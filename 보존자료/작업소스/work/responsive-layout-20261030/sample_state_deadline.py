"""종료 시점만 표본 관측하며 첫 실패 시 원문 상태를 보존한다."""
import os,sys,time,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];WORK=Path(__file__).resolve().parent
os.environ['QT_QPA_PLATFORM']='offscreen:configfile=work/responsive-layout-20261030/offscreen-render.json';sys.path.insert(0,str(ROOT/'소스'))
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
import app
from ui_motion import StateMark
app.DATA=WORK/'state-deadline-sample-settings';q=QApplication([]);app.apply_application_style(q);window=app.MainWindow();window.timer.stop();window.show();q.processEvents();mark=StateMark();mark.show();q.processEvents();QTest.qWait(450)
results=[];current={};zero=0
mark.deadline.timeout.connect(lambda:current['events'].append({'kind':'timeout','ms':(time.perf_counter()-zero)*1000,'current':mark.animation.currentTime()}))
mark.animation.valueChanged.connect(lambda value:current['events'].append({'kind':'frame','ms':(time.perf_counter()-zero)*1000,'current':mark.animation.currentTime()}) if current else None)
for index in range(90):
 delay=(0,50,100)[index%3];current={'index':index,'delay':delay,'events':[]};zero=time.perf_counter();mark.respond('complete');time.sleep(delay/1000);current['prewait_remaining']=mark.deadline.remainingTime();QTest.qWait(420-delay);current.update(wall_ms=(time.perf_counter()-zero)*1000,state=mark.animation.state().name,current=mark.animation.currentTime(),timer_active=mark.deadline.isActive(),remaining=mark.deadline.remainingTime());results.append(current)
 if current['state']!='Stopped':break
(WORK/'state-deadline-sampling.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'samples':len(results),'last':results[-1]},ensure_ascii=False));window.tray.hide();window.hide();mark.hide();window.pool.shutdown(wait=True);window.pdf_panel._pool.shutdown(wait=True);sys.exit(0 if all(item['state']=='Stopped' for item in results) else 1)
