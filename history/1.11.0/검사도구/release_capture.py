"""Windows 검사 출력의 단일 소유·유한 수집과 후손 종료를 제공한다."""
from __future__ import annotations

import codecs
import ctypes
from ctypes import wintypes
import json
import msvcrt
import os
from pathlib import Path
import subprocess
import sys
import time

MAX_CAPTURE_BYTES = 64 * 1024
MAX_DOCUMENT_BYTES = 64 * 1024
DRAIN_SECONDS = 1.0
POLL_SECONDS = 0.005


class WindowsJob:
    """장벽 뒤에 시작하는 검사와 후손을 같은 종료 범위에 넣는다."""

    def __init__(self):
        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class Io(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                         "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", Io), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.SetInformationJobObject.restype = wintypes.BOOL
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, process):
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            if not self.kernel.CloseHandle(self.handle):
                raise ctypes.WinError(ctypes.get_last_error())
            self.handle = None


class PipeReader:
    """같은 호출자만 파이프를 조회·읽기·닫기하며 읽기 스레드는 만들지 않는다."""

    def __init__(self, stream):
        self.fd = stream.fileno()
        self.handle = msvcrt.get_osfhandle(self.fd)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.PeekNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                             ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        self.kernel.PeekNamedPipe.restype = wintypes.BOOL

    def read_available(self):
        """None은 아직 없음, 빈 바이트는 EOF이며 그 밖의 오류는 숨기지 않는다."""
        available = wintypes.DWORD()
        if not self.kernel.PeekNamedPipe(self.handle, None, 0, None, ctypes.byref(available), None):
            error = ctypes.get_last_error()
            if error == 109:
                return b""
            raise ctypes.WinError(error)
        if not available.value:
            return None
        # bufsize=0인 파이프에 다른 소비자가 없어 확인한 가용량보다 많이 기다리지 않는다.
        return os.read(self.fd, min(4096, available.value))


