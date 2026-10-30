"""제품을 수정하지 않고 원문78과 Qt 타이밍을 관측한다."""
import json, os, runpy, sys, time, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent/'state-mark-before'
OUT.mkdir(exist_ok=False)
os.environ['QT_QPA_PLATFORM']='offscreen'
sys.path.insert(0,str(ROOT/'소스'))
import ui_motion
from PySide6.QtTest import QTest
trace=[]
zero=time.perf_counter()
def record(kind,mark,**values):
    trace.append(dict(ms=round((time.perf_counter()-zero)*1000,3),kind=kind,mark=id(mark),visible=mark.isVisible(),state=mark.state,animation=mark.animation.state().name,current=mark.animation.currentTime(),**values))
original_init=ui_motion.StateMark.__init__
original_respond=ui_motion.StateMark.respond
original_wait=QTest.qWait
marks=[]
def init(self,*a,**kw):
    original_init(self,*a,**kw);marks.append(self)
    self.animation.valueChanged.connect(lambda value:record('frame',self,value=value))
    self.animation.stateChanged.connect(lambda new,old:record('transition',self,new=new.name,old=old.name))
def respond(self,state):
    record('respond-before',self,target=state)
    result=original_respond(self,state)
    record('respond-after',self,target=state)
    return result
def wait(ms):
    for mark in marks:record('wait-before',mark,wait=ms)
    original_wait(ms)
    for mark in marks:record('wait-after',mark,wait=ms)
ui_motion.StateMark.__init__=init
ui_motion.StateMark.respond=respond
QTest.qWait=wait
original_runner=unittest.TextTestRunner
class Runner(original_runner):
    def run(self,suite):
        cases=list(suite)
        case=next(c for c in cases if c._testMethodName.startswith('test_78'))
        return super().run(unittest.TestSuite([type(case)(case._testMethodName) for _ in range(12)]))
unittest.TextTestRunner=Runner
sys.argv=[str(ROOT/'소스/test_gui.py'),str(OUT)]
code=0
try:runpy.run_path(sys.argv[0],run_name='__main__')
except SystemExit as e:code=e.code or 0
finally:(OUT/'timeline.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2),encoding='utf-8')
sys.exit(code)
