"""신규 실제 파일·Qt·OCR 프로세스 86개 검사를 유한 수집한다."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
from release_capture import run_check
from run_new_suite19 import EXPECTED_COUNTS

CHILD_TIMEOUT_SECONDS = 44
TOTAL_BUDGET_SECONDS = 50


def hashes(directory):
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(directory.glob('*.py'))}


def main():
    started = time.monotonic()
    folder = ROOT / 'work' / 'new-suites19' / uuid.uuid4().hex
    folder.mkdir(parents=True)
    before, tools_before = hashes(ROOT / '소스'), hashes(TOOLS)
    # 긴 UI·코어를 먼저 시작하고 나머지를 같은 두 실행 슬롯에 넣는다.
    groups = ('test_workspace_ui', 'test_workspace_core', 'test_inspection_tools', 'test_ocr_process')
    checks = [dict(id=name, cwd=str(ROOT / '소스'), timeout_seconds=CHILD_TIMEOUT_SECONDS,
        argv=[sys.executable, '-B', '-X', 'utf8', str(TOOLS / 'run_new_suite19.py'),
              name, str(folder / (name + '-stats.json'))]) for name in groups]
    (folder / 'start.json').write_text(json.dumps(dict(source=before, tools=tools_before, checks=checks,
        expected_counts=EXPECTED_COUNTS, total_budget_seconds=TOTAL_BUDGET_SECONDS,
        concurrency=2, started=datetime.now().astimezone().isoformat()), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run_check, checks))
    for result in results:
        (folder / (result['id'] + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    after, tools_after = hashes(ROOT / '소스'), hashes(TOOLS)
    elapsed = time.monotonic() - started
    passed = before == after and tools_before == tools_after and elapsed <= TOTAL_BUDGET_SECONDS
    passed &= all(result['status'] == 'passed' and result['output_complete'] for result in results)
    observed_total = 0
    actual_ids = []
    for check in checks:
        stats_path = folder / (check['id'] + '-stats.json')
        if not stats_path.is_file():
            passed = False
        else:
            stats = json.loads(stats_path.read_text(encoding='utf-8'))
            observed_total += stats['tests']
            actual_ids.extend(stats['actual'])
            passed &= stats['passed'] and stats['tests'] == EXPECTED_COUNTS[check['id']]
            passed &= stats['actual'] == stats['expected'] and not any(stats[key] for key in ('failures', 'errors', 'skipped'))
    passed &= observed_total == sum(EXPECTED_COUNTS.values()) == len(actual_ids) == len(set(actual_ids)) == 86
    report = dict(passed=bool(passed), source_before=before, source_after=after, tools_before=tools_before,
        tools_after=tools_after, results=results, expected_counts=EXPECTED_COUNTS, expected_total=86,
        observed_total=observed_total, actual_ids=actual_ids, elapsed_seconds=elapsed,
        total_budget_seconds=TOTAL_BUDGET_SECONDS, observed_at=datetime.now().astimezone().isoformat())
    (folder / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(passed=bool(passed), path=str(folder), observed_total=observed_total, seconds=elapsed,
        groups=[dict(id=result['id'], status=result['status'], seconds=result['duration_seconds'])
                for result in results]), ensure_ascii=False))
    return int(not passed)


if __name__ == '__main__':
    sys.exit(main())
