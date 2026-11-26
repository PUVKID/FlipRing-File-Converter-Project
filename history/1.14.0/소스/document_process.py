"""문서 도우미의 시작·취소·후손 종료를 한 작업의 소유 범위로 제한한다."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from pdf_tools import _ProcessTree, _resume_ocr_process, Cancelled as PdfCancelled


def _set_dll_directory(path):
    """DLL 검색 경로 변경 실패를 숨기지 않고 Windows 오류로 보고한다."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.SetDllDirectoryW.argtypes = [wintypes.LPCWSTR]
    kernel.SetDllDirectoryW.restype = wintypes.BOOL
    if not kernel.SetDllDirectoryW(path):
        code = ctypes.get_last_error()
        raise OSError(code, "문서 도우미의 DLL 검색 경로를 변경하지 못했습니다.")


class _OfficeTree(_ProcessTree):
    """Job 알림과 실제 Job 목록을 교차 확인해 소유 프로세스 핸들을 보관한다."""
    def __init__(self, process):
        self.port, self.process_handles = None, {}
        self.cleanup_deadline = None
        super().__init__(process)
        if os.name != "nt":
            return
        kernel = self.kernel
        kernel.CreateIoCompletionPort.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.c_size_t, wintypes.DWORD]
        kernel.CreateIoCompletionPort.restype = wintypes.HANDLE
        kernel.GetQueuedCompletionStatus.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD),
                                                     ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_void_p), wintypes.DWORD]
        kernel.GetQueuedCompletionStatus.restype = wintypes.BOOL
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
        kernel.IsProcessInJob.restype = wintypes.BOOL
        kernel.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        kernel.QueryInformationJobObject.restype = wintypes.BOOL
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.TerminateJobObject.restype = wintypes.BOOL
        class Port(ctypes.Structure):
            _fields_ = [("key", ctypes.c_void_p), ("port", wintypes.HANDLE)]
        try:
            # 알림은 전달이 보장되지 않으므로 단독 종료 근거로 사용하지 않는다.
            self.port = kernel.CreateIoCompletionPort(ctypes.c_void_p(-1).value, None, 0, 1)
            if not self.port:
                raise ctypes.WinError(ctypes.get_last_error())
            association = Port(1, self.port)
            if not kernel.SetInformationJobObject(self.handle, 7, ctypes.byref(association), ctypes.sizeof(association)):
                raise ctypes.WinError(ctypes.get_last_error())
            self._remember(process.pid)
            self.collect()
        except BaseException:
            self.close()
            raise

    def _remember(self, pid):
        if not pid or pid in self.process_handles:
            return
        handle = self.kernel.OpenProcess(0x100000 | 0x1000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:
                return  # 이미 소멸한 PID의 알림은 현재 프로세스로 추정하지 않는다.
            raise ctypes.WinError(ctypes.get_last_error())
        owned = wintypes.BOOL()
        if not self.kernel.IsProcessInJob(handle, self.handle, ctypes.byref(owned)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.kernel.CloseHandle(handle)
            raise error
        if owned.value:
            self.process_handles[pid] = handle
        else:
            # PID가 재사용되어 다른 Job에 속하면 그 프로세스를 기다리거나 종료하지 않는다.
            self.kernel.CloseHandle(handle)

    def collect(self):
        if os.name != "nt" or not self.handle:
            return []
        while True:
            message, key, pid = wintypes.DWORD(), ctypes.c_size_t(), ctypes.c_void_p()
            if not self.kernel.GetQueuedCompletionStatus(self.port, ctypes.byref(message), ctypes.byref(key), ctypes.byref(pid), 0):
                if ctypes.get_last_error() == 258:
                    break
                raise ctypes.WinError(ctypes.get_last_error())
            if key.value != 1:
                raise RuntimeError("문서 Job 알림의 소유 키가 일치하지 않습니다.")
            if message.value == 6:
                self._remember(pid.value)
        capacity = 32
        while True:
            class ProcessIds(ctypes.Structure):
                _fields_ = [("assigned", wintypes.DWORD), ("listed", wintypes.DWORD),
                            ("ids", ctypes.c_size_t * capacity)]
            info = ProcessIds()
            if self.kernel.QueryInformationJobObject(self.handle, 3, ctypes.byref(info), ctypes.sizeof(info), None):
                ids = list(info.ids[:info.listed])
                for pid in ids:
                    self._remember(pid)
                return ids
            error = ctypes.get_last_error()
            if error != 234 or capacity >= 16384:
                raise ctypes.WinError(error)
            capacity = min(16384, max(capacity * 2, info.assigned + 8))

    def close(self):
        errors = []
        for handle in self.process_handles.values():
            if not self.kernel.CloseHandle(handle):
                errors.append(ctypes.WinError(ctypes.get_last_error()))
        self.process_handles.clear()
        if self.port:
            if not self.kernel.CloseHandle(self.port):
                errors.append(ctypes.WinError(ctypes.get_last_error()))
            self.port = None
        try:
            super().close()
        except OSError as error:
            errors.append(error)
        if errors:
            raise errors[0]


def _finish_job(tree, terminate):
    """Job 구성원 수와 보관한 실제 프로세스의 종료 신호를 모두 확인한다."""
    if os.name != "nt" or not tree.handle:
        return
    tree.collect()
    if terminate and not tree.kernel.TerminateJobObject(tree.handle, 1):
        raise ctypes.WinError(ctypes.get_last_error())
    deadline = tree.cleanup_deadline
    while True:
        active = tree.collect()
        waiting = False
        for handle in tree.process_handles.values():
            status = tree.kernel.WaitForSingleObject(handle, 0)
            if status == 258:
                waiting = True
            elif status != 0:
                raise ctypes.WinError(ctypes.get_last_error())
        if not active and not waiting:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("문서 도우미의 실제 후손 종료를 10초 안에 확인하지 못했습니다.")
        time.sleep(0.01)


def _wait_profile_unlocked(work, deadline):
    """자식 종료 뒤 OS가 임시 파일의 삭제 공유까지 반환했는지 확인한다."""
    if os.name != "nt":
        return
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    while True:
        blocked = False
        for path in work.rglob("*"):
            if not path.is_file():
                continue
            handle = kernel.CreateFileW(str(path), 0x10000, 7, None, 3, 0, None)
            if handle == ctypes.c_void_p(-1).value:
                error = ctypes.get_last_error()
                if error not in (32, 33):
                    raise ctypes.WinError(error)
                blocked = True
            elif not kernel.CloseHandle(handle):
                raise ctypes.WinError(ctypes.get_last_error())
        if not blocked:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("문서 임시 프로필의 파일 잠금이 10초 안에 해제되지 않았습니다.")
        time.sleep(0.01)


def run_bridge(argv, work, cancel, check_cancel, timeout=1800):
    """도우미가 자식을 만들기 전에 Job에 묶고 취소 후 정리가 끝날 때까지 기다린다."""
    work = Path(work)
    log = work / "document-process.log"
    flags = subprocess.CREATE_NO_WINDOW | 0x00000004 if os.name == "nt" else 0
    process = tree = cleanup_deadline = None
    deadline = time.monotonic() + timeout
    check_cancel()
    try:
        with log.open("wb") as stream:
            try:
                frozen = os.name == "nt" and getattr(sys, "frozen", False)
                if frozen:
                    _set_dll_directory(None)
                launch_error = None
                try:
                    process = subprocess.Popen(list(map(str, argv)), cwd=work, stdin=subprocess.DEVNULL,
                                               stdout=stream, stderr=stream, shell=False,
                                               creationflags=flags, start_new_session=os.name != "nt")
                except BaseException as error:
                    launch_error = error
                    raise
                finally:
                    if frozen:
                        try:
                            _set_dll_directory(sys._MEIPASS)
                        except OSError as error:
                            if launch_error is not None:
                                raise error from launch_error
                            raise
                tree = _OfficeTree(process)
                if os.name == "nt":
                    try:
                        _resume_ocr_process(process, cancel, deadline)
                    except PdfCancelled:
                        check_cancel()
                        raise
                while process.poll() is None:
                    tree.collect()
                    check_cancel()
                    if time.monotonic() >= deadline:
                        raise RuntimeError("문서 변환 제한 시간 30분을 초과했습니다.")
                    if cancel is not None:
                        cancel.wait(0.05)
                    else:
                        time.sleep(0.05)
                check_cancel()
                if process.returncode:
                    stream.flush()
                    with log.open("rb") as output:
                        output.seek(max(0, log.stat().st_size - 8000))
                        detail = output.read().decode("utf-8", "replace")
                    raise RuntimeError(f"문서 변환 실패 ({process.returncode})\n{detail}")
            finally:
                pending = sys.exc_info()[1]
                cleanup_deadline = time.monotonic() + 10
                errors = []
                if tree is not None:
                    tree.cleanup_deadline = cleanup_deadline
                    try:
                        tree.collect()
                    except Exception as error:
                        errors.append(error)
                # 정지 생성한 직접 자식은 Job보다 먼저 종료를 요청해야 상속 핸들도 회수된다.
                if process is not None and process.poll() is None:
                    try:
                        process.kill()
                    except OSError as error:
                        if process.poll() is None:
                            errors.append(error)
                if tree is not None:
                    try:
                        _finish_job(tree, terminate=True)
                    except Exception as error:
                        errors.append(error)
                    try:
                        tree.close()
                    except Exception as error:
                        errors.append(error)
                if process is not None:
                    if process.poll() is None:
                        try:
                            if os.name != "nt":
                                os.killpg(process.pid, signal.SIGKILL)
                            else:
                                process.kill()
                        except OSError as error:
                            if process.poll() is None:
                                errors.append(error)
                    try:
                        process.wait(timeout=max(0, cleanup_deadline - time.monotonic()))
                    except Exception as error:
                        errors.append(error)
                if errors:
                    error = RuntimeError("문서 도우미 종료를 확인하지 못했습니다: " + "; ".join(map(str, errors)))
                    if pending is not None:
                        raise error from pending
                    raise error
    finally:
        # 부모의 로그 핸들도 닫힌 다음, 동일한 정리 기한으로 잠금 반환을 검사한다.
        if cleanup_deadline is not None:
            pending = sys.exc_info()[1]
            try:
                _wait_profile_unlocked(work, cleanup_deadline)
            except Exception as error:
                if pending is not None:
                    raise RuntimeError("문서 임시 프로필 정리 실패: " + str(error)) from pending
                raise
    return log
