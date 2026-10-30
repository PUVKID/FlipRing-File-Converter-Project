"""공통 선택창 열 머리글의 모델·배치·효과를 읽기 대조한다."""
import sys, json, os
from pathlib import Path
from unittest.mock import patch
os.environ['QT_QPA_PLATFORM']='offscreen'
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'소스'))
import app
from PySide6.QtWidgets import QApplication, QTreeView, QHeaderView
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
out=root/'work/internal-motion-header-diagnostic'
out.mkdir(exist_ok=True)
app.DATA=out/'settings'
a=QApplication([])
app.apply_application_style(a)
with patch.object(app.MainWindow,'autostart_enabled',return_value=False):
    w=app.MainWindow()
w.timer.stop();w.tray.hide()
d=w.file_dialog(False); d.setDirectory(str(root/'소스'));d.show();QTest.qWait(350)
tree=d.findChild(QTreeView,'treeView'); h=tree.header()
rows=[]
for column in range(tree.model().columnCount()):
    rows.append({'column':column,'label':str(tree.model().headerData(column,Qt.Horizontal,Qt.DisplayRole)), 'header_label':str(h.model().headerData(column,Qt.Horizontal,Qt.DisplayRole)), 'width':h.sectionSize(column),'hidden':h.isSectionHidden(column),'resize_mode':str(h.sectionResizeMode(column))})
d.grab().save(str(out/'with-motion.png'))
for surface in d.findChildren(app.QObject):
    if surface.__class__.__name__=='SurfaceMotion':surface.stop()
d.grab().save(str(out/'motion-stopped.png'))
h.setStyleSheet('QHeaderView {padding:0;border:0;border-radius:0;}');a.processEvents();d.grab().save(str(out/'header-padding-zero.png'));print('header-zero',str(h.viewport().geometry()))
report={'headers':rows,'header_visible':h.isVisible(),'header_geometry':str(h.geometry()),'header_viewport':str(h.viewport().geometry()),'tree_geometry':str(tree.geometry()),'style':h.styleSheet(),'font':h.font().family(),'foreground':str(h.palette().color(h.foregroundRole()).name()),'root_directory':d.directory().absolutePath()}
(out/'모델-배치.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
d.hide();d.deleteLater();w.hide();w.pool.shutdown(wait=True);w.pdf_panel.shutdown(wait=True)

