"""문서 확장 검사의 실제 ID·건너뜀·수행 수를 기록합니다."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "소스"
COUNTS = {"test_document_formats": 14, "test_document_xlsb": 12, "test_documents_ui110": 4,
          "test_documents_integration": 7, "test_document_external": 8, "test_document_security": 2,
          "test_document_shutdown": 4}


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def main():
    module, output = sys.argv[1], Path(sys.argv[2])
    if module not in COUNTS:
        raise SystemExit("등록되지 않은 문서 검사입니다.")
    os.chdir(SOURCE)
    os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=offscreen-monitor.json"
    temp = ROOT.parent / "work/t110" / output.parent.name[:10] / str(list(COUNTS).index(module))
    temp.mkdir(parents=True, exist_ok=False)
    os.environ["TEMP"] = os.environ["TMP"] = str(temp)
    tempfile.tempdir = str(temp)
    sys.path.insert(0, str(SOURCE))
    suite = unittest.defaultTestLoader.loadTestsFromName(module)
    expected = [test.id() for test in flatten(suite)]
    actual = []

    class Result(unittest.TextTestResult):
        def startTest(self, test):
            actual.append(test.id())
            super().startTest(test)

    result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(suite)
    data = dict(expected=expected, actual=actual, tests=result.testsRun, expected_count=COUNTS[module],
                failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped))
    data["passed"] = (len(expected) == COUNTS[module] == len(set(expected)) and actual == expected
                      and result.testsRun == COUNTS[module] and result.wasSuccessful() and not result.skipped)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return int(not data["passed"])


if __name__ == "__main__":
    sys.exit(main())
