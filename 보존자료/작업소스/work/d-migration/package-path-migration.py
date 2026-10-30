import ast
from datetime import datetime
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(r'D:\2026\FilpRing Project')
OUT = ROOT / 'work/d-migration'
SESSION = '01a15519-c86d-7880-a2e6-c9070f59067d'
TASK = 'studio-redesign-20261021'
def info(path):
    raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'mtime': path.stat().st_mtime}
def save(name, obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
files = [ROOT/'.codex/routing-checks.json',ROOT/'소스/FlipRing.spec',ROOT/'소스/빌드방법.md']
before = [info(p) for p in files]
for p in files:
    target = OUT/'before'/p.relative_to(ROOT)
    target.parent.mkdir(parents=True,exist_ok=True)
    if not target.exists():
        shutil.copy2(p,target)
old = r'C:\Users\PUVKID\Desktop\플립링'
checks_path=files[0]
checks=json.loads(checks_path.read_text(encoding='utf-8'))
for check in checks['checks']:
    assert check['argv'][0] == old + r'\work\venv\Scripts\python.exe'
    check['argv'][0]=str(ROOT/'work/venv/Scripts/python.exe')
# 보호된 검사 명세는 부모가 지원된 권한으로 별도 갱신한다.
spec=files[1].read_text(encoding='utf-8')
assert spec.count(old.replace('\\','\\\\')) == 5
spec=spec.replace(old.replace('\\','\\\\'),str(ROOT).replace('\\','\\\\'))
ast.parse(spec)
files[1].write_text(spec,encoding='utf-8')
doc=files[2].read_text(encoding='utf-8')
addition='''\n## D드라이브 이동 후 현재 작업 위치\n\n2026-10-24에 실제 프로젝트를 `D:\\2026\\FilpRing Project`에서 확인했습니다. 현재 빌드 작업의 기준 폴더는 `D:\\2026\\FilpRing Project\\소스`이며 위 상대 경로 명령은 같은 방식으로 사용할 수 있습니다. 프로그램·설치 파일·전체 소스·빌드 방법·라이선스는 이 프로젝트 한 폴더에 보관합니다.\n\n이동한 개발 환경은 `D:\\2026\\FilpRing Project\\work\\venv\\Scripts\\python.exe`입니다. 해당 가상환경의 기본 Python은 현재 존재하는 C드라이브의 공용 Codex 런타임을 사용합니다. 가상환경 자체가 Python을 모두 포함하는 것은 아니므로 다른 PC에서는 위 신규 환경 생성 절차를 사용하세요. `pyvenv.cfg`의 기본 런타임이나 과거 검증 기록의 C경로를 임의로 D경로로 치환하지 마세요. 활성 검사 명세와 PyInstaller 명세의 현재 프로젝트 경로만 D 위치에 맞추었습니다.\n'''
assert '## D드라이브 이동 후 현재 작업 위치' not in doc
files[2].write_text(doc.rstrip()+'\n'+addition,encoding='utf-8')
rows=[line.split('==',1) for line in (ROOT/'소스/requirements-lock.txt').read_text(encoding='utf-8').splitlines() if '==' in line]
deps=[{'name':name,'expected':value,'actual':metadata.version(name),'match':metadata.version(name)==value} for name,value in rows]
assert len(deps)==31 and all(d['match'] for d in deps)
original=json.loads((OUT/'before/.codex/routing-checks.json').read_text(encoding='utf-8'))
for previous,current in zip(original['checks'],checks['checks']):
    previous['argv'][0]=current['argv'][0]
assert original==checks
save('기계경로이행.json',{'time_kst':datetime.now().astimezone().isoformat(),'session':SESSION,'task':TASK,'role':'build','tool_requested_model':'gpt-6.1-sol','tool_requested_effort':'medium','server_runtime_identity':'확인 불가','repair_used':8,'input_fix_used':7,'grant_scope':'이번 child turn의 D프로젝트 write 승인','before':before,'after':[info(p) for p in files],'check_assertions_and_timeouts_preserved':True,'files_changed':2,'build_executed':False,'dependencies':deps,'python':sys.version,'base_prefix':sys.base_prefix})
print(json.dumps({'changed':2,'dependencies_match':len(deps),'timeouts':[c['timeout_seconds'] for c in checks['checks']],'total_timeout_seconds':checks['total_timeout_seconds'],'backup':str(OUT/'before')},ensure_ascii=False))

