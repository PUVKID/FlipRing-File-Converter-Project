"""격리한 실제 Qt 위젯의 유한 모션을 PNG/GIF로 보관한다. 데스크톱 캡처가 아니다."""
from pathlib import Path
from unittest.mock import patch
import os,sys,json
os.environ['QT_QPA_PLATFORM']='offscreen'
root=Path(__file__).resolve().parents[1];out=root/'work/internal-motion-preview';out.mkdir(exist_ok=True)
sys.path.insert(0,str(root/'소스'))
import app
from ui_motion import SurfaceMotion
from PySide6.QtWidgets import QApplication,QTreeView
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PIL import Image
application=QApplication([]);application.setQuitOnLastWindowClosed(False);app.apply_application_style(application)
app.DATA=out/'격리설정'
with patch.object(app.MainWindow,'autostart_enabled',return_value=False),patch.object(app.QSystemTrayIcon,'show'):
    window=app.MainWindow()
window.timer.stop();window.notifications.setChecked(False);window.reveal.setChecked(False)
fixtures=out/'선택 시험';fixtures.mkdir(exist_ok=True);(fixtures/'문서 폴더').mkdir(exist_ok=True)
for name in ('이미지 A.png','이미지 B.png'):Image.new('RGB',(32,24),'white').save(fixtures/name)
window.show();QTest.qWait(740);window.grab().save(str(out/'01-home.png'))

def raster(widget):
    picture=widget.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
    return Image.frombytes('RGBA',(picture.width(),picture.height()),picture.bits().tobytes(),'raw','RGBA',picture.bytesPerLine()).convert('RGB')

def stop_surfaces(widget):
    for motion in widget.findChildren(SurfaceMotion):motion.stop()
    own=getattr(widget,'_flipring_surface_motion',None)
    if own is not None:own.stop()

def frames_for(dialog):
    stop_surfaces(dialog);motion=dialog._flipring_surface_motion;motion.pulse();dialog.mark.respond();frames=[]
    for elapsed in (0,35,70,110,170,240,280,380):
        motion.animation.setCurrentTime(min(elapsed,motion.animation.duration()));dialog.mark.animation.setCurrentTime(min(elapsed,380));frames.append(raster(dialog))
    tree=dialog.findChild(QTreeView,'treeView');index=tree.model().index(str(fixtures/'이미지 A.png'));tree.scrollTo(index);QTest.mouseClick(tree.viewport(),Qt.LeftButton,pos=tree.visualRect(index).center())
    row_motion=tree._flipring_surface_motion
    for elapsed in (0,45,90,150,220,280,380):
        row_motion.animation.setCurrentTime(min(elapsed,280));dialog.mark.animation.setCurrentTime(min(elapsed,380));frames.append(raster(dialog))
    return frames

dialog=window.file_dialog(False);dialog.setDirectory(str(fixtures));dialog.show();QTest.qWait(100)
frames=frames_for(dialog);dialog.grab().save(str(out/'02-file-picker.png'))
frames[0].save(out/'file-picker-open-select.gif',save_all=True,append_images=frames[1:],duration=[70]*len(frames),loop=0,optimize=True)
dialog.reject();motion=window._flipring_surface_motion;frames=[]
for elapsed in (0,50,100,170,230,280):
    motion.animation.setCurrentTime(elapsed);frames.append(raster(window))
frames[0].save(out/'picker-return-response.gif',save_all=True,append_images=frames[1:],duration=80,loop=0,optimize=True)
dialog.deleteLater()
folder=window.file_dialog(True);folder.setDirectory(str(fixtures));folder.show();QTest.qWait(400);folder.grab().save(str(out/'03-folder-picker.png'));folder.reject();folder.deleteLater()
message=app.message_dialog(window,'작업 상태 안내','원본은 보존됩니다. 선택·진행·완료는 실제 작업 상태에 이어집니다.');message.show();application.processEvents();mark=message._flipring_message_mark;motion=message._flipring_surface_motion;frames=[]
for elapsed in (0,50,100,180,280,380):
    motion.animation.setCurrentTime(min(elapsed,280));mark.animation.setCurrentTime(elapsed);frames.append(raster(message))
message.grab().save(str(out/'04-message.png'));frames[0].save(out/'message-response.gif',save_all=True,append_images=frames[1:],duration=80,loop=0,optimize=True);message.reject();message.deleteLater()
for page,name in ((4,'05-pdf'),(2,'07-history'),(1,'08-helpers'),(3,'09-about')):
    window.tabs.setCurrentIndex(page);QTest.qWait(430);window.grab().save(str(out/(name+'.png')))
    if page==4:
        panel=window.pdf_panel;panel.set_files([str(fixtures/'이미지 A.png'),str(fixtures/'이미지 B.png')]);panel.operation.setCurrentIndex(panel.operation.findData('recognize'));QTest.qWait(430);window.grab().save(str(out/'06-ocr.png'))
window.set_language('en');window.tabs.setCurrentIndex(0);QTest.qWait(750);window.grab().save(str(out/'10-home-en.png'))
window.hide();window.tray.hide();window.pool.shutdown(wait=True);window.pdf_panel.shutdown(wait=True)
metadata={'platform':application.platformName(),'scope':'소스에서 직접 생성한 실제 Qt 위젯 렌더. OS 데스크톱/설치본/물리 Shift 캡처 아님. GIF 반복은 검토 미리보기만이며 앱은 유한 애니메이션.','files':[{'name':p.name,'bytes':p.stat().st_size} for p in out.iterdir() if p.is_file()]}
(out/'렌더기록.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(metadata,ensure_ascii=False))
