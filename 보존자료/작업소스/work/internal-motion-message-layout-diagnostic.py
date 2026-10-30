"""메시지 내부 본문의 실제 Qt 셀 배치를 읽기 관찰한다."""
import os,sys,json
from pathlib import Path
os.environ['QT_QPA_PLATFORM']='offscreen';root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'소스'))
import app
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
out=root/'work/internal-motion-message-layout-diagnostic';out.mkdir(exist_ok=True)
a=QApplication([]);app.apply_application_style(a)
d=app.message_dialog(None,'작업 상태 안내','원본은 보존됩니다. 선택·진행·완료는 실제 작업 상태에 이어집니다.');d.show();QTest.qWait(420)
l=d.layout();rows=[]
for n in range(l.count()):
    item=l.itemAt(n);widget=item.widget();rows.append({'position':l.getItemPosition(n),'widget':widget.metaObject().className() if widget else None,'name':widget.objectName() if widget else None,'geometry':str(item.geometry()),'size_hint':str(item.sizeHint()),'spacer':item.spacerItem() is not None})
(out/'배치.json').write_text(json.dumps({'dialog_geometry':str(d.geometry()),'items':rows,'stretches':[l.columnStretch(i) for i in range(l.columnCount())]},ensure_ascii=False,indent=2),encoding='utf-8');print((out/'배치.json').read_text(encoding='utf-8'))
d.hide()
