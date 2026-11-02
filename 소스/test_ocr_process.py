"""실제 Windows 자식의 시작 전 Job 보호·취소·실패 정리를 검사한다."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import pdf_tools as tools


@unittest.skipUnless(os.name == 'nt', 'Windows의 Job·정지 생성 전용 검사')
class OcrProcessTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parent.parent / 'work/ocr-startup-tests'
        root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='process-', dir=root)
        self.work = Path(self.temporary.name)
        self.marker = self.work / '실행증거.txt'
        self.cancel = threading.Event()
        self.processes = []

    def tearDown(self):
        for process in self.processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
        self.temporary.cleanup()

    def argv(self, marker=None):
        code = f"from pathlib import Path;Path({str(marker or self.marker)!r}).write_text('ran',encoding='utf-8')"
        return [sys.executable, '-B', '-X', 'utf8', '-c', code]

    def test_01_delayed_assignment_cannot_execute_child(self):
        original = tools._ProcessTree
        def delayed(process):
            self.processes.append(process)
            time.sleep(0.2)
            self.assertIsNone(process.poll())
            self.assertFalse(self.marker.exists(), 'Job 할당 전 자식 코드가 실행됐습니다.')
            return original(process)
        with patch.object(tools, '_ProcessTree', side_effect=delayed):
            tools.run_ocr_process(self.argv(), self.work, self.cancel, timeout=10)
        self.assertEqual(self.processes[0].returncode, 0)
        self.assertEqual(self.marker.read_text(encoding='utf-8'), 'ran')

    def test_02_assignment_denied_never_executes_and_terminates(self):
        def denied(process):
            self.processes.append(process)
            time.sleep(0.2)
            raise ctypes.WinError(5)
        with patch.object(tools, '_ProcessTree', side_effect=denied):
            with self.assertRaises(OSError) as result:
                tools.run_ocr_process(self.argv(), self.work, self.cancel)
        self.assertEqual(result.exception.winerror, 5)
        self.assertFalse(self.marker.exists())
        self.assertIsNotNone(self.processes[0].poll())

    def test_03_cancel_after_assignment_before_resume(self):
        original = tools._ProcessTree
        def assigned(process):
            self.processes.append(process)
            tree = original(process)
            self.cancel.set()
            return tree
        with patch.object(tools, '_ProcessTree', side_effect=assigned):
            with self.assertRaises(tools.Cancelled):
                tools.run_ocr_process(self.argv(), self.work, self.cancel)
        self.assertFalse(self.marker.exists())
        self.assertIsNotNone(self.processes[0].poll())

    def test_04_timeout_during_assignment_cannot_resume(self):
        original = tools._ProcessTree
        def delayed(process):
            self.processes.append(process)
            time.sleep(0.2)
            return original(process)
        with patch.object(tools, '_ProcessTree', side_effect=delayed):
            with self.assertRaises(tools.PdfToolError) as result:
                tools.run_ocr_process(self.argv(), self.work, self.cancel, timeout=0.05)
        self.assertEqual(result.exception.code, 'ocr_timeout')
        self.assertFalse(self.marker.exists())
        self.assertIsNotNone(self.processes[0].poll())

    def test_05_eight_fast_children_finish_with_zero(self):
        original = tools._ProcessTree
        def assigned(process):
            self.processes.append(process)
            return original(process)
        with patch.object(tools, '_ProcessTree', side_effect=assigned):
            for number in range(8):
                marker = self.work / f'실행-{number}.txt'
                tools.run_ocr_process(self.argv(marker), self.work, self.cancel, timeout=10)
                self.assertEqual(marker.read_text(encoding='utf-8'), 'ran')
        self.assertEqual([p.returncode for p in self.processes], [0] * 8)

    def test_06_resume_failure_terminates_without_execution(self):
        original = tools._ProcessTree
        def assigned(process):
            self.processes.append(process)
            return original(process)
        with patch.object(tools, '_ProcessTree', side_effect=assigned), \
                patch.object(tools, '_resume_ocr_process', side_effect=tools.PdfToolError('ocr_startup_state'), create=True):
            with self.assertRaises(tools.PdfToolError) as result:
                tools.run_ocr_process(self.argv(), self.work, self.cancel)
        self.assertEqual(result.exception.code, 'ocr_startup_state')
        self.assertFalse(self.marker.exists())
        self.assertIsNotNone(self.processes[0].poll())

    def test_07_assignment_error_survives_cleanup_last_error(self):
        original = tools._ProcessTree.close
        def close(tree):
            original(tree)
            # 실제 실패 뒤 정리가 마지막 오류를 바꾸는 상황을 제어한다.
            ctypes.set_last_error(1234)
        with patch.object(tools._ProcessTree, 'close', close):
            with self.assertRaises(OSError) as result:
                tools._ProcessTree(SimpleNamespace(_handle=0))
        self.assertEqual(result.exception.winerror, 6)


if __name__ == '__main__':
    unittest.main()
