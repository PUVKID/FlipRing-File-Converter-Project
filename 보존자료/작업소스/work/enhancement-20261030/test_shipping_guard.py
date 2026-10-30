"""출하 검사에서 실행부·상응소스 누락과 해시 변조를 거부하는지 검사한다."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
tree = ast.parse((ROOT / '소스/package.py').read_text(encoding='utf-8'))
function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'verify_7zip')
namespace = {'Path': Path, 're': re, 'hashlib': hashlib, 'json': json}
exec(compile(ast.Module(body=[function], type_ignores=[]), '출하검사원문', 'exec'), namespace)


class ShippingGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.vendor = self.root / 'vendor/7zip'
        self.notices = self.root / 'licenses/7Zip'
        names = ['vendor/7zip/7z.exe', 'vendor/7zip/7z.dll'] + ['licenses/7Zip/' + name for name in (
            'License.txt', 'Source-License.txt', 'LGPL-2.1.txt', 'unRarLicense.txt', 'sources/7z2605-src.tar.xz')]
        self.data = {'version': '26.05', 'files': []}
        for name in names:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = ('검증 자료 ' + name).encode('utf-8')
            path.write_bytes(raw)
            self.data['files'].append({'path': name, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
        self.save()

    def tearDown(self):
        self.temporary.cleanup()

    def save(self):
        (self.notices / '출하목록.json').write_text(json.dumps(self.data), encoding='utf-8')

    def run_guard(self):
        return namespace['verify_7zip'](self.vendor, self.notices)

    def test_valid_components(self):
        self.assertEqual(self.run_guard(), self.notices / '출하목록.json')

    def test_missing_corresponding_source(self):
        (self.notices / 'sources/7z2605-src.tar.xz').unlink()
        with self.assertRaises(SystemExit): self.run_guard()

    def test_same_size_modified_binary(self):
        path = self.vendor / '7z.dll'
        raw = path.read_bytes()
        path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        with self.assertRaises(SystemExit): self.run_guard()

    def test_boolean_size_rejected(self):
        self.data['files'][0]['size'] = True
        self.save()
        with self.assertRaises(SystemExit): self.run_guard()

    def test_duplicate_entry_rejected(self):
        self.data['files'][1] = copy.deepcopy(self.data['files'][0])
        self.save()
        with self.assertRaises(SystemExit): self.run_guard()

    def test_external_path_rejected(self):
        self.data['files'][0]['path'] = '../외부파일'
        self.save()
        with self.assertRaises(SystemExit): self.run_guard()

    def test_other_version_rejected(self):
        self.data['version'] = '0.0'
        self.save()
        with self.assertRaises(SystemExit): self.run_guard()


if __name__ == '__main__':
    unittest.main(verbosity=2)
