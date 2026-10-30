"""변경하지 않은 실제 PDF/OCR 전체 검사를 실행하고 원문·시간을 기록한다."""
from pathlib import Path
from datetime import datetime
import os,sys,json,time,subprocess
root=Path(__file__).resolve().parents[1];out=root/'work/internal-motion-final-pdf17';out.mkdir(exist_ok=True)
argv=[sys.executable,'-B','-X','utf8','소스/test_pdf_tools.py',str(out/'results'),'--ocr','--gui']
s=json.loads((root/'.codex/routing-state/8497857bac3133cb43214010.json').read_text(encoding='utf-8-sig'))
r={'started_kst':datetime.now().astimezone().isoformat(),'session':s['session_id'],'task':s['task_id'],'repair_used':s['repair_used'],'input_fix_used':s['input_fix_used'],'argv':argv,'cwd':str(root)}
(out/'실행기록.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8');env=os.environ.copy();env['QT_QPA_PLATFORM']='offscreen';start=time.monotonic()
p=subprocess.run(argv,cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60);data=p.stdout
(out/'출력.log').write_bytes(data[:262144]);r.update(exit_code=p.returncode,elapsed_seconds=time.monotonic()-start,output_bytes=len(data),captured_bytes=min(len(data),262144),truncated=len(data)>262144)
(out/'실행기록.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(r,ensure_ascii=False));print(data[:262144].decode('utf-8',errors='replace'));sys.exit(p.returncode)
