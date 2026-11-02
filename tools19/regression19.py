"""기존 163개 검사의 실제 ID·순서·원본·유한 출력을 기록한다."""
import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys
import time
import unittest
import uuid

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
SOURCE = ROOT / '소스'
sys.path.insert(0, str(TOOLS))
from release_capture import run_check

TOTAL_BUDGET_SECONDS = 60
CHILD_TIMEOUT_SECONDS = 27
SOURCE_FILES = {'gui': 'test_gui.py', 'workbench': 'test_workbench.py',
                'workspace': 'test_pdf_workspace.py', 'pdf': 'test_pdf_tools.py'}


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def hashes(directory):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(directory.glob('*.py'))}


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def expected_ids(group):
    tree = ast.parse((SOURCE / SOURCE_FILES[group]).read_text(encoding='utf-8'))
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    def methods(name):
        node = classes[name]
        names = {item.name for item in node.body if isinstance(item, ast.FunctionDef) and item.name.startswith('test_')}
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id in classes:
                names.update(methods(base.id))
        return sorted(names)
    selected = ['OcrTests', 'PanelTests'] if group == 'pdf' else sorted(classes)
    ids = ['__main__.' + name + '.' + method for name in selected for method in methods(name)]
    assert len(ids) == {'gui': 85, 'workbench': 20, 'workspace': 30, 'pdf': 28}[group]
    assert len(ids) == len(set(ids)), '예상 검사 ID 중복'
    return ids


def child(group, output):
    os.chdir(SOURCE)
    os.environ['QT_QPA_PLATFORM'] = 'offscreen:configfile=offscreen-monitor.json'
    sys.path.insert(0, str(SOURCE))
    # Windows offscreen에서 글꼴은 시험 프로세스에만 등록한다.
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase
    application = None
    if group != 'gui':
        application = QApplication([])
        for filename in ('segoeui.ttf', 'seguisb.ttf', 'malgun.ttf', 'malgunbd.ttf'):
            QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / filename))
    original = unittest.TextTestRunner
    original_default = unittest.runner.TextTestRunner
    actual = []
    expected = json.loads((output / 'expected.json').read_text(encoding='utf-8'))

    class Result(unittest.TextTestResult):
        def startTest(self, test):
            actual.append(test.id())
            super().startTest(test)

    class Runner(original):
        resultclass = Result
        def run(self, suite):
            cases = [test for test in flatten(suite) if test.id() in expected]
            assert [test.id() for test in cases] == expected, '수집한 검사 ID 불일치'
            result = super().run(unittest.TestSuite(cases))
            write(output / 'stats.json', dict(expected=expected, actual=actual, tests=result.testsRun,
                  failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped)))
            return result

    unittest.TextTestRunner = Runner
    unittest.runner.TextTestRunner = Runner
    sys.argv = [SOURCE_FILES[group]] + ([str(output)] if group in ('gui', 'workspace', 'pdf') else [])
    if group == 'pdf':
        sys.argv += ['--ocr', '--gui']
    try:
        runpy.run_path(str(SOURCE / SOURCE_FILES[group]), run_name='__main__')
    finally:
        unittest.TextTestRunner = original
        unittest.runner.TextTestRunner = original_default


def timed_check(check, submitted_at, submitted_monotonic):
    started_at = datetime.now().astimezone().isoformat()
    started = time.monotonic()
    result = run_check(check)
    result['schedule'] = dict(submitted_at=submitted_at, submitted_monotonic=submitted_monotonic,
        started_at=started_at, started_monotonic=started, queue_seconds=round(started-submitted_monotonic, 6),
        finished_at=datetime.now().astimezone().isoformat(), finished_monotonic=time.monotonic())
    return result


