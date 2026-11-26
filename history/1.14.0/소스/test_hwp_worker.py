"""GUI 초기화 없는 worker와 결과 경계의 실제 동작을 검사한다."""
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class HwpWorkerTests(unittest.TestCase):
    def worker(self):
        self.assertIsNotNone(importlib.util.find_spec('hwp_worker'), '별도 저장 worker가 필요합니다.')
        return importlib.import_module('hwp_worker')

    def test_worker_single_request_and_result(self):
        worker = self.worker()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / '원본.txt'
            source.write_text('worker 한글 123', encoding='utf-8')
            request = root / 'request.json'
            request.write_text(json.dumps({'version': 1, 'source': str(source), 'target': 'hwpx',
                'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}), encoding='utf-8')
            self.assertEqual(0, worker.main([str(request)]))
            result = json.loads((root / 'result.json').read_text(encoding='utf-8'))
            self.assertIs(result['ok'], True)
            self.assertEqual('output.hwpx', result['output'])
            self.assertTrue((root / result['output']).is_file())
            self.assertLessEqual((root / 'result.json').stat().st_size, 65536)

    def test_cli_before_gui_and_bad_request(self):
        self.worker()
        app = Path(__file__).with_name('app.py')
        result = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(app), '--hwp-worker'],
                                capture_output=True, timeout=15)
        self.assertEqual(2, result.returncode)
        self.assertNotIn(b'QApplication', result.stderr)
        self.assertNotIn(b'WinDLL', result.stderr)

    def test_schema_hash_and_preexisting_result_refused(self):
        worker = self.worker()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / '원본.txt'
            source.write_bytes(b'original')
            request = root / 'request.json'
            request.write_text(json.dumps({'version': 1, 'source': str(source), 'target': 'hwpx',
                'source_sha256': '0' * 64}), encoding='utf-8')
            self.assertEqual(1, worker.main([str(request)]))
            result = json.loads((root / 'result.json').read_text(encoding='utf-8'))
            self.assertIs(result['ok'], False)
            self.assertFalse((root / 'output.hwpx').exists())
            with self.assertRaises(FileExistsError):
                worker.main([str(request)])
            self.assertEqual(b'original', source.read_bytes())


class HwpOwnedWorkerTests(unittest.TestCase):
    """취소·시간·메시지·출력 검증 누락이 실제 소유 자식에서 드러나게 한다."""

    def exercise(self, scenario, error=None, pattern=None):
        import ctypes
        from ctypes import wintypes
        import os
        import threading
        import time
        from types import SimpleNamespace
        from unittest.mock import patch
        import engine

        # 외부 변환기 대신 제어된 자식만 주입한다. Popen·Job·종료·회수는 제품 그대로다.
        probe = r"""
import hashlib, json, os, subprocess, sys, time
from pathlib import Path
request = Path(sys.argv[1])
mode = sys.argv[2]
root = request.parent
data = json.loads(request.read_text(encoding='utf-8'))
output = root / 'output.hwpx'
output.write_bytes(b'controlled-worker-output')
result = {'version':1, 'ok':True, 'format':'hwpx', 'source_sha256':data['source_sha256'],
          'output':'output.hwpx', 'output_sha256':hashlib.sha256(output.read_bytes()).hexdigest()}
if mode in ('cancel', 'timeout'):
    child = subprocess.Popen([sys.executable, '-B', '-X', 'utf8', '-c', 'import time; time.sleep(45)'],
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    (root / 'ready.json').write_text(json.dumps({'pid':child.pid}), encoding='utf-8')
    time.sleep(45)
elif mode == 'oversize_json':
    (root / 'result.json').write_bytes(b' ' * 65537)
elif mode == 'duplicate_json':
    (root / 'result.json').write_text('{"ok":true,"ok":false}', encoding='utf-8')
else:
    if mode == 'outside_output': result['output'] = '../output.hwpx'
    if mode == 'bad_hash': result['output_sha256'] = '0' * 64
    (root / 'result.json').write_text(json.dumps(result), encoding='utf-8')
    if mode == 'overflow_log': os.write(1, b'x' * 65537)
    if mode == 'exact_log': os.write(1, b'x' * 65533 + '\uac00'.encode('utf-8'))
    if mode == 'invalid_utf8': os.write(1, b'\xff')
"""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / '원본.txt'
            source.write_bytes(b'original-source-unchanged')
            before_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            final = root / '기존결과.hwpx'
            final.write_bytes(b'preexisting-published-output')
            work = root / 'work'
            work.mkdir()
            processes = []
            descendant_handles = []
            shifted = False
            cancel = threading.Event()
            real_popen = subprocess.Popen
            real_monotonic = time.monotonic
            old_cancel = getattr(engine._CONTEXT, 'cancel', None)
            engine._CONTEXT.cancel = cancel
            original_check = engine.check_cancel
            kernel = None
            if os.name == 'nt':
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
                kernel.OpenProcess.restype = wintypes.HANDLE
                kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
                kernel.WaitForSingleObject.restype = wintypes.DWORD
                kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                kernel.CloseHandle.restype = wintypes.BOOL

            def launch(argv, **kwargs):
                self.assertIn('--hwp-worker', argv)
                request = argv[-1]
                process = real_popen([sys.executable, '-B', '-X', 'utf8', '-c', probe,
                                      str(request), scenario], **kwargs)
                processes.append(process)
                return process

            def observe_cancel():
                nonlocal shifted
                ready = list(work.glob('hwp-*/ready.json'))
                if ready and not shifted:
                    pid = json.loads(ready[0].read_text(encoding='utf-8'))['pid']
                    if kernel is not None:
                        handle = kernel.OpenProcess(0x100000, False, pid)
                        self.assertTrue(handle, '살아 있는 자체 후손의 종료 관측 핸들이 필요합니다.')
                        descendant_handles.append(handle)
                        self.assertEqual(258, kernel.WaitForSingleObject(handle, 0))
                    shifted = True
                    if scenario == 'cancel':
                        cancel.set()
                original_check()

            def controlled_clock():
                # READY 이후 단조시계만 1801초 이동한다. 실제 30분 시험이 아니다.
                return real_monotonic() + (1801 if shifted and scenario == 'timeout' else 0)

            returned = []
            try:
                with patch.object(engine.subprocess, 'Popen', launch), \
                     patch.object(engine, 'check_cancel', observe_cancel), \
                     patch.object(engine, 'time', SimpleNamespace(monotonic=controlled_clock, sleep=time.sleep)):
                    if error is None:
                        returned.append(engine.run_hwp_worker(source, 'hwpx', work))
                    else:
                        with self.assertRaisesRegex(error, pattern):
                            returned.append(engine.run_hwp_worker(source, 'hwpx', work))
                self.assertEqual(1, len(processes))
                process = processes[0]
                self.assertIsNotNone(process.poll(), '실제 직접 자식이 종료되어야 합니다.')
                self.assertTrue(process.stdout.closed, '실제 파이프를 회수하고 닫아야 합니다.')
                if kernel is not None:
                    tree = process._flipring_owned_tree
                    self.assertFalse(tree.handle, '소유 Job 핸들을 정리해야 합니다.')
                    self.assertFalse(tree.port, 'Job 알림 포트를 정리해야 합니다.')
                    self.assertEqual({}, tree.process_handles)
                    for handle in descendant_handles:
                        self.assertEqual(0, kernel.WaitForSingleObject(handle, 0), '자체 후손의 실제 종료 신호')
                if scenario in ('cancel', 'timeout'):
                    self.assertTrue(shifted, '후손 실행 이후 취소·시간초과 분기에 도달해야 합니다.')
                    if kernel is not None:
                        self.assertEqual(1, len(descendant_handles))
                self.assertEqual(before_hash, hashlib.sha256(source.read_bytes()).hexdigest())
                self.assertEqual(b'preexisting-published-output', final.read_bytes())
                self.assertEqual({'원본.txt', '기존결과.hwpx', 'work'}, {p.name for p in root.iterdir()})
                if error is not None:
                    self.assertEqual([], returned, '거부된 임시 출력을 호출자에게 게시하면 안 됩니다.')
                else:
                    self.assertEqual(b'controlled-worker-output', returned[0].read_bytes())
                    self.assertEqual(work.resolve(), returned[0].parent.parent.resolve())
            finally:
                engine._CONTEXT.cancel = old_cancel
                # 단언 실패 시에도 이 시험이 소유한 자식만 회수한다. 정리 오류는 숨기지 않는다.
                for process in processes:
                    if process.poll() is None:
                        engine._finish_owned_process(process, real_monotonic() + 15)
                    if process.stdout is not None and not process.stdout.closed:
                        process.stdout.close()
                for handle in descendant_handles:
                    self.assertTrue(kernel.CloseHandle(handle))

    def test_cancel_terminates_owned_worker_and_descendant(self):
        import engine
        self.exercise('cancel', engine.Cancelled, '취소')

    def test_controlled_timeout_terminates_owned_worker_and_descendant(self):
        self.exercise('timeout', RuntimeError, '제한 시간')

    def test_oversized_result_json_is_not_published(self):
        self.exercise('oversize_json', ValueError, '메시지 크기 제한')

    def test_duplicate_result_json_is_not_published(self):
        self.exercise('duplicate_json', ValueError, '중복 키')

    def test_outside_output_path_is_not_published(self):
        self.exercise('outside_output', RuntimeError, '출력 경계')

    def test_wrong_output_hash_is_not_published(self):
        self.exercise('bad_hash', RuntimeError, '출력 해시')

    def test_log_over_64k_is_not_published(self):
        self.exercise('overflow_log', RuntimeError, '64KiB')

    def test_invalid_utf8_log_is_not_published(self):
        self.exercise('invalid_utf8', UnicodeDecodeError, 'utf-8')

    def test_exact_64k_utf8_log_is_accepted(self):
        self.exercise('exact_log')


if __name__ == '__main__':
    unittest.main()
