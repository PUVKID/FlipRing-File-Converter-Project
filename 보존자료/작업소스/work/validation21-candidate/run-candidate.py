"""활성 명세는 보존하고 후보 명세만 중앙 실행기로 한 번 실측한다."""
from pathlib import Path
from datetime import datetime
import hashlib
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, 'D:/2026/Codex 관련/Codex 모델 라우팅/3차/tools')
from routing_stop import validate_checks, run_check

spec = json.loads((OUT / 'routing-checks.candidate.json').read_text(encoding='utf-8'))
checks, errors = validate_checks(ROOT, spec)
assert not errors, errors
assert spec['total_timeout_seconds'] == 45
assert sum(c['timeout_seconds'] for c in checks) == 45
assert all(c['timeout_seconds'] <= 30 for c in checks)
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
state = json.loads((ROOT / '.codex/routing-state/8497857bac3133cb43214010.json').read_text(encoding='utf-8-sig'))
record = {'started_kst': datetime.now().astimezone().isoformat(), 'session': state['session_id'],
          'task': state['task_id'], 'repair_used': state['repair_used'], 'input_fix_used': state['input_fix_used'],
          'verification_failures': state['verification_failures'], 'argv': sys.argv, 'cwd': str(ROOT),
          'checks': checks, 'validate_errors': errors, 'active_spec_before': sha(ROOT / '.codex/routing-checks.json'),
          'helper_sha256': sha(ROOT / '.codex/release_validation.py'), 'manifest_sha256': sha(ROOT / '.codex/gui_test_manifest.json'),
          'results': []}
# 한글 파일명으로 결과를 기록하며 기존 실패·실측은 덮지 않는다.
target = OUT / '후보실측.json'
assert not target.exists()
target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
start = time.perf_counter()
for check in checks:
    result = run_check(check)
    record['results'].append(result)
    record.update(recorded_kst=datetime.now().astimezone().isoformat(), elapsed_seconds=time.perf_counter() - start)
    record['active_spec_after'] = sha(ROOT / '.codex/routing-checks.json')
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if result['status'] != 'passed':
        sys.exit(1)
record['passed'] = all(r['status'] == 'passed' and r['exit_code'] == 0 for r in record['results'])
record['active_spec_unchanged'] = record['active_spec_before'] == record['active_spec_after']
target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'passed': record['passed'], 'elapsed_seconds': record['elapsed_seconds'],
                  'active_spec_unchanged': record['active_spec_unchanged']}, ensure_ascii=False))