def run_check(check: dict) -> dict:
    result = {key: check[key] for key in ("id", "argv", "cwd", "timeout_seconds")}
    started = time.monotonic()
    deadline = started + check["timeout_seconds"]
    captured = bytearray()
    output_bytes = 0
    invalid_utf8 = False
    validator = codecs.getincrementaldecoder("utf-8")(errors="surrogateescape")
    process = job = reader = None
    eof = False
    capture_error = None
    cleanup_errors = []

    def consume(chunk):
        nonlocal output_bytes, invalid_utf8
        output_bytes += len(chunk)
        invalid_utf8 |= any(0xDC80 <= ord(char) <= 0xDCFF for char in validator.decode(chunk, final=False))
        captured.extend(chunk[:max(0, MAX_CAPTURE_BYTES - len(captured))])

    try:
        if os.name != "nt":
            raise OSError("이 수집기는 Windows 전용입니다.")
        payload = json.dumps({"argv": check["argv"], "cwd": check["cwd"]}).encode("utf-8")
        if len(payload) > MAX_DOCUMENT_BYTES:
            raise ValueError("검사 실행 인수 크기 상한 초과")
        job = WindowsJob()
        process = subprocess.Popen([sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve()), "--run-child"],
                                   cwd=check["cwd"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, shell=False, bufsize=0,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        job.assign(process)
        reader = PipeReader(process.stdout)
        # Python 3.12 Windows 파이프의 비차단 쓰기로 래퍼 기동 지연도 같은 deadline에 둔다.
        os.set_blocking(process.stdin.fileno(), False)
        sent = 0
        while True:
            if time.monotonic() >= deadline:
                result.update(status="timeout", exit_code=None, error="제한 시간 초과: 검사와 자식 프로세스의 종료를 요청했습니다.")
                break
            if not process.stdin.closed:
                if sent < len(payload):
                    try:
                        sent += os.write(process.stdin.fileno(), payload[sent:sent + 4096])
                    except BlockingIOError:
                        pass
                if sent == len(payload):
                    process.stdin.close()
            chunk = reader.read_available()
            if chunk == b"":
                eof = True
            elif chunk:
                consume(chunk)
            code = process.poll()
            if code is not None:
                result.update(status="passed" if code == 0 else "failed", exit_code=code)
                break
            if not chunk:
                time.sleep(min(POLL_SECONDS, max(0, deadline - time.monotonic())))
    except (OSError, ValueError) as exc:
        capture_error = str(exc)
        result.update(status="error", exit_code=None, error=capture_error)
    finally:
        if job:
            try:
                # 정상 종료 때 파이프를 붙든 후손도 종료한 뒤 남은 출력만 유한하게 비운다.
                job.close()
            except OSError as exc:
                cleanup_errors.append(str(exc))
        if process:
            if process.poll() is None:
                try:
                    process.kill()
                except OSError as exc:
                    cleanup_errors.append(str(exc))
            try:
                process.wait(timeout=0.5)
            except (OSError, subprocess.TimeoutExpired) as exc:
                cleanup_errors.append(str(exc))
            drain_deadline = time.monotonic() + DRAIN_SECONDS
            if reader and not capture_error:
                try:
                    while not eof and time.monotonic() < drain_deadline:
                        chunk = reader.read_available()
                        if chunk == b"":
                            eof = True
                        elif chunk:
                            consume(chunk)
                        else:
                            time.sleep(POLL_SECONDS)
                except (OSError, ValueError) as exc:
                    capture_error = str(exc)
            for stream in (process.stdin, process.stdout):
                if stream and not stream.closed:
                    try:
                        stream.close()
                    except OSError as exc:
                        cleanup_errors.append(str(exc))
    if eof:
        invalid_utf8 |= any(0xDC80 <= ord(char) <= 0xDCFF for char in validator.decode(b"", final=True))
    complete = eof and not capture_error
    if not complete or cleanup_errors:
        detail = capture_error or ("출력 EOF 미확인: 수집이 완료되지 않았습니다." if not eof else
                                   "프로세스·파이프 종료 오류: " + "; ".join(cleanup_errors))
        result["capture_error"] = detail
        result["cleanup_errors"] = cleanup_errors
        if result.get("status") == "passed":
            result.update(status="error", error=detail)
    truncated = output_bytes > len(captured)
    decoder = codecs.getincrementaldecoder("utf-8")(errors="backslashreplace")
    output = decoder.decode(captured, final=complete and not truncated)
    boundary_bytes = len(decoder.getstate()[0])
    display = output.encode("utf-8")
    display_truncated = len(display) > MAX_CAPTURE_BYTES
    if display_truncated:
        output = display[:MAX_CAPTURE_BYTES].decode("utf-8", errors="ignore")
    result.update(duration_seconds=round(time.monotonic() - started, 3), output=output,
                  output_bytes=output_bytes, captured_bytes=len(captured), output_truncated=truncated or display_truncated,
                  capture_boundary_omitted_bytes=boundary_bytes, output_invalid_utf8=invalid_utf8,
                  output_display_truncated=display_truncated, output_complete=complete,
                  output_bytes_complete=complete,
                  output_note=("출력 수집 미완료: 바이트 수는 관측한 범위입니다." if not complete else
                               "출력 상한으로 나머지를 생략했습니다." if truncated or display_truncated else "전체 출력입니다."))
    return result


def child_main():
    # stdin EOF는 부모의 Job 할당이 끝난 뒤에만 전달된다.
    raw = sys.stdin.buffer.read(MAX_DOCUMENT_BYTES + 1)
    if len(raw) > MAX_DOCUMENT_BYTES:
        return 125
    data = json.loads(raw.decode("utf-8"))
    try:
        return subprocess.call(data["argv"], cwd=data["cwd"], stdin=subprocess.DEVNULL, shell=False)
    except (OSError, ValueError) as exc:
        print(str(exc), flush=True)
        return 126


if __name__ == "__main__" and sys.argv[1:] == ["--run-child"]:
    sys.exit(child_main())
