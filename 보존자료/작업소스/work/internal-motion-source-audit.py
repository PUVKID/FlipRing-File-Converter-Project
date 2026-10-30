"""독립 검증을 대신하지 않는 구현자 측 소스 대조 근거를 기록한다."""
from pathlib import Path
from datetime import datetime
import ast,json,hashlib,sys
root=Path(__file__).resolve().parents[1]
files=list((root/'소스').glob('*.py'))
for path in files:
    text=path.read_bytes().decode('utf-8-sig',errors='strict')
    if '\ufffd' in text:raise ValueError(f'대체문자 발견: {path}')
    ast.parse(text,filename=str(path))
owned=['app.py','studio_ui.py','pdf_panel.py','i18n.py','ui_motion.py','test_gui.py']
baseline=json.loads((root/'work/internal-motion-baseline/보존목록.json').read_text(encoding='utf-8-sig'))
backend={}
for name in ['engine.py','pdf_tools.py']:
    digest=hashlib.sha256((root/'소스'/name).read_bytes()).hexdigest()
    old=next(item['sha256'] for item in baseline if item['name']==name)
    assert digest.lower()==old.lower()
    backend[name]=digest
state=json.loads((root/'.codex/routing-state/8497857bac3133cb43214010.json').read_text(encoding='utf-8-sig'))
global_path=Path('C:/Users/PUVKID/.codex/AGENTS.md')
report={'recorded_kst':datetime.now().astimezone().isoformat(),'argv':[sys.executable,'-B','-X','utf8']+sys.argv,'cwd':str(root),'session':state['session_id'],'task':state['task_id'],'repair_used':state['repair_used'],'input_fix_used':state['input_fix_used'],'role_assignment':'deep / gpt-6.1-sol / xhigh; 부모의 도구 배정 근거이며 서버 내부 런타임 신원 보증 아님','utf8_ast_py_files':len(files),'backend_unchanged':backend,'owned_files':{name:{'bytes':(root/'소스'/name).stat().st_size,'sha256':hashlib.sha256((root/'소스'/name).read_bytes()).hexdigest()} for name in owned},'global_guidance':{'path':str(global_path),'bytes':global_path.stat().st_size,'sha256':hashlib.sha256(global_path.read_bytes()).hexdigest()},'gui':{'tests':85,'passed':85,'skipped':0,'elapsed':28.703,'evidence':'work/internal-motion-final-gui/실행기록.json'},'pdf':{'tests':28,'passed':28,'skipped':0,'elapsed':13.562,'evidence':'work/internal-motion-final-pdf/실행기록.json'},'source_frozen':False,'pending':'메시지 NoIcon 본문 폭의 부모 수리 배정 대기. 수리 후 새 GUI 확인·소스 동결 필요','scope_limits':['오프스크린 Qt 직접 렌더/모형 이벤트와 설치본 Windows 직접 실행은 별도','물리 Shift/OLE·새 EXE/설치·독립 verifier/Stop은 부모 조율','서버 실제 모델 증명/실제 API 비용 미확인']}
(root/'evidence/내부모션-구현중간대조.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
