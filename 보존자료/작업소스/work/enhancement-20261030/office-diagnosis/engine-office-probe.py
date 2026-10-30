import sys,ctypes,json,hashlib,subprocess,time,datetime
from pathlib import Path
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root.parents[2]/'소스'))
k=ctypes.windll.kernel32
buffer=ctypes.create_unicode_buffer(32768)
def dll_directory():
    size=k.GetDllDirectoryW(len(buffer),buffer)
    return {'size':size,'directory':buffer.value}
before=dll_directory()
import engine
after=dll_directory()
source=root.parent/'matrix-test/run-cd6dd5dc-fc33-4d86-9c22-9cfb469e5f87/fixtures/한글 입력 공백.docx'
work=root/'engine-office'; work.mkdir(exist_ok=False)
original=engine.subprocess.Popen
observed=[]
def traced(*args,**kwargs):
    observed.append({'argv':list(map(str,args[0])),'kwargs':{key:str(value) for key,value in kwargs.items()},'dll_directory':dll_directory()})
    (root/'engine-office-argv.json').write_text(json.dumps(observed,ensure_ascii=False,indent=2),encoding='utf-8')
    return original(*args,**kwargs)
engine.subprocess.Popen=traced
report={'before_import':before,'after_import':after,'source_hash':hashlib.sha256(source.read_bytes()).hexdigest(),'repair_used':12,'input_fix_used':1,'started':datetime.datetime.now().astimezone().isoformat()}
try:
    output=engine.office(source,'pdf',work)
    report['output']=str(output); report['output_bytes']=output.stat().st_size
except Exception as exc: report['error']=repr(exc)
report['source_after']=hashlib.sha256(source.read_bytes()).hexdigest()
(root/'engine-office-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False),flush=True)
