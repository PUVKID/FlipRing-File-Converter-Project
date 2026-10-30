"""내부 화면 구현 검사를 실제 인자와 누적 상태에 결합해 기록한다."""
from pathlib import Path
from datetime import datetime
import subprocess
import sys
import json
import os
import time

root = Path(__file__).resolve().parents[1]
name = sys.argv[1]
folder = root / 'work' / name
folder.mkdir(parents=True, exist_ok=True)
if len(sys.argv) > 2:
    selected = sys.argv[2:]
    code = 'import sys,unittest;sys.argv=["소스/test_gui.py",' + repr(str(folder / 'gui')) + '];sys.path.insert(0,"소스");import test_gui as t;suite=unittest.TestSuite(t.GuiTests(n) for n in ' + repr(selected) + ');r=unittest.TextTestRunner(verbosity=2,failfast=True).run(suite);sys.exit(not r.wasSuccessful())'
    argv = [sys.executable, '-B', '-X', 'utf8', '-c', code]
else:
    argv = [sys.executable, '-B', '-X', 'utf8', '소스/test_gui.py', str(folder / 'gui')]
state = json.loads((root / '.codex/routing-state/8497857bac3133cb43214010.json').read_text(encoding='utf-8-sig'))
metadata = {'started_kst': datetime.now().astimezone().isoformat(), 'session': state['session_id'], 'task': state['task_id'], 'repair_used': state['repair_used'], 'input_fix_used': state['input_fix_used'], 'argv': argv, 'cwd': str(root), 'source_changed': True}
(folder / '실행기록.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
env = os.environ.copy()
env['QT_QPA_PLATFORM'] = 'offscreen'
start = time.monotonic()
process = subprocess.Popen(argv, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
output = process.communicate(timeout=90)[0]
(folder / '출력.log').write_bytes(output[:262144])
metadata.update(exit_code=process.returncode, elapsed_seconds=time.monotonic()-start, output_bytes=len(output), captured_bytes=min(len(output),262144), truncated=len(output)>262144)
(folder / '실행기록.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(metadata, ensure_ascii=False))
print(output[:262144].decode('utf-8',errors='replace'))
sys.exit(process.returncode)
