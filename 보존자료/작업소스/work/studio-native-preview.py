"""분리된 설정으로 실제 Windows 작업 화면을 확인한다."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
setup = (root / "work" / "studio-preview.py").read_text(encoding="utf-8")
exec(compile(setup.split("window.drop_card.orbit.intro.setCurrentTime(220)")[0], str(root / "work" / "studio-preview.py"), "exec"))
from PySide6.QtCore import QTimer

window.setWindowTitle("FlipRing Studio · 디자인 검사")
QTimer.singleShot(600000, application.quit)
application.exec()
window.pool.shutdown(wait=True)
window.pdf_panel.shutdown()
