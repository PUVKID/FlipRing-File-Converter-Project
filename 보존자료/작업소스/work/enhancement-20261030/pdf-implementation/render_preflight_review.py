"""설정을 바꾸지 않는 호스트에서 사전 점검의 한영 성공·실패 표면을 렌더링한다."""
import hashlib
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(r"D:\2026\FilpRing Project")
sys.path.insert(0, str(ROOT / "소스"))
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QMenu
from PySide6.QtTest import QTest
import app
import pdf_tools
from pdf_panel import PdfToolsPanel
from test_pdf_workspace import make_pdf

folder = Path(__file__).parent / "repair14-render"
folder.mkdir(exist_ok=True)
source = folder / "사전 점검 한글 원본.pdf"
make_pdf(source)
before = hashlib.sha256(source.read_bytes()).hexdigest()
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
report = []


def wait():
    deadline = time.monotonic() + 10
    while (panel.is_busy() or panel._render_scheduled) and time.monotonic() < deadline:
        QTest.qWait(5)
    assert not panel.is_busy()


def capture(name, language, size=(960, 680)):
    panel.set_language(language)
    host.resize(*size)
    QTest.qWait(25)
    assert (host.width(), host.height()) == size
    assert panel.cancel_pages_button.isVisible() if panel.source_tabs.currentIndex() == 1 else panel.cancel_button.isVisible()
    host.grab().save(str(folder / (name + ".png")))
    report.append({"name": name, "language": language, "size": size, "status": panel.status.text(),
                   "preflight": panel.preflight_label.text(), "busy": panel.is_busy()})


results = []
panel.result_ready.connect(lambda *values: results.append(values))
panel.set_files([str(source)])
panel.start()
wait()
assert results and Path(results[0][1]).is_file()
completed = Path(results[0][1])
completed_before = completed.read_bytes()
capture("PDF-실행사전점검-한국어", "ko")
capture("PDF-실행사전점검-영어", "en")
with patch.object(pdf_tools.shutil, "disk_usage", return_value=SimpleNamespace(free=0)):
    panel.start()
    assert not panel.is_busy()
capture("PDF-공간부족차단-한국어", "ko")
capture("PDF-공간부족차단-영어", "en")
panel.load_workspace(str(source))
wait()
target = folder / "생성되면 안 되는 PDF.pdf"
with patch.object(pdf_tools.shutil, "disk_usage", return_value=SimpleNamespace(free=0)):
    panel.save_workspace(str(target))
    assert not panel.is_busy() and not target.exists()
capture("PDF-편집저장공간부족-한국어", "ko")
capture("PDF-편집저장공간부족-영어", "en")
capture("PDF-편집저장공간부족-큰창", "ko", (1200, 820))
with patch.object(pdf_tools.tempfile, "TemporaryFile", side_effect=PermissionError("controlled write refusal")):
    panel.save_workspace(str(target))
    assert not panel.is_busy() and not target.exists()
capture("PDF-편집저장쓰기거부-한국어", "ko")
capture("PDF-편집저장쓰기거부-영어", "en")
assert hashlib.sha256(source.read_bytes()).hexdigest() == before
assert completed.read_bytes() == completed_before
assert len(results) == 1
panel.shutdown(wait=True)
host.close()
(folder / "사전점검-렌더검증.json").write_text(json.dumps({"captures": report, "source_preserved": True,
                                                       "completed_preserved": True, "blocked_output_created": False},
                                                      ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"captures": len(report), "source_preserved": True, "completed_preserved": True}, ensure_ascii=False))
