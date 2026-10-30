"""원본 검사 본문을 바꾸지 않고 ID·해시·새 출력에 결합해 격리 실행한다."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys
import time
import traceback
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / '.codex/gui_test_manifest.json'
CENTRAL = Path('D:/2026/Codex 관련/Codex 모델 라우팅/3차/tools')
GUI_SHA = '13d3f04609c3cec929a70346068b5b334bf73ddd488e29cac281a7b3998c5018'
PDF_SHA = '58032cfc269c038d9190c5e9cca9e9a2fd0436162c587b063147ada9f8dd8df7'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def stamp():
    return datetime.now().astimezone().isoformat()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write_json(path, data):
    path.write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def validate_ids(expected, actual):
    require(isinstance(expected, list) and isinstance(actual, list), '검사 ID는 목록이어야 합니다.')
    require(all(isinstance(x, str) for x in expected + actual), '검사 ID 형식 오류')
    require(len(expected) == len(set(expected)), '기대 ID 중복')
    require(Counter(actual) == Counter(expected), '실제 검사 ID의 중복·누락·예상 밖 항목')
    require(actual == expected, '원래 검사 순서 변경')


def validate_counts(stats, expected):
    wanted = {'testsRun': expected, 'failures': 0, 'errors': 0, 'skipped': 0}
    for key, value in wanted.items():
        require(type(stats.get(key)) is int and stats[key] == value, '검사 통계 불일치: ' + key)


def validate_pdf(report):
    require(type(report.get('tests')) is int and report['tests'] == 28, 'PDF 검사 수 불일치')
    require(type(report.get('passed')) is int and report['passed'] == 28, 'PDF 통과 수 불일치')
    require(report.get('ocr_enabled') is True and report.get('gui_enabled') is True, '실제 OCR/GUI 옵션 누락')
    for key in ('skipped', 'failures', 'errors'):
        require(report.get(key) == [], 'PDF 건너뜀·오류·실패: ' + key)


def source_hashes(contract):
    return {name: sha(ROOT / '소스' / name) for name in contract['source_sha256']}


def load_contract():
    contract = read_json(MANIFEST)
    require(contract.get('schema_version') == 1, 'manifest 버전 오류')
    require(contract['gui_source_sha256'] == GUI_SHA and contract['pdf_source_sha256'] == PDF_SHA, '고정 원본 SHA 변경')
    require(sha(ROOT / contract['gui_source']) == GUI_SHA, 'GUI 원본 변경')
    require(sha(ROOT / contract['pdf_source']) == PDF_SHA, 'PDF 원본 변경')
    require(source_hashes(contract) == contract['source_sha256'], '동결 제품 소스 변경')
    source = (ROOT / contract['gui_source']).read_text(encoding='utf-8')
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == 'GuiTests')
    names = sorted(n.name for n in node.body if isinstance(n, ast.FunctionDef) and n.name.startswith('test_'))
    require(len(names) == 85, 'GUI85개 원본 요구 변경')
    validate_ids(['__main__.GuiTests.' + name for name in names], contract['test_ids'])
    validate_ids(contract['test_ids'], [name for group in contract['shards'] for name in group['test_ids']])
    require([len(s['test_ids']) for s in contract['shards']] == [23, 1, 25, 20, 16], '격리 그룹 구성 변경')
    require(contract['child_timeout_seconds'] == 27, '자식 제한 시간 변경')
    pdf_argv = contract['pdf_argv_template']
    require(pdf_argv[:5] == [str(ROOT / 'work/venv/Scripts/python.exe'), '-B', '-X', 'utf8', '-c'], 'PDF 실행 인자 변경')
    pdf_tree = ast.parse(pdf_argv[-1])
    assignment = next(n for n in pdf_tree.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                              and t.value.id == 'sys' and t.attr == 'argv' for t in n.targets))
    require(ast.literal_eval(assignment.value) == ['소스/test_pdf_tools.py', 'work/pdf-ocr-check', '--ocr', '--gui'], 'PDF 원문 옵션 변경')
    command_hash = hashlib.sha256(json.dumps(pdf_argv, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()
    require(command_hash == contract['pdf_argv_origin_sha256'], 'PDF 원문 명령 해시 불일치')
    suites = contract['workflow_suites']
    require([group['id'] for group in suites] == ['workbench', 'workspace'], '새 작업 검사 그룹 누락')
    for group in suites:
        path = ROOT / group['source']
        require(sha(path) == group['sha256'], '새 작업 검사 소스 변경')
        tree = ast.parse(path.read_text(encoding='utf-8'))
        ids = ['__main__.' + node.name + '.' + name
               for node in sorted((node for node in tree.body if isinstance(node, ast.ClassDef)), key=lambda node: node.name)
               for name in sorted(item.name for item in node.body if isinstance(item, ast.FunctionDef) and item.name.startswith('test_'))]
        validate_ids(group['test_ids'], ids)
        require(type(group['count']) is int and len(ids) == group['count'] and group['count'] > 0, '새 작업 검사 수 불일치')
    return contract


def state_context():
    state = read_json(ROOT / '.codex/routing-state/8497857bac3133cb43214010.json')
    return {key: state[key] for key in ('session_id', 'task_id', 'repair_used', 'input_fix_used', 'verification_failures')}


def read_events(path):
    lines = path.read_text(encoding='utf-8').split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    require(all(lines), 'ID 기록의 중간 빈 행')
    return [json.loads(line) for line in lines]


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def run_gui(shard_id, run_id):
    contract = load_contract()
    group = next(s for s in contract['shards'] if s['id'] == shard_id)
    require(uuid.UUID(run_id).hex == run_id, '실행 UUID 오류')
    output = ROOT / 'work/release-validation' / run_id / shard_id
    output.mkdir(exist_ok=False)
    expected = group['test_ids']
    before = source_hashes(contract)
    data = {'run_id': run_id, 'shard_id': shard_id, 'started_kst': stamp(), 'source_before': before}
    write_json(output / '실행시작.json', {**state_context(), **data, 'argv': sys.argv, 'cwd': str(ROOT)})
    events = (output / 'executed-ids.jsonl').open('w', encoding='utf-8', newline='\n', buffering=1)
    actual, ended = [], []

    class RecordingResult(unittest.TextTestResult):
        def startTest(self, test):
            actual.append(test.id())
            events.write(json.dumps({'event': 'start', 'id': test.id(), 'run_id': run_id}) + '\n')
            super().startTest(test)

        def stopTest(self, test):
            ended.append(test.id())
            events.write(json.dumps({'event': 'end', 'id': test.id(), 'run_id': run_id}) + '\n')
            super().stopTest(test)

    original_runner = unittest.TextTestRunner

    class ShardRunner(original_runner):
        resultclass = RecordingResult

        def run(self, suite):
            cases = list(flatten(suite))
            validate_ids(contract['test_ids'], [case.id() for case in cases])
            chosen = [case for case in cases if case.id() in set(expected)]
            validate_ids(expected, [case.id() for case in chosen])
            result = super().run(unittest.TestSuite(chosen))
            data['stats'] = {'testsRun': result.testsRun, 'failures': len(result.failures),
                             'errors': len(result.errors), 'skipped': len(result.skipped)}
            return result

    unittest.TextTestRunner = ShardRunner
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    sys.path.insert(0, str(ROOT / '소스'))
    sys.argv = [contract['gui_source'], str(output)]
    code = 0
    try:
        # 원래 main의 fixture·본문·보고서·반환 코드를 그대로 사용한다.
        runpy.run_path(contract['gui_source'], run_name='__main__')
    except SystemExit as exc:
        code = exc.code or 0
    finally:
        unittest.TextTestRunner = original_runner
        events.close()
        data.update(finished_kst=stamp(), actual_ids=actual, ended_ids=ended,
                    source_after=source_hashes(contract), original_exit_code=code)
        write_json(output / 'gui-shard.json', data)
    require(code == 0, '원래 GUI 검사 실패')
    validate_ids(expected, actual)
    validate_ids(expected, ended)
    validate_counts(data.get('stats', {}), len(expected))
    require(before == data['source_after'], '실행 중 소스 변경')
    original = read_json(output / 'Mono-Qt검증.json')
    require(original['tests'] == original['passed'] == len(expected) and original['original_preserved'] is True, '원래 GUI 보고서 불일치')
    require(original['failures'] == original['errors'] == [], '원래 GUI 오류 보고')
    return 0


def run_suite(suite_id, run_id):
    """새 검사도 본문을 그대로 실행하고 모든 시작·종료 ID와 결과를 결합한다."""
    contract = load_contract()
    group = next(group for group in contract['workflow_suites'] if group['id'] == suite_id)
    require(uuid.UUID(run_id).hex == run_id, '실행 UUID 오류')
    output = ROOT / 'work/release-validation' / run_id / suite_id
    output.mkdir(exist_ok=False)
    before = source_hashes(contract)
    actual, ended = [], []
    record = {**state_context(), 'run_id': run_id, 'suite_id': suite_id,
              'started_kst': stamp(), 'source_before': before, 'argv': sys.argv, 'cwd': str(ROOT)}
    write_json(output / '실행시작.json', record)
    events = (output / 'executed-ids.jsonl').open('w', encoding='utf-8', newline='\n', buffering=1)

    class RecordingResult(unittest.TextTestResult):
        def startTest(self, test):
            actual.append(test.id())
            events.write(json.dumps({'event': 'start', 'id': test.id(), 'run_id': run_id}) + '\n')
            super().startTest(test)

        def stopTest(self, test):
            ended.append(test.id())
            events.write(json.dumps({'event': 'end', 'id': test.id(), 'run_id': run_id}) + '\n')
            super().stopTest(test)

    original_runner = unittest.TextTestRunner
    original_default_runner = unittest.runner.TextTestRunner

    class SuiteRunner(original_runner):
        resultclass = RecordingResult

        def run(self, suite):
            validate_ids(group['test_ids'], [test.id() for test in flatten(suite)])
            result = super().run(suite)
            record['stats'] = {'testsRun': result.testsRun, 'failures': len(result.failures),
                               'errors': len(result.errors), 'skipped': len(result.skipped)}
            return result

    unittest.TextTestRunner = SuiteRunner
    unittest.runner.TextTestRunner = SuiteRunner
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    sys.path.insert(0, str(ROOT / '소스'))
    sys.argv = [group['source']] + ([str(output)] if suite_id == 'workspace' else [])
    code = 0
    try:
        runpy.run_path(group['source'], run_name='__main__')
    except SystemExit as exc:
        code = exc.code or 0
    except BaseException:
        code = 1
        record['error'] = traceback.format_exc()
    finally:
        events.close()
        unittest.TextTestRunner = original_runner
        unittest.runner.TextTestRunner = original_default_runner
        record.update(finished_kst=stamp(), source_after=source_hashes(contract),
                      actual_ids=actual, ended_ids=ended, exit_code=code)
        write_json(output / 'suite.json', record)
    require(code == 0, '새 작업 검사 실패')
    validate_ids(group['test_ids'], actual)
    validate_ids(group['test_ids'], ended)
    validate_counts(record.get('stats', {}), group['count'])
    require(before == record['source_after'], '새 작업 검사 중 소스 변경')
    return 0


def run_parallel():
    contract = load_contract()
    before = source_hashes(contract)
    validation_before = {p.name: sha(p) for p in (Path(__file__).resolve(), MANIFEST)}
    run_id = uuid.uuid4().hex
    output = ROOT / 'work/release-validation' / run_id
    output.mkdir(parents=True, exist_ok=False)
    checks = []
    for group in contract['shards']:
        checks.append({'id': group['id'], 'cwd': str(ROOT), 'timeout_seconds': contract['child_timeout_seconds'],
                       'argv': [sys.executable, '-B', '-X', 'utf8', str(Path(__file__).resolve()), 'gui',
                                '--shard', group['id'], '--run-id', run_id]})
    pdf_output = output / 'pdf'
    pdf_argv = list(contract['pdf_argv_template'])
    require(pdf_argv[-1].count('"work/pdf-ocr-check"') == 1, 'PDF 원문 출력 인자 경계 오류')
    pdf_argv[-1] = pdf_argv[-1].replace('"work/pdf-ocr-check"', json.dumps(pdf_output.relative_to(ROOT).as_posix()), 1)
    checks.append({'id': 'PDF-OCR-전체28', 'cwd': str(ROOT), 'timeout_seconds': contract['child_timeout_seconds'], 'argv': pdf_argv})
    for group in contract['workflow_suites']:
        checks.append({'id': group['id'], 'cwd': str(ROOT), 'timeout_seconds': contract['child_timeout_seconds'],
                       'argv': [sys.executable, '-B', '-X', 'utf8', str(Path(__file__).resolve()), 'suite',
                                '--shard', group['id'], '--run-id', run_id]})
    record = {**state_context(), 'run_id': run_id, 'started_kst': stamp(), 'cwd': str(ROOT),
              'argv': sys.argv, 'checks': checks, 'source_before': before, 'validation_before': validation_before}
    write_json(output / '실행기록.json', record)
    print(json.dumps({'run_id': run_id, 'output': output.relative_to(ROOT).as_posix(), 'started_kst': record['started_kst']}), flush=True)
    sys.path.insert(0, str(CENTRAL))
    from routing_stop import run_check
    started = time.perf_counter()
    results = {}
    with ThreadPoolExecutor(max_workers=len(checks)) as pool:
        futures = {pool.submit(run_check, check): check['id'] for check in checks}
        for future in as_completed(futures):
            key = futures[future]
            results[key] = future.result()
            # 실패도 완료 즉시 원문과 누적 상태를 남겨 이후 통과로 덮지 않는다.
            write_json(output / (key + '-실행결과.json'), {**state_context(), 'recorded_kst': stamp(), **results[key]})
    record.update(finished_kst=stamp(), elapsed_seconds=time.perf_counter() - started,
                  results=[results[check['id']] for check in checks], source_after=source_hashes(contract),
                  validation_after={p.name: sha(p) for p in (Path(__file__).resolve(), MANIFEST)})
    write_json(output / '실행기록.json', record)
    try:
        require(all(result['status'] == 'passed' and result['exit_code'] == 0 for result in results.values()), '병렬 자식 검사 실패·시간초과')
        total, all_actual = 0, []
        for group in contract['shards']:
            folder = output / group['id']
            data = read_json(folder / 'gui-shard.json')
            require(data['run_id'] == run_id and data['shard_id'] == group['id'], '다른 실행의 GUI 보고서')
            validate_counts(data['stats'], len(group['test_ids']))
            validate_ids(group['test_ids'], data['actual_ids'])
            validate_ids(group['test_ids'], data['ended_ids'])
            events = read_events(folder / 'executed-ids.jsonl')
            require(all(event['run_id'] == run_id and event['event'] in ('start', 'end') for event in events), 'ID 기록 출처 오류')
            validate_ids(group['test_ids'], [e['id'] for e in events if e['event'] == 'start'])
            validate_ids(group['test_ids'], [e['id'] for e in events if e['event'] == 'end'])
            require(data['source_before'] == data['source_after'] == before, '자식 소스 해시 불일치')
            original = read_json(folder / 'Mono-Qt검증.json')
            require(original['tests'] == original['passed'] == len(group['test_ids']) and original['original_preserved'] is True, 'GUI 원본·보고서 불일치')
            total += data['stats']['testsRun']
            all_actual.extend(data['actual_ids'])
        validate_ids(contract['test_ids'], all_actual)
        require(total == 85, '전체 GUI 실행 수 불일치')
        validate_pdf(read_json(pdf_output / 'PDF-OCR-검증.json'))
        suite_counts = {}
        for group in contract['workflow_suites']:
            folder = output / group['id']
            data = read_json(folder / 'suite.json')
            require(data['run_id'] == run_id and data['suite_id'] == group['id'], '새 작업 검사 출처 오류')
            validate_counts(data['stats'], group['count'])
            validate_ids(group['test_ids'], data['actual_ids'])
            validate_ids(group['test_ids'], data['ended_ids'])
            events = read_events(folder / 'executed-ids.jsonl')
            require(all(event['run_id'] == run_id and event['event'] in ('start', 'end') for event in events), '새 작업 ID 기록 출처 오류')
            validate_ids(group['test_ids'], [event['id'] for event in events if event['event'] == 'start'])
            validate_ids(group['test_ids'], [event['id'] for event in events if event['event'] == 'end'])
            require(data['source_before'] == data['source_after'] == before and data['exit_code'] == 0, '새 작업 검사 소스·종료 오류')
            suite_counts[group['id']] = data['stats']['testsRun']
        require(record['source_before'] == record['source_after'] == contract['source_sha256'], '전체 실행 중 소스 변경')
        require(record['validation_before'] == record['validation_after'], '실행기·manifest 변경')
        record.update(passed=True, gui_tests=total, pdf_tests=28, workflow_tests=suite_counts,
                      skipped=0, duplicate_ids=0, missing_ids=0, actual_ids=all_actual)
    except (ValueError, KeyError, OSError) as exc:
        record.update(passed=False, validation_error=str(exc))
    write_json(output / '실행기록.json', record)
    print(json.dumps({'run_id': run_id, 'passed': record['passed'], 'gui_tests': record.get('gui_tests'),
                      'pdf_tests': record.get('pdf_tests'), 'elapsed_seconds': record['elapsed_seconds'],
                      'children': [{k: result.get(k) for k in ('id', 'status', 'duration_seconds')} for result in record['results']],
                      'error': record.get('validation_error')}, ensure_ascii=False), flush=True)
    return 0 if record['passed'] else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('static', 'parallel', 'gui', 'suite'))
    parser.add_argument('--shard')
    parser.add_argument('--run-id')
    args = parser.parse_args()
    if args.mode == 'static':
        contract = load_contract()
        print(json.dumps({'source_unchanged': True, 'test_ids': len(contract['test_ids']),
                          'shards': [len(g['test_ids']) for g in contract['shards']]}, ensure_ascii=False))
        return 0
    if args.mode == 'gui':
        return run_gui(args.shard, args.run_id)
    if args.mode == 'suite':
        return run_suite(args.shard, args.run_id)
    return run_parallel()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, KeyError, OSError) as error:
        print('격리 검증 실패: ' + str(error), file=sys.stderr, flush=True)
        traceback.print_exc()
        sys.exit(1)
