"""신규 86개 검사의 실제 ID·실행 수·건너뜀을 기록한다."""
import json
from pathlib import Path
import sys
import unittest

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(ROOT / '소스'))
EXPECTED_COUNTS = {'test_workspace_core': 46, 'test_inspection_tools': 13,
                   'test_workspace_ui': 20, 'test_ocr_process': 7}


def flatten(items):
    for item in items:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def main():
    module = sys.argv[1]
    target = Path(sys.argv[2])
    if module not in EXPECTED_COUNTS:
        raise SystemExit('지원하지 않는 검사 그룹입니다.')
    suite = unittest.defaultTestLoader.loadTestsFromName(module)
    expected = [test.id() for test in flatten(suite)]
    actual = []

    class Result(unittest.TextTestResult):
        def startTest(self, test):
            actual.append(test.id())
            super().startTest(test)

    result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(suite)
    data = dict(expected=expected, actual=actual, tests=result.testsRun, expected_count=EXPECTED_COUNTS[module],
                failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped))
    data['passed'] = (len(expected) == EXPECTED_COUNTS[module] and len(expected) == len(set(expected))
                      and actual == expected and result.wasSuccessful() and not result.skipped)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return int(not data['passed'])


if __name__ == '__main__':
    sys.exit(main())
