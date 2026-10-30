"""승인된 새 검사 본문과 최종 소스를 릴리스 검사 명세에 결합한다."""
import ast
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / '소스'
parser = argparse.ArgumentParser()
parser.add_argument('--revision', type=int, default=1)
args = parser.parse_args()
assert args.revision >= 1


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


manifest_path = ROOT / '.codex/gui_test_manifest.json'
manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
assert manifest['pdf_source_sha256'] == '58032cfc269c038d9190c5e9cca9e9a2fd0436162c587b063147ada9f8dd8df7'
assert sha(SOURCE / 'test_pdf_tools.py') == manifest['pdf_source_sha256']
gui_sha = sha(SOURCE / 'test_gui.py')
manifest['gui_source_sha256'] = gui_sha
manifest['prior_gui_source_sha256'] = 'f27752075c05151ea54583b0b7aaf163fd4c28b64ce04ffbf17b44d66b196f9a'
manifest['approved_structure_change'] = '수리5: 설정 전용 탭6/index5, 번역 fixture와 독립 장식 검사. 수리15: 빈 상태를 명시한 드래그 중 고정 영역과 수락 후 카드 축소 분리 검사. 기존 기능 assert와 불변 원문 보존.'
source_files = sorted(SOURCE.glob('*.py'))
for path in source_files:
    text = path.read_text(encoding='utf-8')
    assert '\ufffd' not in text, str(path)
    ast.parse(text)
source_files += [SOURCE / name for name in ('requirements-lock.txt', '빌드방법.md', '사용안내.txt', '1.7-새기능안내.md')]
manifest['source_sha256'] = {path.name: sha(path) for path in source_files}
manifest['workflow_suites'] = []
expected_counts = {'workbench': 20, 'workspace': 30}
for name, filename in [('workbench', 'test_workbench.py'), ('workspace', 'test_pdf_workspace.py')]:
    path = SOURCE / filename
    tree = ast.parse(path.read_text(encoding='utf-8'))
    ids = ['__main__.' + node.name + '.' + method
           for node in sorted((node for node in tree.body if isinstance(node, ast.ClassDef)), key=lambda node: node.name)
           for method in sorted(item.name for item in node.body if isinstance(item, ast.FunctionDef) and item.name.startswith('test_'))]
    assert len(ids) == expected_counts[name], (name, len(ids), expected_counts[name])
    manifest['workflow_suites'].append({'id': name, 'source': path.relative_to(ROOT).as_posix(),
                                        'sha256': sha(path), 'count': len(ids), 'test_ids': ids})
freeze = {'time_kst': datetime.now(timezone(timedelta(hours=9))).isoformat(), 'release': '1.7.0',
          'source_sha256': manifest['source_sha256'], 'workflow_suites': manifest['workflow_suites'],
          'prior_gui_sha256': manifest['prior_gui_source_sha256'], 'gui_sha256': gui_sha,
          'pdf_source_sha256': manifest['pdf_source_sha256'],
          'scope': '최종 릴리스 검사 명세 준비. 독립 통과와 실제 설치·화면 확인은 별도.'}
freeze_path = ROOT / ('evidence/1.7-소스동결' + ('' if args.revision == 1 else str(args.revision)) + '.json')
assert not freeze_path.exists(), '기존 동결 원본은 덮어쓰지 않습니다.'
write(freeze_path, freeze)
manifest['baseline'] = freeze_path.relative_to(ROOT).as_posix()
manifest['baseline_sha256'] = sha(freeze_path)
write(manifest_path, manifest)
helper = ROOT / '.codex/release_validation.py'
text = helper.read_text(encoding='utf-8')
text, count = re.subn(r"^GUI_SHA = '[0-9a-f]{64}'$", "GUI_SHA = '" + gui_sha + "'", text, flags=re.MULTILINE)
assert count == 1
helper.write_text(text, encoding='utf-8')
print(json.dumps({'gui': 85, 'pdf': 28, 'workflow': expected_counts, 'source_files': len(source_files),
                  'freeze': str(freeze_path)}, ensure_ascii=False))
