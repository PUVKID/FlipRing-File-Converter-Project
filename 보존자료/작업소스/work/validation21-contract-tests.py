"""검증 실행기의 누락·중복·건너뜀·옵션 우회를 거부하는 계약 회귀다."""
from pathlib import Path
import copy
import importlib.util
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / '.codex/release_validation.py'


class ContractTests(unittest.TestCase):
    def module(self):
        spec = importlib.util.spec_from_file_location('release_validation_contract', HELPER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_01_manifest_and_helper_required(self):
        self.assertTrue(HELPER.is_file(), '격리 병렬 검증 실행기가 아직 없습니다.')
        contract = self.module().load_contract()
        self.assertEqual(len(contract['test_ids']), 85)
        self.assertEqual([len(x['test_ids']) for x in contract['shards']], [23, 1, 25, 20, 16])

    def test_02_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):
            self.module().validate_ids(['a', 'b'], ['a', 'a'])

    def test_03_missing_ids_rejected(self):
        with self.assertRaises(ValueError):
            self.module().validate_ids(['a', 'b'], ['a'])

    def test_04_order_change_rejected(self):
        with self.assertRaises(ValueError):
            self.module().validate_ids(['a', 'b'], ['b', 'a'])

    def test_05_unexpected_id_rejected(self):
        with self.assertRaises(ValueError):
            self.module().validate_ids(['a', 'b'], ['a', 'c'])

    def test_06_skip_is_not_success(self):
        with self.assertRaises(ValueError):
            self.module().validate_counts({'testsRun': 2, 'failures': 0, 'errors': 0, 'skipped': 1}, 2)

    def test_07_error_is_not_success(self):
        with self.assertRaises(ValueError):
            self.module().validate_counts({'testsRun': 2, 'failures': 0, 'errors': 1, 'skipped': 0}, 2)

    def test_08_boolean_count_rejected(self):
        with self.assertRaises(ValueError):
            self.module().validate_counts({'testsRun': True, 'failures': 0, 'errors': 0, 'skipped': 0}, 1)

    def test_09_real_pdf_options_required(self):
        valid = {'tests': 28, 'passed': 28, 'ocr_enabled': True, 'gui_enabled': True,
                 'skipped': [], 'failures': [], 'errors': []}
        self.module().validate_pdf(valid)
        for key, value in [('ocr_enabled', False), ('gui_enabled', False), ('skipped', [{'test': 'a'}]), ('tests', 27)]:
            broken = copy.deepcopy(valid)
            broken[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.module().validate_pdf(broken)


if __name__ == '__main__':
    unittest.main(verbosity=2, failfast=True)
