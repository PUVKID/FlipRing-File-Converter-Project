"""열려 있는 선택창의 언어 이벤트와 폴더 수락 라벨을 읽기 관찰한다."""
import os,sys,json
from pathlib import Path
from unittest.mock import patch
os.environ['QT_QPA_PLATFORM']='offscreen';root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'소스'))
import app,ui_motion
from PySide6.QtWidgets import QApplication,QFileDialog
out=root/'work/internal-motion-label-box-diagnostic';out.mkdir(exist_ok=True)
a=QApplication([]);app.apply_application_style(a);app.DATA=out/'data'
log=[];original=ui_motion.MotionFileDialog.set_language

def trace(d,language):
    before=d.labelText(QFileDialog.Accept)
    original(d,language)
    log.append({'event':'set_language','folder':d.folder_mode,'input':language,'before':before,'after':d.labelText(QFileDialog.Accept),'mode':str(d.fileMode())})

with patch.object(app.MainWindow,'autostart_enabled',return_value=False):w=app.MainWindow()
w.timer.stop();w.tray.hide()
with patch.object(ui_motion.MotionFileDialog,'set_language',trace):
    dialogs=[w.file_dialog(False),w.file_dialog(True),w.pdf_panel.file_dialog()]
    from PySide6.QtCore import QObject,QEvent
    from PySide6.QtWidgets import QDialogButtonBox
    class Guard(QObject):
        def eventFilter(self,w,e):
            return e.type()==QEvent.LanguageChange
    guards=[]
    for d in dialogs:
        box=d.findChild(QDialogButtonBox);g=Guard(box);box.installEventFilter(g);guards.append(g)
    for d in dialogs:
        d.setDirectory(str(root))
        log.append({'event':'constructed','folder':d.folder_mode,'accept':d.labelText(QFileDialog.Accept),'mode':str(d.fileMode())})
        for language in ('en','ko'):
            w.set_language(language);a.processEvents()
            log.append({'event':'after_events','language':language,'folder':d.folder_mode,'accept':d.labelText(QFileDialog.Accept),'title':d.heading.text(),'mode':str(d.fileMode())})
(out/'이벤트-순서.json').write_text(json.dumps(log,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(log,ensure_ascii=False))
for d in dialogs:d.hide()
w.hide();w.pool.shutdown(wait=True);w.pdf_panel.shutdown(wait=True)

