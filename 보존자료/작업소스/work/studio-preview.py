"""운영 설정을 건드리지 않는 새 작업 공간의 자체 Qt 렌더링."""
from pathlib import Path
import ast
import json
import os
import sys
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
source = root / "소스"
out = root / "work" / "studio-preview"
out.mkdir(exist_ok=True)
for path in source.glob("*.py"):
    text = path.read_text(encoding="utf-8", errors="strict")
    assert "\ufffd" not in text
    ast.parse(text, filename=str(path))
sys.path.insert(0, str(source))
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
import app

application = QApplication([])
if application.platformName() == "offscreen":
    for name in ("segoeui.ttf", "seguisb.ttf", "malgun.ttf", "malgunbd.ttf"):
        QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name))
app.apply_application_style(application)
app.DATA = out / "격리설정"
with patch.object(app.MainWindow, "autostart_enabled", return_value=False), patch.object(app.QSystemTrayIcon, "show"):
    window = app.MainWindow()
window.timer.stop()
window.notifications.setChecked(False)
window.reveal.setChecked(False)
window.show()
application.processEvents()
window.drop_card.orbit.intro.setCurrentTime(220)
assert window.grab().save(str(out / "Studio-intro-middle.png"))
window.drop_card.orbit.intro.setCurrentTime(window.drop_card.orbit.intro.duration())
assert window.grab().save(str(out / "Studio-ko-home.png"))
window.set_language("en")
assert window.grab().save(str(out / "Studio-en-home.png"))
window.tabs.setCurrentIndex(4)
window.tabs.fade.setCurrentTime(window.tabs.fade.duration())
application.processEvents()
assert window.grab().save(str(out / "Studio-en-pdf.png"))
print(json.dumps({"size": [window.width(), window.height()], "minimum": [window.minimumWidth(), window.minimumHeight()], "captures": [path.name for path in out.glob("*.png")], "os_input": False}, ensure_ascii=False))
window.hide()
window.tray.hide()
window.pool.shutdown(wait=True)
window.pdf_panel.shutdown()
