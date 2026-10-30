"""기존 검사 원문을 보존하며 GUI85와 독립 배포·PDF 검사의 시간 배정을 준비한다."""
from pathlib import Path
from datetime import datetime
import copy
import hashlib
import json
import sys

root = Path(__file__).resolve().parents[1]
folder = root / 'work' / 'release-check-budget-1.6'
folder.mkdir(exist_ok=True)
tool_folder = Path('D:/2026/Codex 관련/Codex 모델 라우팅/3차/tools')
sys.path.insert(0, str(tool_folder))
from routing_stop import validate_checks
original_bytes = (root / '.codex/routing-checks.json').read_bytes()
original = json.loads(original_bytes.decode('utf-8-sig'))
assert len(original['checks']) == 3
hash_check, gui_check, pdf_check = copy.deepcopy(original['checks'])
inner = [hash_check, pdf_check]
for check in inner:
    check['cwd'] = str(root)
inner[1]['timeout_seconds'] = 14.7
controller = '\n'.join([
    'from concurrent.futures import ThreadPoolExecutor',
    'from pathlib import Path',
    'import json,sys',
    'sys.path.insert(0,' + repr(str(tool_folder)) + ')',
    'from routing_stop import run_check',
    'checks=json.loads(' + repr(json.dumps(inner, ensure_ascii=False)) + ')',
    'with ThreadPoolExecutor(max_workers=2) as pool:',
    '    results=list(pool.map(run_check,checks))',
    'target=Path(' + repr(str(folder / '동시검사-실행결과.json')) + ')',
    'target.write_bytes((json.dumps(results,ensure_ascii=False,indent=2)+"\\n").encode("utf-8"))',
    'print(json.dumps([{k:r.get(k) for k in ("id","status","exit_code","duration_seconds","output_bytes","captured_bytes","output_truncated","error")} for r in results],ensure_ascii=False))',
    'sys.exit(0 if len(results)==2 and all(r["status"]=="passed" for r in results) else 1)',
])
new = {'schema_version': 1, 'total_timeout_seconds': 45, 'checks': [gui_check, {
    'id': '배포해시-PDF-OCR-동시', 'cwd': '.', 'timeout_seconds': 15,
    'argv': [gui_check['argv'][0], '-B', '-X', 'utf8', '-c', controller],
}]}
new['checks'][0]['timeout_seconds'] = 30
assert new['checks'][0]['argv'] == original['checks'][1]['argv']
assert inner[0]['argv'] == original['checks'][0]['argv']
assert inner[1]['argv'] == original['checks'][2]['argv']
compile(controller, '<배포-PDF-동시검사>', 'exec')
checks, errors = validate_checks(root, new)
assert len(checks) == 2 and not errors, errors
backup = folder / 'routing-checks-before.json'
if not backup.exists():
    backup.write_bytes(original_bytes)
candidate = folder / 'routing-checks-candidate.json'
candidate.write_bytes((json.dumps(new,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
report = {'time_kst':datetime.now().astimezone().isoformat(), 'before_sha256':hashlib.sha256(original_bytes).hexdigest(), 'candidate_sha256':hashlib.sha256(candidate.read_bytes()).hexdigest(), 'existing_argv_unchanged':True, 'criteria_skips_assertions_changed':False, 'individual_limits':[30,15], 'total_limit':45, 'central_module_modified':False, 'validation_errors':errors, 'executed':False, 'scope':'활성 명세 교체 전 준비. 기존 배포 증거는 아직1.5이므로 실제 전체 실행은 새 빌드·설치 근거 갱신 후.'}
(folder / '준비검증.json').write_bytes((json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
print(json.dumps(report,ensure_ascii=False))