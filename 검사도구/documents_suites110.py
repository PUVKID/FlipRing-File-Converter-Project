"""문서 확장의 정책·Qt·실제 Office 검사를 순차 실행하고 원문을 결합합니다."""
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
from run_documents_suite110 import COUNTS

TIMEOUTS = {"test_document_formats": 30, "test_document_xlsb": 30, "test_documents_ui110": 60,
            "test_documents_integration": 180, "test_document_external": 210, "test_document_security": 90,
            "test_document_shutdown": 30}
TOTAL_BUDGET_SECONDS = 600


def hashes(directory):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(directory.glob("*.py"))}


def main():
    started = time.monotonic()
    folder = ROOT / "work/documents-suites110" / uuid.uuid4().hex
    folder.mkdir(parents=True)
    before, tools_before = hashes(ROOT / "소스"), hashes(TOOLS)
    checks = [dict(id=name, cwd=str(ROOT / "소스"), timeout_seconds=TIMEOUTS[name],
                   argv=[sys.executable, "-B", "-X", "utf8", str(TOOLS / "run_documents_suite110.py"),
                         name, str(folder / (name + "-stats.json"))]) for name in COUNTS]
    report = dict(started=datetime.now().astimezone().isoformat(), checks=checks, expected_counts=COUNTS,
                  source_before=before, tools_before=tools_before, total_budget_seconds=TOTAL_BUDGET_SECONDS)
    (folder / "start.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    results = []
    for check in checks:
        result = run_check(check)
        results.append(result)
        (folder / (check["id"]+".json")).write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    after, tools_after = hashes(ROOT / "소스"), hashes(TOOLS)
    elapsed = time.monotonic() - started
    passed = before == after and tools_before == tools_after and elapsed <= TOTAL_BUDGET_SECONDS
    passed &= all(item["status"] == "passed" and item["output_complete"] for item in results)
    actual, observed = [], 0
    for check in checks:
        path = folder / (check["id"]+"-stats.json")
        if not path.is_file():
            passed = False
            continue
        stats = json.loads(path.read_text(encoding="utf-8"))
        observed += stats["tests"]
        actual.extend(stats["actual"])
        passed &= stats["passed"] and stats["tests"] == COUNTS[check["id"]]
        passed &= stats["expected"] == stats["actual"] and not any(stats[k] for k in ("failures", "errors", "skipped"))
    passed &= observed == len(actual) == len(set(actual)) == sum(COUNTS.values())
    report.update(passed=bool(passed), source_after=after, tools_after=tools_after, results=results,
                  observed_total=observed, actual_ids=actual, elapsed_seconds=elapsed,
                  finished=datetime.now().astimezone().isoformat())
    (folder / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(dict(passed=bool(passed), path=str(folder), observed_total=observed, seconds=elapsed), ensure_ascii=False))
    return int(not passed)


if __name__ == "__main__":
    sys.exit(main())
