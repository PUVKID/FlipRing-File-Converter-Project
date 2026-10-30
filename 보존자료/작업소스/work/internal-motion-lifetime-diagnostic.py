"""재생성 메뉴 소유권과 폴더 형식의 언어를 읽기 관찰한다."""
from pathlib import Path
import os,sys,json
from unittest.mock import patch
os.environ['QT_QPA_PLATFORM']='offscreen'
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'소스'))
import app
from PySide6.QtCore import QFileInfo
from PySide6.QtWidgets import QApplication,QFileIconProvider,QMenu
from PySide6.QtTest import QTest
out=root/'work/internal-motion-lifetime-diagnostic';out.mkdir(exist_ok=True)
a=QApplication([]);app.apply_application_style(a);app.DATA=out/'data'
with patch.object(app.MainWindow,'autostart_enabled',return_value=False):w=app.MainWindow()
w.timer.stop();w.tray.hide()
counts=[]
for n in range(4):
    counts.append(len(w.tray_menu.findChildren(QMenu)))
    w.update_tray_menu()
provider=QFileIconProvider()
report={'menu_descendants_per_rebuild':counts,'system_folder_type':provider.type(QFileInfo(str(root/'소스'))),'system_python_type':provider.type(QFileInfo(str(root/'소스/app.py')))}
d=w.file_dialog(False);d.setDirectory(str(root));d.show();QTest.qWait(100)
from PySide6.QtWidgets import QTreeView
t=d.findChild(QTreeView,'treeView');model=t.model();index=model.index(str(root/'소스'))
report['custom_folder_ko']=str(model.data(index.siblingAtColumn(2)))
w.set_language('en');a.processEvents()
report['custom_folder_en']=str(model.data(index.siblingAtColumn(2)))
report['caption_en']=d.caption.text();report['heading_en']=d.heading.text()
(out/'관찰.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
d.hide();w.hide();w.pool.shutdown(wait=True);w.pdf_panel.shutdown(wait=True)
