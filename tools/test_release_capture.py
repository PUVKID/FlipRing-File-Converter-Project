"""실제 Windows 자식과 제한된 결함 주입으로 수집기 계약을 검사한다."""
import ctypes
from ctypes import wintypes
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import release_capture as capture

ROOT = Path(__file__).resolve().parents[1]
LOG = Path(os.environ.get("FLIPRING_CAPTURE_TEST_OUTPUT", tempfile.gettempdir())) / "FlipRing-capture-tests"
RUN_TIMEOUT_SECONDS = 27


def append_record(data):
    LOG.mkdir(parents=True, exist_ok=True)
    with (LOG / "회귀실행.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps({"kst": datetime.now().astimezone().isoformat(), **data}, ensure_ascii=False) + "\n")


class CaptureTests(unittest.TestCase):
    def run_code(self, code, timeout=RUN_TIMEOUT_SECONDS):
        check = {"id": self.id(), "argv": [sys.executable, "-B", "-X", "utf8", "-c", code],
                 "cwd": str(ROOT), "timeout_seconds": timeout}
        result = capture.run_check(check)
        append_record({"kind": "수집기결과", "check": check, "result": result})
        self.assertLess(result["duration_seconds"], timeout + 2, result)
        return result

    def assert_complete(self, result, status="passed"):
        self.assertEqual(result["status"], status, result)
        self.assertTrue(result["output_complete"], result)
        self.assertTrue(result["output_bytes_complete"], result)

    def assert_dead(self, pid):
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x100000, False, pid)
        if handle:
            try:
                self.assertEqual(kernel.WaitForSingleObject(handle, 1500), 0, "후손 프로세스 생존")
            finally:
                kernel.CloseHandle(handle)
        else:
            self.assertEqual(ctypes.get_last_error(), 87, "프로세스 종료 여부 조회 실패")

    def test_normal_stdout_stderr(self):
        result = self.run_code("import os; os.write(1,'정상\\n'.encode()); os.write(2,b'error-stream\\n')")
        self.assert_complete(result)
        self.assertEqual(result["output"], "정상\nerror-stream\n")
        self.assertEqual(result["output_bytes"], len(result["output"].encode()))

    def test_nonzero_exit(self):
        result = self.run_code("import sys; print('failure'); sys.exit(7)")
        self.assert_complete(result, "failed")
        self.assertEqual(result["exit_code"], 7)

    def test_large_output_total_and_cap(self):
        result = self.run_code("import os; os.write(1,b'a'*400000)")
        self.assert_complete(result)
        self.assertEqual(result["output_bytes"], 400000)
        self.assertEqual(result["captured_bytes"], 65536)
        self.assertEqual(result["output"], "a" * 65536)
        self.assertTrue(result["output_truncated"])

    def test_utf8_boundary_is_not_invalid(self):
        result = self.run_code("import os; os.write(1,b'a'*65535+'한'.encode()+b'end')")
        self.assert_complete(result)
        self.assertEqual(result["capture_boundary_omitted_bytes"], 1)
        self.assertEqual(result["output"], "a" * 65535)
        self.assertFalse(result["output_invalid_utf8"])

    def test_utf8_across_read_boundaries(self):
        result = self.run_code("import os; os.write(1,b'a'*4095+'한글'.encode())")
        self.assert_complete(result)
        self.assertEqual(result["output"], "a" * 4095 + "한글")
        self.assertFalse(result["output_invalid_utf8"])

    def test_invalid_utf8_and_final_partial(self):
        result = self.run_code("import os; os.write(1,b'\\xff\\xe3')")
        self.assert_complete(result)
        self.assertTrue(result["output_invalid_utf8"])
        self.assertEqual(result["output"], r"\xff\xe3")
        self.assertEqual(result["capture_boundary_omitted_bytes"], 0)

    def test_invalid_utf8_beyond_capture(self):
        result = self.run_code("import os; os.write(1,b'a'*65536+b'\\xff')")
        self.assert_complete(result)
        self.assertTrue(result["output_invalid_utf8"])
        self.assertEqual(result["output_bytes"], 65537)

    def test_invalid_display_expansion_stays_bounded(self):
        result = self.run_code("import os; os.write(1,b'\\xff'*65536)")
        self.assert_complete(result)
        self.assertTrue(result["output_display_truncated"])
        self.assertLessEqual(len(result["output"].encode()), 65536)

    def test_timeout_terminates_descendant(self):
        child = "import time; time.sleep(60)"
        code = "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c'," + repr(child) + "]); print(p.pid,flush=True); time.sleep(60)"
        result = self.run_code(code, timeout=RUN_TIMEOUT_SECONDS)
        self.assertEqual(result["status"], "timeout", result)
        self.assertIsNone(result["exit_code"])
        self.assertGreaterEqual(result["duration_seconds"], RUN_TIMEOUT_SECONDS)
        self.assertLess(result["duration_seconds"], RUN_TIMEOUT_SECONDS + 2)
        if result["output_complete"]:
            self.assertTrue(result["output_bytes_complete"], result)
            self.assertNotIn("capture_error", result)
            self.assertEqual(result["output_note"], "전체 출력입니다.")
        else:
            # Windows 비동기 종료 중 남은 출력은 완전 수집으로 주장하지 않는다.
            self.assertFalse(result["output_bytes_complete"], result)
            self.assertTrue(result["capture_error"], result)
            self.assertIn("미완료", result["output_note"])
            self.assertNotEqual(result["status"], "passed")
        self.assertEqual(result["output_bytes"], len(result["output"].encode("utf-8")))
        self.assertEqual(result["captured_bytes"], result["output_bytes"])
        pid_text = result["output"].strip()
        self.assertTrue(pid_text, "시간 초과 전에 후손 PID를 출력하지 않았습니다.")
        self.assertTrue(pid_text.isdecimal(), "후손 PID 출력이 십진 정수가 아닙니다: " + repr(pid_text))
        self.assert_dead(int(pid_text))

    def test_parent_exit_with_descendant_holding_pipe(self):
        code = "import subprocess,sys; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); print(p.pid,flush=True)"
        result = self.run_code(code)
        self.assert_complete(result)
        self.assertLess(result["duration_seconds"], RUN_TIMEOUT_SECONDS + 2)
        self.assert_dead(int(result["output"].strip()))

    def test_reader_failure_cannot_pass(self):
        with patch.object(capture.PipeReader, "read_available", side_effect=OSError("주입된 읽기 오류")):
            result = self.run_code("pass")
        self.assertEqual(result["status"], "error")
        self.assertFalse(result["output_complete"])
        self.assertIn("주입된 읽기 오류", result["capture_error"])

    def test_missing_eof_cannot_pass(self):
        with patch.object(capture.PipeReader, "read_available", return_value=None):
            result = self.run_code("pass")
        self.assertEqual(result["status"], "error")
        self.assertFalse(result["output_complete"])
        self.assertLess(result["duration_seconds"], RUN_TIMEOUT_SECONDS + 2)

    def test_job_assignment_failure_keeps_workload_behind_barrier(self):
        LOG.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=LOG) as folder:
            marker = Path(folder) / "시작표식"
            code = "from pathlib import Path; Path(" + repr(str(marker)) + ").write_text('started')"
            with patch.object(capture.WindowsJob, "assign", side_effect=OSError("주입된 Job 할당 오류")):
                result = self.run_code(code)
            self.assertEqual(result["status"], "error")
            self.assertFalse(marker.exists(), "할당 실패 뒤 작업부하가 시작됨")


class RecordingResult(unittest.TextTestResult):
    def addFailure(self, test, err):
        append_record({"kind": "실패선기록", "test": test.id(), "argv": sys.argv, "cwd": os.getcwd(),
                       "error": self._exc_info_to_string(err, test)})
        super().addFailure(test, err)

    def addError(self, test, err):
        append_record({"kind": "오류선기록", "test": test.id(), "argv": sys.argv, "cwd": os.getcwd(),
                       "error": self._exc_info_to_string(err, test)})
        super().addError(test, err)


if __name__ == "__main__":
    append_record({"kind": "검사시작", "argv": sys.argv, "cwd": os.getcwd(),
                   "source_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                     for path in (Path(__file__), Path(capture.__file__))}})
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CaptureTests)
    result = unittest.TextTestRunner(verbosity=2, resultclass=RecordingResult).run(suite)
    append_record({"kind": "검사종료", "tests": result.testsRun, "failures": len(result.failures),
                   "errors": len(result.errors), "skipped": len(result.skipped), "exit_code": 0 if result.wasSuccessful() else 1})
    sys.exit(0 if result.wasSuccessful() else 1)
