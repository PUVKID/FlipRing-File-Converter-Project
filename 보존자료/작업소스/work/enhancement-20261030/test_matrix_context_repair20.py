"""실제 변환표 문맥과 메모리 결함 주입으로 좁은 계약을 검사한다."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('release_artifacts_check', ROOT / '.codex/release_artifacts_check.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
RUN = ROOT / 'work/enhancement-20261030/matrix-test/run-bf49e1f2-7b56-471b-918f-3bc495f6e860'


class MatrixContextTests(unittest.TestCase):
    def setUp(self):
        self.context = json.loads((RUN / 'run-context.json').read_text(encoding='utf-8'))
        self.report = (RUN / 'report.json').relative_to(ROOT).as_posix()
        self.engine = str(ROOT / '소스/engine.py')

    def verify(self):
        checker.verify_matrix_context(self.context, self.report)

    def test_actual_context(self):
        self.verify()

    def test_missing_start_entry(self):
        del self.context['start_sha256'][self.engine]
        with self.assertRaises(AssertionError): self.verify()

    def test_missing_end_entry(self):
        del self.context['end_sha256'][self.engine]
        with self.assertRaises(AssertionError): self.verify()

    def test_changed_start_digest(self):
        self.context['start_sha256'][self.engine] = '0' * 64
        with self.assertRaises(AssertionError): self.verify()

    def test_changed_end_digest(self):
        self.context['end_sha256'][self.engine] = '0' * 64
        with self.assertRaises(AssertionError): self.verify()

    def test_equal_but_changed_recorded_digests(self):
        self.context['start_sha256'][self.engine] = '0' * 64
        self.context['end_sha256'][self.engine] = '0' * 64
        with self.assertRaises(AssertionError): self.verify()

    def test_current_digest_differs_without_modifying_original(self):
        original_sha = checker.sha
        # 현재 파일이 달라진 경우만 메모리에서 모사하며 원본에는 쓰지 않는다.
        with patch.object(checker, 'sha', side_effect=lambda path: '0' * 64 if path == ROOT / '소스/engine.py' else original_sha(path)):
            with self.assertRaises(AssertionError): self.verify()

    def test_outside_root_entry(self):
        for field in ('start_sha256', 'end_sha256'):
            self.context[field][str(ROOT.parent / '외부.py')] = self.context[field].pop(self.engine)
        with self.assertRaises(AssertionError): self.verify()

    def test_modified_report_digest(self):
        self.context['report_sha256'] = '0' * 64
        with self.assertRaises(AssertionError): self.verify()

    def test_failed_execution(self):
        self.context['exit_code'] = 1
        with self.assertRaises(AssertionError): self.verify()


if __name__ == '__main__':
    unittest.main(verbosity=2)
