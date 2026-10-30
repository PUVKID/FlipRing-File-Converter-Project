"""동결 소스를 바꾸지 않고 검사 구간·도구 탐색·기동 지연을 측정한다."""
from pathlib import Path
from datetime import datetime
import faulthandler
import hashlib
import json
import os
import runpy
import shutil
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODE = sys.argv[1]
OUT = ROOT / 'work' / ('final-timeout20-io-' + MODE)
FILES = ('app.py', 'studio_ui.py', 'pdf_panel.py', 'i18n.py', 'ui_motion.py', 'test_gui.py', 'engine.py', 'pdf_tools.py')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp():
    return datetime.now().astimezone().isoformat()


if '--child' not in sys.argv:
    OUT.mkdir(exist_ok=False)
    state = json.loads((ROOT / '.codex/routing-state/8497857bac3133cb43214010.json').read_text(encoding='utf-8-sig'))
    argv = [sys.executable, '-B', '-X', 'utf8', str(Path(__file__).resolve()), MODE, '--child']
    before = {name: sha(ROOT / '소스' / name) for name in FILES}
    record = {
        'started_kst': stamp(), 'session': state['session_id'], 'task': state['task_id'],
        'repair_used': state['repair_used'], 'input_fix_used': state['input_fix_used'],
        'verification_failures': state['verification_failures'], 'argv': argv, 'cwd': str(ROOT),
        'timeout_seconds': 30, 'scope': '읽기전용 진단. 검사·제품·중앙 명세를 수정하지 않고 같은 검사 본문을 새 격리 출력에 실행합니다.',
        'environment': {key: os.environ.get(key) for key in ('PATH', 'PATHEXT', 'TEMP', 'TMP', 'PYTHONPATH', 'PYTHONHOME', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM', 'WINDIR')},
        'source_before': before,
    }
    (OUT / '실행기록.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    sys.path.insert(0, 'D:/2026/Codex 관련/Codex 모델 라우팅/3차/tools')
    from routing_stop import run_check
    check = {'id': '구간측정-' + MODE, 'argv': argv, 'cwd': str(ROOT), 'timeout_seconds': 30}
    record['launch_kst'] = stamp()
    started = time.perf_counter()
    result = run_check(check)
    record.update(finished_kst=stamp(), elapsed_seconds=time.perf_counter() - started,
                  result=result, source_after={name: sha(ROOT / '소스' / name) for name in FILES})
    record['source_unchanged'] = record['source_before'] == record['source_after']
    (OUT / '실행기록.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(record, ensure_ascii=False))
    sys.exit(0 if result['status'] == 'passed' else 1)

origin = time.perf_counter()
events = (OUT / '구간.jsonl').open('w', encoding='utf-8', newline='\n', buffering=1)
trace = (OUT / '장기실행스택.log').open('w', encoding='utf-8')
faulthandler.enable(file=trace)
faulthandler.dump_traceback_later(23, file=trace)
active = ''
counts = {}


def event(kind, **data):
    events.write(json.dumps({'at_kst': stamp(), 'elapsed': time.perf_counter() - origin,
                             'cpu_seconds': time.process_time(), 'event': kind,
                             'test': active, **data}, ensure_ascii=False) + '\n')


def observe_function(module, name):
    original = getattr(module, name)

    def observed(*args, **kwargs):
        began = time.perf_counter()
        event(name + '_start', argument=str(args[0]) if args else '')
        try:
            return original(*args, **kwargs)
        finally:
            duration = time.perf_counter() - began
            item = counts.setdefault(name, {'calls': 0, 'wall_seconds': 0.0})
            item['calls'] += 1
            item['wall_seconds'] += duration
            event(name + '_end', seconds=duration)

    setattr(module, name, observed)


start_test = unittest.TextTestResult.startTest
stop_test = unittest.TextTestResult.stopTest
test_starts = {}


def started(self, test):
    global active
    active = test.id()
    test_starts[active] = time.perf_counter()
    event('test_start')
    return start_test(self, test)


def stopped(self, test):
    event('test_end', seconds=time.perf_counter() - test_starts[test.id()])
    return stop_test(self, test)


unittest.TextTestResult.startTest = started
unittest.TextTestResult.stopTest = stopped
event('child_started', actual_argv=sys.argv, actual_cwd=os.getcwd())
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, str(ROOT / '소스'))
observe_function(shutil, 'which')
event('import_engine_start')
import engine
event('import_engine_end')
observe_function(engine, 'tool')
event('test_module_start')
script = '소스/test_gui.py' if MODE == 'gui' else '소스/test_pdf_tools.py'
sys.argv = [script, str(OUT / 'results')] + ([] if MODE == 'gui' else ['--ocr', '--gui'])
code = 0
try:
    namespace = runpy.run_path('소스/test_gui.py', run_name='diagnostic_target')
    event('test_import_end')
    observe_function(Path, 'open')
    observe_function(Path, 'write_text')
    observe_function(Path, 'replace')
    observe_function(namespace['app'].QSettings, 'sync')
    for name in ('set_language', 'retranslate', 'append_record'):
        observe_function(namespace['app'].MainWindow, name)
    suite = unittest.TestSuite([namespace['GuiTests']('test_40_pdf_error_history_status_and_notifications_switch_both_ways')])
    result = unittest.TextTestRunner(verbosity=2, failfast=True).run(suite)
    code = int(not result.wasSuccessful())
except SystemExit as exc:
    code = exc.code or 0
finally:
    event('child_finished', exit_code=code, function_counts=counts)
    faulthandler.cancel_dump_traceback_later()
    events.close()
    trace.close()
sys.exit(code)
