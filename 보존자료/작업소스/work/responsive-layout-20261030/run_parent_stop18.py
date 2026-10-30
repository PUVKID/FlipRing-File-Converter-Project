"""최종 독립 영수증에 이어 부모 완료 검사를 실행하고 원문을 보존한다."""
from pathlib import Path
from datetime import datetime
import json
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
WORK=Path(__file__).resolve().parent
argv=[str(ROOT/'work/venv/Scripts/python.exe'),'-B','-X','utf8','D:/2026/Codex 관련/Codex 모델 라우팅/3차/tools/routing_stop.py']
event={'hook_event_name':'Stop','cwd':str(ROOT),'session_id':'01a15519-c86d-7880-a2e6-c9070f59067d','turn_id':'workflow-enhancement-20261030-parent-18'}
target=WORK/'부모-최종Stop18.json'
assert not target.exists()
start=datetime.now().astimezone().isoformat()
result=subprocess.run(argv,cwd=ROOT,input=json.dumps(event,ensure_ascii=False).encode('utf-8'),capture_output=True,timeout=150)
out=result.stdout.decode('utf-8')
err=result.stderr.decode('utf-8')
record={'start_kst':start,'end_kst':datetime.now().astimezone().isoformat(),'argv':argv,'event':event,'exit_code':result.returncode,'stdout':out,'stderr':err}
target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(record,ensure_ascii=False))
response=json.loads(out)
assert result.returncode==0 and response.get('continue') is True and response.get('decision')!='block'
