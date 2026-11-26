"""격리 문서 종료의 원예외 보존과 실패 반환을 검사한다."""
import contextlib
import io
import json
import subprocess
import unittest
from unittest.mock import Mock, patch

import document_bridge


class DocumentShutdownTests(unittest.TestCase):
    def error_json(self, error):
        output = io.StringIO()
        with patch.object(document_bridge.sys, 'argv', ['bridge', 'request.json']), \
                patch.object(document_bridge.Path, 'read_text', return_value='{}'), \
                patch.object(document_bridge, 'convert', side_effect=error), \
                contextlib.redirect_stderr(output):
            self.assertEqual(1, document_bridge.main())
        return json.loads(output.getvalue())

    def test_01_primary_disposal_preserves_original_and_skips_uno_calls(self):
        for stop_fails in (False, True):
            with self.subTest(stop_fails=stop_fails):
                original = RuntimeError('최초 변환 연결 단절')
                document, desktop, process = Mock(), Mock(), Mock()
                with patch.object(document_bridge, '_stop',
                                  side_effect=OSError('로컬 회수 실패') if stop_fails else None) as stop:
                    with self.assertRaises(RuntimeError) as failure:
                        document_bridge._shutdown_office(document, desktop, process, original)
                self.assertIs(original, failure.exception)
                document.close.assert_not_called()
                document.dispose.assert_not_called()
                desktop.terminate.assert_not_called()
                stop.assert_called_once_with(process)
                value = self.error_json(failure.exception)
                self.assertIn('최초 변환 연결 단절', value['error'])
                if stop_fails:
                    self.assertIsNotNone(failure.exception.__cause__)
                    self.assertIn('로컬 회수 실패', str(failure.exception.__cause__))
                    self.assertIn('로컬 회수 실패', value['cause'])

    def test_02_close_failure_never_calls_dispose_or_desktop_again(self):
        original = RuntimeError('최초 close 연결 단절')
        document, desktop, process = Mock(), Mock(), Mock()
        document.close.side_effect = original
        with patch.object(document_bridge, '_stop') as stop:
            with self.assertRaises(RuntimeError) as failure:
                document_bridge._shutdown_office(document, desktop, process, None)
        self.assertIs(original, failure.exception)
        document.close.assert_called_once_with(True)
        document.dispose.assert_not_called()
        desktop.terminate.assert_not_called()
        stop.assert_called_once_with(process)
        self.assertIn('최초 close 연결 단절', self.error_json(failure.exception)['error'])

    def test_03_termination_rejection_timeout_and_recovery_failures_never_succeed(self):
        cases = ['terminate_false', 'terminate_throw', 'wait_nonzero', 'wait_timeout',
                 'terminate_false_stop_failure', 'wait_timeout_stop_failure']
        for case in cases:
            with self.subTest(case=case):
                document, desktop, process = Mock(), Mock(), Mock()
                desktop.terminate.return_value = not case.startswith('terminate_false')
                process.wait.return_value = 0
                if case == 'terminate_throw':
                    desktop.terminate.side_effect = RuntimeError('종료 호출 연결 단절')
                if case == 'wait_nonzero':
                    process.wait.return_value = 23
                if case.startswith('wait_timeout'):
                    process.wait.side_effect = subprocess.TimeoutExpired('자체 Office', 5)
                with patch.object(document_bridge, '_stop',
                                  side_effect=OSError('추가 회수 실패') if case.endswith('stop_failure') else None) as stop:
                    with self.assertRaises(Exception) as failure:
                        document_bridge._shutdown_office(document, desktop, process, None)
                document.dispose.assert_not_called()
                value = self.error_json(failure.exception)
                self.assertFalse(value['ok'])
                self.assertTrue(value['error'])
                if case == 'wait_nonzero':
                    self.assertIn('23', value['error'])
                if case.startswith('wait_timeout'):
                    self.assertIn('5', value['error'])
                    stop.assert_called_once_with(process)
                if case.endswith('stop_failure'):
                    self.assertIn('추가 회수 실패', value['cause'])

    def test_04_normal_close_approved_termination_and_zero_exit_succeed(self):
        document, desktop, process = Mock(), Mock(), Mock()
        desktop.terminate.return_value = True
        process.wait.return_value = 0
        with patch.object(document_bridge, '_stop') as stop:
            self.assertIsNone(document_bridge._shutdown_office(document, desktop, process, None))
        document.close.assert_called_once_with(True)
        document.dispose.assert_not_called()
        desktop.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=5)
        stop.assert_not_called()


if __name__ == '__main__':
    unittest.main()
