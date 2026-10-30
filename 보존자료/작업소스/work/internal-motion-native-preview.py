"""운영 설정·자동 시작을 바꾸지 않고 내부 화면을 실제 Windows에서 살펴본다."""
from pathlib import Path
import sys
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "소스"))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
import app

application = QApplication([])
application.setQuitOnLastWindowClosed(False)
app.apply_application_style(application)
app.DATA = root / "work" / "internal-motion-native" / "격리설정"
app.DATA.mkdir(parents=True, exist_ok=True)
with patch.object(app.MainWindow, "autostart_enabled", return_value=False), patch.object(app.QSystemTrayIcon, "show"):
    window = app.MainWindow()
window.timer.stop()
window.notifications.setChecked(False)
window.reveal.setChecked(False)
window.setWindowTitle("FlipRing · 내부 모션 검사")
window.show()
QTimer.singleShot(600000, application.quit)
application.exec()
window.hide()
window.tray.hide()
window.pool.shutdown(wait=True)
window.pdf_panel.shutdown()
