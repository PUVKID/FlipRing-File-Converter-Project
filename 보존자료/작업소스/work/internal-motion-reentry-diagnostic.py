"""전역 등록 중복·행 재진입·진행 상태의 실제 그리기값을 격리 관찰한다."""
from pathlib import Path
import os,sys,json
from unittest.mock import patch
os.environ['QT_QPA_PLATFORM']='offscreen';root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'소스'))
import app,ui_motion
from PySide6.QtWidgets import QApplication,QPushButton,QListWidget
from PySide6.QtCore import QRectF
out=root/'work/internal-motion-reentry-diagnostic';out.mkdir(exist_ok=True)
a=QApplication([]);app.apply_application_style(a);app.DATA=out/'data'
with patch.object(app.MainWindow,'autostart_enabled',return_value=False):w=app.MainWindow()
w.timer.stop();w.tray.hide();w.notifications.setChecked(False);w.reveal.setChecked(False)
b=QPushButton('버튼');m=app.ButtonMotion(b);before=len([x for x in b.children() if isinstance(x,app.ButtonMotion)]);b.show();a.processEvents();after=len([x for x in b.children() if isinstance(x,app.ButtonMotion)])
l=QListWidget();l.resize(280,240);motion=ui_motion.ensure_surface_motion(l);l.show();a.processEvents()
motion.pulse(rectangle=QRectF(4,10,250,30));motion.animation.setCurrentTime(280)
motion.pulse(rectangle=QRectF(4,100,250,30));motion.animation.setCurrentTime(85)
def rect_now():
    start=motion.overlay.origin or motion.overlay.rectangle;target=motion.overlay.rectangle;p=motion.overlay.travel
    return QRectF(start.x()+(target.x()-start.x())*p,start.y()+(target.y()-start.y())*p,start.width()+(target.width()-start.width())*p,start.height()+(target.height()-start.height())*p)
pre=rect_now();motion.overlay.grab().save(str(out/'before-retarget.png'));amount=motion.amount
motion.pulse(rectangle=QRectF(4,160,250,30));post=rect_now();motion.overlay.grab().save(str(out/'after-retarget.png'))
w.pending=2;w.finished('진단파일A.png',str(out/'진단결과.png'),'')
report={'button_motion_before_show':before,'after_show':after,'manual_is_registered':getattr(b,'_flipring_button_motion',None) is m,'actual_rectangle_before':str(pre),'actual_rectangle_after':str(post),'amount_before':amount,'amount_after':motion.amount,'remaining':w.pending,'main_orbit_state':w.drop_card.orbit.state,'main_status_mark':w.status_mark.state,'status_text':w.status.text()}
(out/'관측.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
b.hide();l.hide();w.hide();w.pool.shutdown(wait=True);w.pdf_panel.shutdown(wait=True)
