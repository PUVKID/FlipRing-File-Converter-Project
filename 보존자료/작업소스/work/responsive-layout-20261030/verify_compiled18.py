"""실제 실행 파일의 앱 코드와 납품 소스의 코드 객체를 대조한다."""
import hashlib
import json
import marshal
from pathlib import Path
import sys
from types import CodeType
from PyInstaller.archive.readers import CArchiveReader

ROOT = Path(__file__).resolve().parents[2]
program = Path(sys.argv[1]).resolve()
report_path = Path(sys.argv[2]).resolve()
archive = CArchiveReader(str(program))
modules = archive.open_embedded_archive('PYZ.pyz')


def normalized(code):
    return code.replace(co_filename='<납품소스>', co_consts=tuple(normalized(value) if isinstance(value, CodeType) else value
                                                                 for value in code.co_consts))


items = []
for name in ('app', 'engine', 'flipring_workflow', 'preview_panel', 'pdf_panel', 'pdf_tools',
             'pdf_pages', 'pdf_lock', 'i18n', 'studio_ui', 'ui_motion', 'fixed_viewport'):
    path = ROOT / '소스' / (name + '.py')
    raw = path.read_bytes()
    expected = normalized(compile(raw, str(path), 'exec', dont_inherit=True, optimize=0))
    actual = normalized(marshal.loads(archive.extract('app')) if name == 'app' else modules.extract(name))
    items.append({'module': name, 'source_sha256': hashlib.sha256(raw).hexdigest(),
                  'code_equal': actual == expected})
report = {'exe': str(program.relative_to(ROOT)), 'exe_sha256': hashlib.file_digest(program.open('rb'), 'sha256').hexdigest(),
          'modules': items, 'passed': len(items) == 12 and all(item['code_equal'] for item in items),
          'scope': '파일명만 정규화한 재귀 코드 객체 동등성. 실제 Windows 화면·외부 입력 검증과 별도.'}
assert not report_path.exists(), '이전 대조 원문은 덮어쓰지 않습니다.'
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'modules': len(items), 'passed': report['passed'], 'mismatches': [item['module'] for item in items if not item['code_equal']]}, ensure_ascii=False))
sys.exit(0 if report['passed'] else 1)
