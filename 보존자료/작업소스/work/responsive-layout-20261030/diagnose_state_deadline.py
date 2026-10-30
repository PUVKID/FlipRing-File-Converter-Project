"""추가 수정 없이 실제 신규 검사에서 기한 타이머와 틱을 관측한다."""
import json,os,runpy,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent/'state-deadline-diagnostic';OUT.mkdir(exist_ok=False)
os.environ['QT_QPA_PLATFORM']='offscreen:configfile=work/responsive-layout-20261030/offscreen-render.json'
sys.path.insert(0,str(ROOT/'소스'))
from PySide6.QtTest import QTest
from shiboken6 import isValid
import ui_motion
zero=time.perf_counter();trace=[];marks=[]
def record(kind,mark,**kw):
 if isValid(mark):trace.append(dict(ms=round((time.perf_counter()-zero)*1000,3),mark=id(mark),kind=kind,state=mark.state,animation=mark.animation.state().name,current=mark.animation.currentTime(),deadline_active=mark.deadline.isActive(),remaining=mark.deadline.remainingTime(),**kw))
init=ui_motion.StateMark.__init__;respond=ui_motion.StateMark.respond;wait=QTest.qWait
def wrapped_init(self,*a,**kw):
 init(self,*a,**kw);marks.append(self);self.animation.valueChanged.connect(lambda value:record('frame',self,value=value));self.deadline.timeout.connect(lambda:record('deadline-timeout',self));self.animation.stateChanged.connect(lambda new,old:record('state',self,new=new.name))
def wrapped_respond(self,state):
 record('respond-before',self,target=state);v=respond(self,state);record('respond-after',self,target=state);return v
def wrapped_wait(ms):
 for m in marks:record('wait-before',m,wait=ms)
 wait(ms)
 for m in marks:record('wait-after',m,wait=ms)
ui_motion.StateMark.__init__=wrapped_init;ui_motion.StateMark.respond=wrapped_respond;QTest.qWait=wrapped_wait
sys.argv=[str(ROOT/'소스/test_fixed_layout.py'),str(OUT)];code=0
try:runpy.run_path(sys.argv[0],run_name='__main__')
except SystemExit as e:code=e.code or 0
finally:(OUT/'timeline.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2),encoding='utf-8')
sys.exit(code)
