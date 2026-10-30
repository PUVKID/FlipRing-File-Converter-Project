"""사용자 설정을 읽거나 바꾸지 않고 실제 앱 스타일로 PDF 패널을 렌더링한다."""
import json
from pathlib import Path
import sys
import time

ROOT = Path(r"D:\2026\FilpRing Project")
sys.path.insert(0, str(ROOT / "소스"))
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QMenu
from PySide6.QtTest import QTest
import app
from pdf_panel import PdfToolsPanel
from test_pdf_workspace import make_pdf

folder = Path(__file__).parent / "render-review"
folder.mkdir(exist_ok=True)
source = folder / "한글과 공백이 있는 긴 원본 PDF 페이지 편집.pdf"
make_pdf(source)
application = QApplication([])
app.apply_application_style(application)
host = QWidget()
host.tray_menu = QMenu(host)
app.MainWindow.apply_style(host)
layout = QVBoxLayout(host)
panel = PdfToolsPanel("ko", host)
layout.addWidget(panel)
host.resize(960, 680)
host.show()
panel.load_workspace(str(source))
deadline = time.monotonic() + 10
while (panel.is_busy() or panel._render_scheduled) and time.monotonic() < deadline:
    QTest.qWait(5)
report = []
for language, size in (("ko", (960, 680)), ("en", (960, 680)), ("ko", (1200, 820))):
    panel.set_language(language)
    host.resize(*size)
    QTest.qWait(25)
    assert (host.width(), host.height()) == size, (size, host.size())
    for button in (panel.open_pages_button, panel.save_pages_button, panel.cancel_pages_button):
        assert button.isVisible() and panel.rect().contains(button.mapTo(panel, button.rect().center()))
    filename = f"PDF-실제스타일-{language}-{size[0]}x{size[1]}.png"
    host.grab().save(str(folder / filename))
    report.append({"language": language, "requested_size": size, "actual_size": [host.width(), host.height()],
                   "source_card": [panel.sources_card.width(), panel.sources_card.height()],
                   "preview": [panel.page_preview.width(), panel.page_preview.height()],
                   "save_visible": panel.save_pages_button.isVisible(), "cancel_visible": panel.cancel_pages_button.isVisible(),
                   "font_family": panel.font().family(), "source_sha256": panel.workspace.source_sha256})
panel.open_page_preview()
QTest.qWait(30)
panel.preview_dialog.grab().save(str(folder / "PDF-확대창.png"))
panel.preview_dialog.close()
panel.shutdown(wait=True)
host.close()
(folder / "렌더검토.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False))
