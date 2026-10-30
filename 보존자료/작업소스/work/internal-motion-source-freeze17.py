"""수리17의 새 직접 검사와 소유 소스 동결 근거를 기록한다. 독립 영수증이 아니다."""
from pathlib import Path
from datetime import datetime
import ast
import hashlib
import json
import re
import sys

root = Path(__file__).resolve().parents[1]
target = root / 'evidence/내부모션-소스동결17.json'
assert not target.exists(), '이전 동결 근거를 덮어쓰지 않습니다.'


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_run(name, count):
    folder = root / 'work' / name
    record = read_json(folder / '실행기록.json')
    output = (folder / '출력.log').read_bytes().decode('utf-8', errors='strict')
    assert record['exit_code'] == 0
    assert re.search(rf'Ran {count} tests in [0-9.]+s', output)
    assert re.search(r'^OK\r*$', output, re.MULTILINE)
    assert 'skipped=' not in output
    assert not record['truncated']
    return {
        'tests': count, 'passed': count, 'skipped': 0,
        'elapsed_seconds': record['elapsed_seconds'],
        'exit_code': record['exit_code'], 'argv': record['argv'],
        'cwd': record['cwd'], 'evidence': str((folder / '실행기록.json').relative_to(root)),
        'log_sha256': digest(folder / '출력.log'),
    }


gui = check_run('internal-motion-final-gui17', 85)
pdf = check_run('internal-motion-final-pdf17', 28)
related = check_run('internal-motion-message-width-green17', 4)
gui_result = read_json(root / 'work/internal-motion-final-gui17/gui/Mono-Qt검증.json')
pdf_result = read_json(root / 'work/internal-motion-final-pdf17/results/PDF-OCR-검증.json')
assert gui_result['tests'] == gui_result['passed'] == 85
assert pdf_result['tests'] == pdf_result['passed'] == 28
assert pdf_result['ocr_enabled'] and pdf_result['gui_enabled'] and pdf_result['skipped'] == []

python_files = sorted((root / '소스').glob('*.py'))
encoding_records = []
for path in python_files:
    data = path.read_bytes()
    text = data.decode('utf-8-sig', errors='strict')
    assert '\ufffd' not in text, str(path)
    assert b'\r\r\n' not in data, str(path)
    ast.parse(text, filename=str(path))
    encoding_records.append({'path': str(path.relative_to(root)), 'bytes': len(data), 'sha256': digest(path)})

baseline = read_json(root / 'work/internal-motion-baseline/보존목록.json')
backend = {}
for name in ('engine.py', 'pdf_tools.py'):
    path = root / '소스' / name
    expected = next(item['sha256'] for item in baseline if item['name'] == name)
    assert digest(path).lower() == expected.lower()
    backend[name] = {'sha256': digest(path), 'baseline_sha256': expected, 'byte_identical': True}

guidance = Path('C:/Users/PUVKID/.codex/AGENTS.md')
assert digest(guidance).upper() == '5C743C60D698F7EFF13C7751DFA7D846A7A0BD84715771975772C9BA4F5DE954'
owned = ('app.py', 'studio_ui.py', 'pdf_panel.py', 'i18n.py', 'ui_motion.py', 'test_gui.py')
state = read_json(root / '.codex/routing-state/8497857bac3133cb43214010.json')
preview = read_json(root / 'work/internal-motion-preview17/렌더기록.json')
assert preview['platform'] == 'offscreen'
assert len([f for f in preview['files'] if f['name'].endswith('.png')]) == 10
assert len([f for f in preview['files'] if f['name'].endswith('.gif')]) == 3
documents = [root / 'ROUTING-LESSONS.md', root / '시작하기.txt'] + sorted((root / 'docs').rglob('*.md'))
report = {
    'recorded_kst': datetime.now().astimezone().isoformat(),
    'argv': [sys.executable, '-B', '-X', 'utf8'] + sys.argv,
    'cwd': str(root), 'session': state['session_id'], 'task': state['task_id'],
    'mode': state['mode'], 'repair_used': state['repair_used'], 'input_fix_used': state['input_fix_used'],
    'stop_failures': state['stop_failures'], 'verification_failures': state['verification_failures'],
    'role_assignment': {
        'role': 'deep', 'model': 'gpt-6.1-sol', 'reasoning_effort': 'xhigh',
        'scope': '부모 배정값을 기록하며 서버 내부 런타임 신원 보증은 아닙니다.',
        'before': 'deep / gpt-6.1-sol / xhigh', 'after': 'deep / gpt-6.1-sol / xhigh',
        'trigger': 'NoIcon 메시지의 빈 아이콘 열 때문에 본문 폭이 좁아지는 실제 진단과 test76 예정 RED',
        'method': '본문 QLabel 한 항목만 원래 행 전체 열로 배치하고 버튼·반환·아이콘 있는 메시지 배치를 보존',
    },
    'gui': gui, 'pdf_ocr': pdf, 'related': related,
    'strict_utf8_ast_python_files': len(python_files),
    'utf8_ast_scope': '엄격 UTF-8/선택 BOM·대체문자·중복 CR 개행·AST. 별도 타입 검사나 의미상 완전 무오류 증명은 아닙니다.',
    'python_files': encoding_records, 'backend_unchanged': backend,
    'owned_files': {name: {'bytes': (root / '소스' / name).stat().st_size, 'sha256': digest(root / '소스' / name)} for name in owned},
    'global_guidance': {'path': str(guidance), 'bytes': guidance.stat().st_size, 'sha256': digest(guidance), 'read_scope': '전문'},
    'project_documents_read': [{'path': str(p.relative_to(root)), 'bytes': p.stat().st_size, 'sha256': digest(p)} for p in documents],
    'surface_matrix': 'evidence/내부모션-적용목록.md', 'surface_count': 40,
    'preview': {'evidence': 'work/internal-motion-preview17/렌더기록.json', 'platform': 'offscreen', 'png_count': 10, 'gif_count': 3,
                'viewed_pngs': ['02-file-picker.png', '04-message.png', '06-ocr.png'], 'scope': preview['scope']},
    'source_frozen': True, 'freeze_scope': list(owned), 'new_product_dependencies': False,
    'pending_parent_steps': ['새 실행 파일·설치 파일 빌드', 'Windows 설치본 실제 화면·탐색기 Shift 검증', '별도 verifier의 독립 검증·최종 Stop'],
    'scope_limits': [
        'Qt 오프스크린 직접 렌더와 모형 이벤트는 Windows 설치본·물리 Shift/OLE를 대신하지 않습니다.',
        '모달 메시지 제목/본문은 생성 시 문자열입니다. 강제 프로그램 언어 변경에 임의 역번역하지 않으며 표준 버튼·새 창은 언어 설정을 따릅니다.',
        'Windows 탐색기·시스템 창 프레임·권한 화면·OS 알림 풍선·다른 앱은 변경 범위 밖입니다.',
        '수명·상태·중간 렌더 회귀를 확인했지만 모든 하드웨어의 일정한 프레임 속도는 보장하지 않습니다.',
        '검사 실행 시간은 이번 관측값이며 다음 실행 시간을 보장하지 않습니다.',
    ],
    'cost': 'API 환산 요율·서버 실제 사용량·구독 청구는 미확인입니다.',
    'independent_verification_receipt': False,
}
target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False))