def batch():
    started = time.monotonic()
    run = ROOT / 'work' / 'regression19' / uuid.uuid4().hex
    run.mkdir(parents=True)
    checks = []
    source_group = {}
    for group in ('gui', 'workbench', 'workspace', 'pdf'):
        ids = expected_ids(group)
        parts = [ids[index:index+20] for index in range(0, len(ids), 20)] if group == 'gui' else [ids]
        if group == 'workbench':
            parts = [[value for value in ids if '.WorkbenchTests.' in value],
                     [value for value in ids if '.WorkbenchUiTests.' in value]]
        for index, expected in enumerate(parts):
            identity = 'pdf28' if group == 'pdf' else f'{group}-{index}'
            output = run / ('pdf' if group == 'pdf' else identity)
            output.mkdir()
            write(output / 'expected.json', expected)
            checks.append(dict(id=identity, cwd=str(SOURCE), timeout_seconds=CHILD_TIMEOUT_SECONDS,
                argv=[sys.executable, '-B', '-X', 'utf8', str(Path(__file__).resolve()),
                      '--child', group, '--output', str(output)]))
            source_group[identity] = (group, output)
    # 무거운 작업을 먼저 제출한다. 각 suite의 원래 검사 순서는 바꾸지 않는다.
    priority = {'pdf28': 0, 'workbench-0': 1, 'workspace-0': 2, 'workbench-1': 3}
    scheduled = sorted(checks, key=lambda check: priority.get(check['id'], 4))
    before, tools_before = hashes(SOURCE), hashes(TOOLS)
    write(run / 'start.json', dict(started=datetime.now().astimezone().isoformat(), source=before,
        tools=tools_before, checks=checks, submission_order=[check['id'] for check in scheduled],
        total_budget_seconds=TOTAL_BUDGET_SECONDS, concurrency=2))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(timed_check, check, datetime.now().astimezone().isoformat(), time.monotonic())
                   for check in scheduled]
        completed = [future.result() for future in futures]
    by_id = {result['id']: result for result in completed}
    results = [by_id[check['id']] for check in checks]
    after, tools_after = hashes(SOURCE), hashes(TOOLS)
    elapsed = time.monotonic() - started
    good = before == after and tools_before == tools_after and elapsed <= TOTAL_BUDGET_SECONDS
    good &= all(result['status'] == 'passed' and result['output_complete'] for result in results)
    actual_ids = []
    observed_total = 0
    for check in checks:
        write(run / (check['id'] + '.json'), by_id[check['id']])
        group, output = source_group[check['id']]
        stats_path = output / 'stats.json'
        if not stats_path.is_file():
            good = False
            continue
        stats = json.loads(stats_path.read_text(encoding='utf-8'))
        observed_total += stats['tests']
        actual_ids.extend(SOURCE_FILES[group] + '::' + value for value in stats['actual'])
        good &= stats['expected'] == stats['actual'] and stats['tests'] == len(stats['expected'])
        good &= not any(stats[key] for key in ('failures', 'errors', 'skipped'))
    pdf_report = run / 'pdf' / 'PDF-OCR-검증.json'
    if pdf_report.is_file():
        stats = json.loads(pdf_report.read_text(encoding='utf-8'))
        good &= stats['tests'] == stats['passed'] == 28 and not any(stats[key] for key in ('failures', 'errors', 'skipped'))
    else:
        good = False
    good &= observed_total == 163 and len(actual_ids) == len(set(actual_ids)) == 163
    write(run / 'result.json', dict(passed=bool(good), source_before=before, source_after=after,
        tools_before=tools_before, tools_after=tools_after, results=results, expected_total=163,
        observed_total=observed_total, actual_ids=actual_ids, elapsed_seconds=elapsed,
        total_budget_seconds=TOTAL_BUDGET_SECONDS, submission_order=[check['id'] for check in scheduled],
        finished=datetime.now().astimezone().isoformat()))
    print(json.dumps(dict(passed=bool(good), path=str(run), observed_total=observed_total,
        seconds=elapsed, groups=[dict(id=result['id'], status=result['status'], seconds=result['duration_seconds'])
                                for result in results]), ensure_ascii=False))
    return int(not good)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--child', choices=tuple(SOURCE_FILES))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.child:
        child(args.child, args.output)
    else:
        sys.exit(batch())
