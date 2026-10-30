"""새 릴리스만 별도 폴더에서 빌드하고 원문 로그를 보존한다."""
from pathlib import Path
from datetime import datetime
import json
import os
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
WORK=Path(__file__).resolve().parent
stage=WORK/'release-stage1'
argv=[str(ROOT/'work/venv/Scripts/python.exe'),'-B','-X','utf8',str(ROOT/'소스/build.py'),'--output-root',str(stage)]
assert not (stage/'프로그램/FlipRing/FlipRing.exe').exists()
assert not (WORK/'build-execution.json').exists()
state=json.loads((ROOT/'.codex/routing-state/8497857bac3133cb43214010.json').read_text(encoding='utf-8'))
record={'started_kst':datetime.now().astimezone().isoformat(),'argv':argv,'cwd':str(ROOT),'release':'1.8.0','repair_used':state['repair_used'],'input_fix_used':state['input_fix_used'],'changes':'고정 창·영역 구분·배율 및 상태 모션 보완'}
env=os.environ.copy()
env.update(PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
with (WORK/'build.stdout.log').open('xb') as out,(WORK/'build.stderr.log').open('xb') as err:
    result=subprocess.run(argv,cwd=ROOT,env=env,stdout=out,stderr=err,timeout=900)
record.update(finished_kst=datetime.now().astimezone().isoformat(),exit_code=result.returncode)
if result.returncode:
    raw=(WORK/'build.stderr.log').read_bytes()
    record['error_original_tail']=raw[-16000:].decode('utf-8',errors='replace')
(WORK/'build-execution.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(record,ensure_ascii=False))
sys.exit(result.returncode)
