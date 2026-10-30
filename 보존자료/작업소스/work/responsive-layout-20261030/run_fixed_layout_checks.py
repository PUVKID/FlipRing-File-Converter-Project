"""배율별 자식 검사를 순서대로 실행하고 실패 원문부터 보존한다."""
import datetime,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
WORK=Path(__file__).resolve().parent
scale=sys.argv[1];label=sys.argv[2];config=sys.argv[3] if len(sys.argv)>3 else 'offscreen-render.json'
argv=[str(ROOT/'work/venv/Scripts/python.exe'),'-B','-X','utf8',str(ROOT/'소스/test_fixed_layout.py'),str(WORK/label)]
env=os.environ.copy();env.update(QT_QPA_PLATFORM='offscreen:configfile=work/responsive-layout-20261030/'+config,QT_SCALE_FACTOR=scale)
state=json.loads((ROOT/'.codex/routing-state/8497857bac3133cb43214010.json').read_text(encoding='utf-8'))
record={'time_kst':datetime.datetime.now().astimezone().isoformat(),'session':'01a15519-c86d-7880-a2e6-c9070f59067d','task':'workflow-enhancement-20261030','repair_used':state['repair_used'],'input_fix_used':state['input_fix_used'],'argv':argv,'cwd':str(ROOT),'env':{k:env[k] for k in ['QT_QPA_PLATFORM','QT_SCALE_FACTOR']},'changes':'수리24선택창이름열과고밀도아이콘/고정창2assert; 모션기준불변'}
with (WORK/(label+'.stdout.log')).open('xb') as out,(WORK/(label+'.stderr.log')).open('xb') as err:p=subprocess.run(argv,cwd=ROOT,env=env,stdout=out,stderr=err)
record.update(exit_code=p.returncode,finished_kst=datetime.datetime.now().astimezone().isoformat())
if p.returncode:record['error_original']=(WORK/(label+'.stderr.log')).read_text(encoding='utf-8')
(WORK/(label+'.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(record,ensure_ascii=False));sys.exit(p.returncode)
