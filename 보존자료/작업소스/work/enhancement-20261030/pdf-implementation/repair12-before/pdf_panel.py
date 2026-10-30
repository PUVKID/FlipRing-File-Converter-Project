"""흑백 PDF/OCR 패널. 무거운 작업은 별도 스레드에서 로컬 처리한다."""
from __future__ import annotations

import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import uuid

from PySide6.QtCore import QObject, Signal, Slot, Qt, QCoreApplication, QPointF, QSize, QTimer, QMimeData, QSignalBlocker, QItemSelectionModel
from PySide6.QtGui import QPainter, QPen, QColor, QImage, QPixmap, QIcon, QDrag
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QListWidget, QFileDialog, QLineEdit, QSpinBox, QCheckBox, QProgressBar,
    QScrollArea, QFormLayout, QAbstractItemView, QStyleOptionSpinBox, QStyle, QAbstractSpinBox,
    QTabWidget, QListWidgetItem, QSplitter, QDialog,
)
import pdf_tools
from pdf_pages import PdfWorkspace
from studio_ui import StudioCard, Toggle
from ui_motion import make_file_dialog, install_surface_motions, pulse_widget, StateMark


TEXT = {
    "files": ("파일 · 위에서 아래 순서로 처리", "Files · Processed from top to bottom"),
    "add": ("추가", "Add"), "remove": ("빼기", "Remove"),
    "up": ("위로", "Up"), "down": ("아래로", "Down"),
    "operation": ("작업", "Operation"),
    "merge": ("PDF 합치기", "Merge PDFs"), "split": ("PDF 페이지별 분할", "Split PDF into pages"),
    "extract": ("페이지 추출", "Extract pages"), "delete": ("페이지 삭제", "Delete pages"),
    "rotate": ("페이지 회전", "Rotate pages"), "images_to_pdf": ("이미지 → PDF", "Images to PDF"),
    "pdf_to_images": ("PDF → 이미지", "PDF to images"), "compress": ("PDF 압축", "Compress PDF"),
    "recognize": ("문서·표 인식 / OCR", "Document / table recognition / OCR"),
    "pages": ("페이지", "Pages"), "range_hint": ("전체 또는 예: 1,3-5", "All, or e.g. 1,3-5"),
    "rotation": ("회전", "Rotation"), "compression": ("압축 방식", "Compression"),
    "lossless": ("무손실 정리", "Lossless cleanup"),
    "images": ("이미지 축소·재압축 (손실)", "Resize / recompress images (lossy)"),
    "quality": ("이미지 품질", "Image quality"), "dpi": ("해상도 (DPI)", "Resolution (DPI)"),
    "ocr_language": ("인식 언어", "Recognition language"),
    "bilingual": ("한국어 + 영어", "Korean + English"), "korean": ("한국어", "Korean"),
    "english": ("영어", "English"), "output": ("결과 형식", "Output format"),
    "searchable": ("검색 가능한 PDF", "Searchable PDF"),
    "text": ("텍스트 (TXT)", "Text (TXT)"), "word": ("Word 문서 (DOCX)", "Word document (DOCX)"),
    "excel": ("Excel 표 (XLSX)", "Excel table (XLSX)"),
    "layout": ("인식 배치", "Recognition layout"),
    "automatic": ("자동", "Automatic"), "block": ("단일 블록", "Single block"),
    "sparse": ("흩어진 글자", "Sparse text"),
    "force": ("텍스트가 있는 PDF도 OCR로 다시 읽기", "OCR PDFs even if they already contain text"),
    "start": ("실행", "Run"), "cancel": ("취소", "Cancel"),
    "ready": ("원본을 보존하고 같은 폴더에 새 파일로 저장합니다.", "Originals are kept. New files go in the same folder."),
    "working": ("처리 중 · {label}", "Processing · {label}"),
    "cancelling": ("취소 중 · 현재 페이지 처리를 정리합니다.", "Cancelling · Finishing the current page safely."),
    "done": ("완료 · {count}개 결과", "Done · {count} result(s)"),
    "cancelled": ("취소했습니다. 앞서 완성한 결과는 유지합니다.", "Cancelled. Previously completed results are kept."),
    "pick": ("PDF 또는 이미지 선택", "Choose PDFs or images"),
    "empty": ("먼저 파일을 추가해 주세요.", "Add files first."),
    "busy": ("다른 변환이 끝난 뒤 실행해 주세요.", "Wait for the other conversion to finish."),
    "note": ("로컬 처리 · OCR은 흐림·기울기·복잡한 표에서 오인식할 수 있습니다.\nWord/Excel은 좌표로 행·열을 추론하며 원본 배치나 병합 셀을 완벽히 복원하지 않습니다.",
             "Local processing · OCR can misread blur, skew and complex tables.\nWord/Excel infer rows and columns from positions; layout and merged cells may differ."),
    "lossy_note": ("이미지 축소·재압축은 화질을 낮춥니다. 무손실 정리는 크기 감소를 보장하지 않습니다.",
                   "Image resizing / recompression reduces quality. Lossless cleanup may not reduce file size."),
    "pdf_note": ("검색 PDF는 페이지를 이미지로 다시 만들고 인식된 텍스트 층을 추가합니다.",
                 "Searchable PDF rebuilds pages as images and adds a recognized text layer."),
    "file_tab": ("파일 작업", "File tools"), "editor_tab": ("페이지 편집", "Page editor"),
    "open_pages": ("PDF 열기", "Open PDF"), "close_pages": ("닫기", "Close"),
    "rotate_pages": ("선택 회전", "Rotate selection"), "delete_pages": ("선택 삭제", "Delete selection"),
    "extract_pages": ("선택 추출", "Extract selection"), "save_pages": ("새 PDF 저장", "Save new PDF"),
    "save_preset": ("현재 옵션을 프리셋으로 저장", "Save options as preset"),
    "editor_empty": ("PDF를 열어 페이지를 확인하고 편집하세요.", "Open a PDF to view and edit its pages."),
    "editor_hint": ("썸네일을 드래그해 순서 변경 · Ctrl/Shift로 다중 선택", "Drag thumbnails to reorder · Ctrl/Shift to select multiple pages"),
    "page_label": ("{number}쪽 · 원본 {source}쪽", "Page {number} · Source {source}"),
    "editor_count": ("{name} · {count}쪽 · {selected}쪽 선택", "{name} · {count} pages · {selected} selected"),
    "editor_ready": ("페이지 편집은 메모리에만 반영됩니다. 새 PDF로 저장하세요.", "Edits stay in memory. Save them as a new PDF."),
    "selection_empty": ("먼저 페이지를 선택해 주세요.", "Select pages first."),
    "preset_invalid": ("프리셋 옵션을 확인해 주세요.", "Check the preset options."),
    "view_page": ("크게 보기", "Enlarge"), "preview_title": ("페이지 미리보기", "Page preview"),
    "zoom_in": ("확대", "Zoom in"), "zoom_out": ("축소", "Zoom out"), "zoom_fit": ("창에 맞춤", "Fit to window"),
}

ERRORS = {
    "page_range": ("페이지 범위를 확인해 주세요. 예: 1,3-5. 삭제는 범위를 입력해야 합니다.", "Check the page range, e.g. 1,3-5. Deletion requires a range."),
    "empty_pdf": ("페이지가 없는 PDF입니다.", "The PDF has no pages."),
    "encrypted_pdf": ("암호화된 PDF는 지원하지 않습니다. 암호를 해제한 사본을 사용해 주세요.", "Encrypted PDFs are not supported. Use an unlocked copy."),
    "invalid_pdf": ("PDF를 읽을 수 없습니다.", "The PDF could not be read."),
    "all_pages_removed": ("모든 페이지를 삭제할 수는 없습니다.", "At least one page must remain."),
    "ocr_missing": ("동봉 OCR 실행 파일 또는 언어 모델이 없습니다. 배포 파일을 확인해 주세요.", "The bundled OCR runtime or language model is missing. Check the distribution files."),
    "ocr_timeout": ("페이지 OCR 제한 시간 3분을 초과했습니다.", "OCR exceeded the 3 minute limit for a page."),
    "ocr_failed": ("OCR 처리에 실패했습니다.", "OCR processing failed."),
    "ocr_language": ("지원하지 않는 인식 언어입니다.", "Unsupported recognition language."),
    "page_too_large": ("선택한 해상도에서 페이지가 너무 큽니다. DPI를 낮춰 주세요.", "The page is too large at this resolution. Lower the DPI."),
    "input_files": ("입력 파일을 확인해 주세요.", "Check the input files."),
    "quality": ("해상도 또는 품질 값을 확인해 주세요.", "Check the resolution and quality values."),
    "output_format": ("지원하지 않는 출력 형식입니다.", "Unsupported output format."),
    "rotation": ("회전 각도를 확인해 주세요.", "Check the rotation angle."),
    "compression": ("압축 방식을 확인해 주세요.", "Check the compression mode."),
    "operation": ("지원하지 않는 작업입니다.", "Unsupported operation."),
    "processing_failed": ("파일을 처리할 수 없습니다. 입력 파일과 저장 위치를 확인해 주세요.", "The file could not be processed. Check the input file and output location."),
    "ocr_layout": ("인식 배치 설정을 확인해 주세요.", "Check the recognition layout setting."),
    "output_name": ("새 출력 이름을 만들 수 없습니다.", "A new output filename could not be created."),
    "output_exists": ("원본 또는 기존 파일을 덮어쓸 수 없습니다. 새 이름을 선택해 주세요.", "The original or an existing file cannot be overwritten. Choose a new name."),
}


class _Bridge(QObject):
    progress = Signal(int, int, str)
    result = Signal(str, str, str)
    finished = Signal(object)


class OptionComboBox(QComboBox):
    """닫힌 옵션 위의 휠은 설정 변경 대신 부모 스크롤로 전달한다."""

    def wheelEvent(self, event):
        if self.view().isVisible():
            super().wheelEvent(event)
        else:
            event.ignore()


class OptionSpinBox(QSpinBox):
    """기본 증감 입력은 유지하고 평면 버튼에 화살표만 그린다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pdfNumeric")

    def wheelEvent(self, event):
        event.ignore()

    def paintEvent(self, event):
        super().paintEvent(event)
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        for control, flag, direction in ((QStyle.SC_SpinBoxUp, QAbstractSpinBox.StepEnabledFlag.StepUpEnabled, 1),
                                         (QStyle.SC_SpinBoxDown, QAbstractSpinBox.StepEnabledFlag.StepDownEnabled, -1)):
            rectangle = self.style().subControlRect(QStyle.CC_SpinBox, option, control, self)
            if rectangle.isEmpty():
                continue
            enabled = self.isEnabled() and bool(self.stepEnabled() & flag)
            painter.setPen(QPen(QColor("#757575" if enabled else "#bbbbbb"), 1.4,
                                Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            center = rectangle.center()
            tip = QPointF(center.x(), center.y() - direction * 1.5)
            painter.drawLine(QPointF(center.x() - 3, center.y() + direction * 1.5), tip)
            painter.drawLine(tip, QPointF(center.x() + 3, center.y() + direction * 1.5))
        painter.end()


class PagePreview(QLabel):
    """렌더링한 한 페이지를 창 크기에 맞추며 확대창에서는 더 크게 보여준다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.original = QPixmap()
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(120, 160)
        self.setStyleSheet("background:#f1f1f1;border:1px solid #e5e5e5;border-radius:8px;")

    def set_image(self, image):
        self.original = _pixmap(image)
        self._fit()

    def clear(self):
        self.original = QPixmap()
        super().clear()

    def _fit(self):
        if not self.original.isNull():
            self.setPixmap(self.original.scaled(self.size() - QSize(12, 12), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()


class PageList(QListWidget):
    """썸네일의 화면 좌표 이동 대신 명시적인 페이지 순서 변경을 전달한다."""
    order_changed = Signal()
    MIME = "application/x-flipring-pdf-pages"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_token = uuid.uuid4().hex

    def mimeData(self, items):
        mime = QMimeData()
        indices = sorted(self.row(item) for item in items)
        mime.setData(self.MIME, json.dumps({"token": self._drag_token,
                                          "pages": [self.item(index).data(Qt.UserRole) for index in indices]}).encode("utf-8"))
        return mime

    def _drag_pages(self, mime):
        if not mime.hasFormat(self.MIME):
            return None
        try:
            data = json.loads(bytes(mime.data(self.MIME)).decode("utf-8"))
            pages = data["pages"]
            available = {self.item(index).data(Qt.UserRole) for index in range(self.count())}
            if data["token"] != self._drag_token or not isinstance(pages, list) or not pages:
                return None
            if any(type(page) is not int or page not in available for page in pages) or len(set(pages)) != len(pages):
                return None
            return pages
        except (ValueError, TypeError, KeyError, UnicodeError):
            return None

    def startDrag(self, supported_actions):
        if not self.selectedItems():
            return
        drag = QDrag(self)
        drag.setMimeData(self.mimeData(self.selectedItems()))
        # 직접 이동을 소유하므로 Qt의 기본 원본 행 삭제와 중복하지 않는다.
        drag.exec(Qt.MoveAction)

    def dragEnterEvent(self, event):
        if self.isEnabled() and self._drag_pages(event.mimeData()) is not None:
            event.setDropAction(Qt.MoveAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)
        if event.isAccepted():
            self.scrollTo(self.indexAt(event.position().toPoint()))

    def dropEvent(self, event):
        pages = self._drag_pages(event.mimeData())
        if not self.isEnabled() or pages is None:
            event.ignore()
            return
        position = event.position().toPoint()
        target = self.itemAt(position)
        boundary = self.row(target) if target is not None else self.count()
        if target is not None and position.x() > self.visualItemRect(target).center().x():
            boundary += 1
        items = [self.item(index) for index in range(self.count())]
        moving = [item for item in items if item.data(Qt.UserRole) in pages]
        before = [item for item in items[:boundary] if item not in moving]
        after = [item for item in items[boundary:] if item not in moving]
        with QSignalBlocker(self):
            while self.count():
                self.takeItem(0)
            for item in before + moving + after:
                self.addItem(item)
                item.setSelected(item in moving)
            if moving:
                self.setCurrentItem(moving[0], QItemSelectionModel.NoUpdate)
        self.order_changed.emit()
        event.setDropAction(Qt.MoveAction)
        event.accept()


class EnlargedPreview(QDialog):
    """선택 페이지 한 장의 확대·축소만 담당하며 PDF 객체는 소유하지 않는다."""

    def __init__(self, pixmap, panel):
        super().__init__(panel)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(840, 760)
        self.raster = pixmap
        self.zoom_factor = 1.0
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.zoom_out_button = QPushButton()
        self.zoom_in_button = QPushButton()
        self.fit_button = QPushButton()
        self.close_button = QPushButton()
        for button in (self.zoom_out_button, self.zoom_in_button, self.fit_button, self.close_button):
            controls.addWidget(button)
        layout.addLayout(controls)
        self.scroll = QScrollArea()
        self.scroll.setAlignment(Qt.AlignCenter)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignCenter)
        self.scroll.setWidget(self.image)
        layout.addWidget(self.scroll, 1)
        self.zoom_out_button.clicked.connect(lambda: self.set_zoom(self.zoom_factor / 1.25))
        self.zoom_in_button.clicked.connect(lambda: self.set_zoom(self.zoom_factor * 1.25))
        self.fit_button.clicked.connect(self.fit)
        self.close_button.clicked.connect(self.close)
        self.set_language(panel)
        install_surface_motions(self)
        QTimer.singleShot(0, self.fit)

    def set_language(self, panel):
        self.setWindowTitle(panel.tr_text("preview_title"))
        for button, key in ((self.zoom_in_button, "zoom_in"), (self.zoom_out_button, "zoom_out"),
                            (self.fit_button, "zoom_fit"), (self.close_button, "close_pages")):
            button.setText(panel.tr_text(key))

    def set_zoom(self, factor):
        self.zoom_factor = max(0.1, min(4.0, factor))
        size = self.raster.size() * self.zoom_factor
        self.image.resize(size)
        self.image.setPixmap(self.raster.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def fit(self):
        if not self.raster.isNull():
            size = self.scroll.viewport().size() - QSize(16, 16)
            self.set_zoom(min(size.width() / self.raster.width(), size.height() / self.raster.height()))


def _pixmap(image):
    raster = image.convert("RGB")
    data = raster.tobytes()
    return QPixmap.fromImage(QImage(data, raster.width, raster.height, raster.width * 3, QImage.Format_RGB888).copy())


class PdfToolsPanel(QWidget):
    result_ready = Signal(str, str, str)
    activity_changed = Signal(str)
    preset_requested = Signal(dict)

    def __init__(self, language, parent=None):
        super().__init__(parent)
        self.language = "en" if language == "en" else "ko"
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="FlipRing-PDF")
        self._future = None
        # 브리지는 GUI 스레드에 남겨 두고 Python 작업 스레드는 신호만 보낸다.
        self._bridge = _Bridge(self)
        self._bridge.progress.connect(self._on_progress, Qt.QueuedConnection)
        self._bridge.result.connect(self._on_result, Qt.QueuedConnection)
        self._bridge.finished.connect(self._finish, Qt.QueuedConnection)
        application = QCoreApplication.instance()
        if application is not None:
            application.aboutToQuit.connect(self.shutdown)
        self._busy = False
        self._cancel = threading.Event()
        self._results = 0
        self._error = None
        self._status_key = "ready"
        self._status_values = {}
        self._labels = {}
        self.workspace = None
        self._workspace_job = None
        self._render_scheduled = False
        self._render_pending = False
        self._thumbnail_cache = OrderedDict()
        self._preview_key = None
        self._reduced_motion = False
        self._refreshing_pages = False
        self.preview_dialog = None
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(20)
        self.sources_card = StudioCard()
        self.sources_card.setMinimumWidth(280)
        outer.addWidget(self.sources_card, 1)
        source_outer = QVBoxLayout(self.sources_card)
        source_outer.setContentsMargins(12, 12, 12, 12)
        self.source_tabs = QTabWidget()
        source_outer.addWidget(self.source_tabs)
        file_host = QWidget()
        self.source_tabs.addTab(file_host, "")
        source_layout = QVBoxLayout(file_host)
        source_layout.setContentsMargins(22, 22, 22, 22)
        source_layout.setSpacing(16)
        self.files_label = QLabel()
        self.files_label.setObjectName("cardTitle")
        self.files_label.setWordWrap(True)
        source_layout.addWidget(self.files_label)
        self.files = QListWidget()
        self.files.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.files.setMinimumHeight(250)
        source_layout.addWidget(self.files, 1)
        row = QHBoxLayout()
        self.add_button = QPushButton()
        self.remove_button = QPushButton()
        self.up_button = QPushButton()
        self.down_button = QPushButton()
        for button in (self.add_button, self.remove_button, self.up_button, self.down_button):
            row.addWidget(button)
        self.add_button.clicked.connect(self.add_files)
        self.remove_button.clicked.connect(self.remove_files)
        self.up_button.clicked.connect(lambda: self.move_file(-1))
        self.down_button.clicked.connect(lambda: self.move_file(1))
        source_layout.addLayout(row)
        self._build_workspace()
        self.options_card = StudioCard()
        self.options_card.setMinimumWidth(320)
        outer.addWidget(self.options_card, 1)
        actions_layout = QVBoxLayout(self.options_card)
        actions_layout.setContentsMargins(22, 22, 22, 22)
        actions_layout.setSpacing(15)
        # 파일 조작과 실행·취소는 고정하고 긴 옵션만 안쪽에서 스크롤한다.
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        actions_layout.addWidget(self.scroll, 1)
        host = QWidget()
        self.scroll.setWidget(host)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(15)
        self.form = QFormLayout()
        self.form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        self.operation = OptionComboBox()
        for key in ("merge", "split", "extract", "delete", "rotate", "images_to_pdf", "pdf_to_images", "compress", "recognize"):
            self.operation.addItem(key, key)
        self._row("operation", self.operation)
        self.pages = QLineEdit()
        self._row("pages", self.pages)
        self.rotation = OptionComboBox()
        for angle in (90, 180, 270):
            self.rotation.addItem(f"{angle}°", angle)
        self._row("rotation", self.rotation)
        self.compression = OptionComboBox()
        for key in ("lossless", "images"):
            self.compression.addItem(key, key)
        self._row("compression", self.compression)
        self.quality = OptionSpinBox()
        self.quality.setRange(20, 95)
        self.quality.setValue(80)
        self._row("quality", self.quality)
        self.dpi = OptionSpinBox()
        self.dpi.setRange(60, 600)
        self.dpi.setValue(200)
        self.dpi.setSingleStep(25)
        self._row("dpi", self.dpi)
        self.ocr_language = OptionComboBox()
        for label, code in (("bilingual", "kor+eng"), ("korean", "kor"), ("english", "eng")):
            self.ocr_language.addItem(label, code)
        self._row("ocr_language", self.ocr_language)
        self.output = OptionComboBox()
        self._row("output", self.output)
        self.psm = OptionComboBox()
        for label, code in (("automatic", 3), ("block", 6), ("sparse", 11)):
            self.psm.addItem(label, code)
        self._row("layout", self.psm)
        layout.addLayout(self.form)
        self.force = Toggle()
        layout.addWidget(self.force)
        self.lossy_note = QLabel()
        self.lossy_note.setWordWrap(True)
        self.lossy_note.setObjectName("muted")
        layout.addWidget(self.lossy_note)
        self.pdf_note = QLabel()
        self.pdf_note.setWordWrap(True)
        self.pdf_note.setObjectName("muted")
        layout.addWidget(self.pdf_note)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setObjectName("muted")
        layout.addWidget(self.note)
        self.save_preset_button = QPushButton()
        self.save_preset_button.clicked.connect(self.request_preset)
        layout.addWidget(self.save_preset_button)
        layout.addStretch()
        row = QHBoxLayout()
        self.start_button = QPushButton()
        self.start_button.setProperty("primary", True)
        self.cancel_button = QPushButton()
        self.cancel_button.setEnabled(False)
        self.start_button.clicked.connect(self.start)
        self.cancel_button.clicked.connect(self.cancel)
        row.addWidget(self.start_button)
        row.addWidget(self.cancel_button)
        actions_layout.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.hide()
        actions_layout.addWidget(self.progress)
        self.status = QLabel()
        self.status.setWordWrap(True)
        status_row = QHBoxLayout()
        self.status_mark = StateMark()
        status_row.addWidget(self.status_mark)
        status_row.addWidget(self.status, 1)
        actions_layout.addLayout(status_row)
        self.operation.currentIndexChanged.connect(self._options_changed)
        self.compression.currentIndexChanged.connect(self._options_changed)
        self.output.currentIndexChanged.connect(self._notes_changed)
        self.set_language(self.language)
        self._options_changed()
        self.source_tabs.currentChanged.connect(self._editor_tab_changed)
        install_surface_motions(self)
        pulse_widget(self.status)

    def _row(self, key, widget):
        label = QLabel()
        self._labels[key] = (label, widget)
        self.form.addRow(label, widget)

    def tr_text(self, key, **values):
        return TEXT[key][self.language == "en"].format(**values)

    def set_language(self, language):
        self.language = "en" if language == "en" else "ko"
        for key, (label, _) in self._labels.items():
            label.setText(self.tr_text(key))
        self.files_label.setText(self.tr_text("files"))
        self.source_tabs.setTabText(0, self.tr_text("file_tab"))
        self.source_tabs.setTabText(1, self.tr_text("editor_tab"))
        for button, key in ((self.open_pages_button, "open_pages"), (self.close_pages_button, "close_pages"),
                            (self.rotate_pages_button, "rotate_pages"), (self.delete_pages_button, "delete_pages"),
                            (self.extract_pages_button, "extract_pages"), (self.save_pages_button, "save_pages"),
                            (self.save_preset_button, "save_preset")):
            button.setText(self.tr_text(key))
        self.editor_hint.setText(self.tr_text("editor_hint"))
        self.cancel_pages_button.setText(self.tr_text("cancel"))
        self.view_page_button.setText(self.tr_text("view_page"))
        if self.preview_dialog is not None:
            self.preview_dialog.set_language(self)
        self._refresh_page_labels()
        for button, key in ((self.add_button, "add"), (self.remove_button, "remove"),
                            (self.up_button, "up"), (self.down_button, "down"),
                            (self.start_button, "start"), (self.cancel_button, "cancel")):
            button.setText(self.tr_text(key))
        for index in range(self.operation.count()):
            self.operation.setItemText(index, self.tr_text(self.operation.itemData(index)))
        for index, key in enumerate(("lossless", "images")):
            self.compression.setItemText(index, self.tr_text(key))
        for index, key in enumerate(("bilingual", "korean", "english")):
            self.ocr_language.setItemText(index, self.tr_text(key))
        for index, key in enumerate(("automatic", "block", "sparse")):
            self.psm.setItemText(index, self.tr_text(key))
        self.pages.setPlaceholderText(self.tr_text("range_hint"))
        self.force.setText(self.tr_text("force"))
        self.note.setText(self.tr_text("note"))
        self.lossy_note.setText(self.tr_text("lossy_note"))
        self.pdf_note.setText(self.tr_text("pdf_note"))
        self._refresh_output_labels()
        self._render_status()

    def _refresh_output_labels(self):
        names = {"pdf": "searchable", "txt": "text", "docx": "word", "xlsx": "excel"}
        for index in range(self.output.count()):
            key = self.output.itemData(index)
            self.output.setItemText(index, self.tr_text(names[key]) if key in names else key.upper())

    def _options_changed(self):
        operation = self.operation.currentData()
        visible = {
            "pages": operation in {"split", "extract", "delete", "rotate", "pdf_to_images", "recognize"},
            "rotation": operation == "rotate", "compression": operation == "compress",
            "quality": operation == "pdf_to_images" or (operation == "compress" and self.compression.currentData() == "images"),
            "dpi": operation in {"images_to_pdf", "pdf_to_images", "recognize"} or (operation == "compress" and self.compression.currentData() == "images"),
            "ocr_language": operation == "recognize", "output": operation in {"pdf_to_images", "recognize"},
            "layout": operation == "recognize",
        }
        for key, show in visible.items():
            for widget in self._labels[key]:
                widget.setVisible(show)
        if operation != getattr(self, "_output_operation", None):
            self.output.blockSignals(True)
            self.output.clear()
            for key in (("pdf", "txt", "docx", "xlsx") if operation == "recognize" else ("png", "jpg")):
                self.output.addItem(key, key)
            self.output.blockSignals(False)
            self._output_operation = operation
        self._refresh_output_labels()
        self.force.setVisible(operation == "recognize")
        self.note.setVisible(operation == "recognize")
        self.lossy_note.setVisible(operation == "compress")
        self._notes_changed()
        pulse_widget(self.scroll.widget())

    def _notes_changed(self):
        self.pdf_note.setVisible(self.operation.currentData() == "recognize" and self.output.currentData() == "pdf")

    def add_files(self):
        dialog = self.file_dialog()
        try:
            if dialog.exec() == QFileDialog.Accepted:
                self.set_files(self.input_paths() + dialog.selectedFiles())
        finally:
            dialog.deleteLater()

    def file_dialog(self):
        return make_file_dialog(self, self.tr_text("pick"),
                                name_filter="PDF / Images (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp *.heic *.gif)")

    def input_paths(self):
        return [self.files.item(index).data(Qt.UserRole) for index in range(self.files.count())]

    def set_files(self, paths):
        if self._busy:
            return
        self.files.clear()
        for path in dict.fromkeys(map(str, paths)):
            self.files.addItem(Path(path).name)
            item = self.files.item(self.files.count() - 1)
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
        pulse_widget(self.files)

    def remove_files(self):
        if self._busy:
            return
        for item in self.files.selectedItems():
            self.files.takeItem(self.files.row(item))
        pulse_widget(self.files)

    def move_file(self, offset):
        if self._busy:
            return
        row = self.files.currentRow()
        if 0 <= row + offset < self.files.count() and row >= 0:
            item = self.files.takeItem(row)
            self.files.insertItem(row + offset, item)
            self.files.setCurrentRow(row + offset)
            self.files._flipring_surface_motion.selection_pulse()

    def is_busy(self):
        return self._busy

    def _set_busy(self, value):
        self._busy = value
        for widget in (self.files, self.add_button, self.remove_button, self.up_button, self.down_button,
                       self.operation, self.pages, self.rotation, self.compression, self.quality, self.dpi,
                       self.ocr_language, self.output, self.psm, self.force, self.start_button,
                       self.open_pages_button, self.save_preset_button):
            widget.setEnabled(not value)
        self._update_workspace_controls()
        self.cancel_button.setEnabled(value)
        self.progress.setVisible(value)
        self.cancel_pages_button.setEnabled(value)
        self.editor_progress.setVisible(value)
        self.editor_progress.setRange(self.progress.minimum(), self.progress.maximum())
        pulse_widget(self.options_card)
        self.activity_changed.emit(self.status_mark.state)

    def start(self):
        if self._busy or self._pool is None:
            return
        if getattr(self.window(), "pending", 0):
            self._set_status("busy")
            return
        paths = self.input_paths()
        if not paths:
            self._set_status("empty")
            return
        request = pdf_tools.Request(
            self.operation.currentData(), paths, self.pages.text(), self.rotation.currentData(),
            self.compression.currentData(), self.quality.value(), self.dpi.value(),
            self.ocr_language.currentData(), self.output.currentData() or "pdf", self.force.isChecked(), self.psm.currentData())
        self._cancel = threading.Event()
        self._results = 0
        self._error = None
        self.progress.setValue(0)
        self._set_busy(True)
        self._set_status("working", label=Path(paths[0]).name)
        bridge = self._bridge
        self._future = self._pool.submit(pdf_tools.execute, request, self._cancel,
                                         bridge.progress.emit, bridge.result.emit)
        self._future.add_done_callback(bridge.finished.emit)

    def cancel(self):
        if self._busy:
            self._cancel.set()
            self.cancel_button.setEnabled(False)
            self.cancel_pages_button.setEnabled(False)
            self._set_status("cancelling")

    @Slot(int, int, str)
    def _on_progress(self, done, total, label):
        if not self._cancel.is_set():
            self.progress.setValue(int(done * 100 / max(total, 1)))
            self.editor_progress.setRange(0, 100)
            self.editor_progress.setValue(int(done * 100 / max(total, 1)))
            self._set_status("working", label=label)

    @Slot(str, str, str)
    def _on_result(self, source, output, error):
        self._results += bool(output)
        self.result_ready.emit(source, output, error)

    @Slot(object)
    def _on_error(self, error):
        self._error = error
        self._render_status()
        if not isinstance(error, pdf_tools.Cancelled):
            self.result_ready.emit(getattr(error, "source", ""), "", self.error_text(error))

    def error_text(self, error):
        code = getattr(error, "code", "")
        if code == "cancelled":
            return self.tr_text("cancelled")
        base = ERRORS.get(code)
        return base[self.language == "en"] if base else str(error)

    def _set_status(self, key, **values):
        self._status_key, self._status_values = key, values
        self._render_status()

    def _render_status(self):
        self.status.setText(self.error_text(self._error) if self._error is not None else
                            self.tr_text(self._status_key, **self._status_values))
        self.editor_status.setText(self.status.text())
        state = ("cancelled" if isinstance(self._error, pdf_tools.Cancelled) else "error" if self._error is not None else
                 {"working": "working", "cancelling": "cancelling", "cancelled": "cancelled", "done": "complete",
                  "empty": "error", "busy": "working"}.get(self._status_key, "ready"))
        self.status_mark.respond(state)
        self.editor_status_mark.respond(state)
        pulse_widget(self.status)
        self.activity_changed.emit(state)

    @Slot(object)
    def _finish(self, future):
        if self._workspace_job is not None:
            self._finish_workspace(future)
            return
        # Future 완료 뒤에만 GUI 입력을 복구하므로 반복 실행과 종료 정리가 경합하지 않는다.
        try:
            future.result()
        except Exception as error:
            self._on_error(error)
        self._set_busy(False)
        if self._error is None:
            self._set_status("cancelled" if self._cancel.is_set() else "done", count=self._results)
        self._future = None

    def _build_workspace(self):
        host = QWidget()
        self.source_tabs.addTab(host, "")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        self.open_pages_button = QPushButton()
        self.close_pages_button = QPushButton()
        self.view_page_button = QPushButton()
        row = QHBoxLayout()
        row.addWidget(self.open_pages_button, 1)
        row.addWidget(self.view_page_button)
        row.addWidget(self.close_pages_button)
        layout.addLayout(row)
        self.open_pages_button.clicked.connect(self.choose_workspace)
        self.close_pages_button.clicked.connect(self.close_workspace)
        self.view_page_button.clicked.connect(self.open_page_preview)
        # 작은 창에서도 실행·취소는 고정하고 문서 보기 영역만 스크롤한다.
        self.editor_scroll = QScrollArea()
        self.editor_scroll.setWidgetResizable(True)
        self.editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        document_host = QWidget()
        self.editor_scroll.setWidget(document_host)
        body = QVBoxLayout(document_host)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)
        self.editor_summary = QLabel()
        self.editor_summary.setWordWrap(True)
        body.addWidget(self.editor_summary)
        self.editor_hint = QLabel()
        self.editor_hint.setObjectName("muted")
        self.editor_hint.setWordWrap(True)
        body.addWidget(self.editor_hint)
        splitter = QSplitter(Qt.Vertical)
        self.pages_list = PageList()
        self.pages_list.setViewMode(QListWidget.IconMode)
        self.pages_list.setResizeMode(QListWidget.Adjust)
        self.pages_list.setMovement(QListWidget.Snap)
        self.pages_list.setWrapping(True)
        self.pages_list.setIconSize(QSize(104, 140))
        self.pages_list.setGridSize(QSize(128, 174))
        self.pages_list.setSpacing(4)
        self.pages_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.pages_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.pages_list.setDefaultDropAction(Qt.MoveAction)
        self.pages_list.setMinimumHeight(185)
        splitter.addWidget(self.pages_list)
        self.page_preview = PagePreview()
        self.page_preview.setToolTip("")
        splitter.addWidget(self.page_preview)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        body.addWidget(splitter, 1)
        layout.addWidget(self.editor_scroll, 1)
        self.rotate_pages_button = QPushButton()
        self.delete_pages_button = QPushButton()
        self.extract_pages_button = QPushButton()
        self.save_pages_button = QPushButton()
        self.cancel_pages_button = QPushButton()
        self.cancel_pages_button.setEnabled(False)
        self.save_pages_button.setProperty("primary", True)
        for buttons in ((self.rotate_pages_button, self.delete_pages_button),
                        (self.extract_pages_button, self.save_pages_button, self.cancel_pages_button)):
            row = QHBoxLayout()
            for button in buttons:
                row.addWidget(button, 1)
            layout.addLayout(row)
        self.rotate_pages_button.clicked.connect(self.rotate_selected_pages)
        self.delete_pages_button.clicked.connect(self.delete_selected_pages)
        self.extract_pages_button.clicked.connect(lambda: self.choose_workspace_save(selected=True))
        self.save_pages_button.clicked.connect(lambda: self.choose_workspace_save())
        self.cancel_pages_button.clicked.connect(self.cancel)
        self.editor_progress = QProgressBar()
        self.editor_progress.setRange(0, 100)
        self.editor_progress.hide()
        layout.addWidget(self.editor_progress)
        self.editor_status = QLabel()
        self.editor_status.setWordWrap(True)
        self.editor_status.setObjectName("muted")
        self.editor_status_mark = StateMark()
        status_row = QHBoxLayout()
        status_row.addWidget(self.editor_status_mark)
        status_row.addWidget(self.editor_status, 1)
        layout.addLayout(status_row)
        self.pages_list.itemSelectionChanged.connect(self._page_selection_changed)
        self.pages_list.model().rowsMoved.connect(self._pages_reordered)
        self.pages_list.order_changed.connect(self._pages_reordered)
        self.pages_list.verticalScrollBar().valueChanged.connect(self._schedule_render)
        self.source_tabs.currentChanged.connect(self._schedule_render)
        self._update_workspace_controls()

    def _update_workspace_controls(self):
        ready = self.workspace is not None and not self._busy
        self.pages_list.setEnabled(ready)
        self.close_pages_button.setEnabled(ready)
        selected = bool(self.pages_list.selectedItems())
        for button in (self.rotate_pages_button, self.delete_pages_button, self.extract_pages_button):
            button.setEnabled(ready and selected)
        self.save_pages_button.setEnabled(ready)
        self.view_page_button.setEnabled(ready and not self.page_preview.original.isNull())

    def _editor_tab_changed(self, index):
        self.options_card.setVisible(index == 0)
        self._schedule_render()

    def open_page_preview(self):
        if self._busy or self.page_preview.original.isNull():
            return
        if self.preview_dialog is not None:
            self.preview_dialog.close()
        dialog = EnlargedPreview(self.page_preview.original, self)
        self.preview_dialog = dialog
        dialog.destroyed.connect(lambda: self._preview_closed(dialog))
        dialog.show()

    def _preview_closed(self, dialog):
        if self.preview_dialog is dialog:
            self.preview_dialog = None

    def selected_page_indices(self):
        return sorted(self.pages_list.row(item) for item in self.pages_list.selectedItems())

    def choose_workspace(self):
        dialog = make_file_dialog(self, self.tr_text("open_pages"), name_filter="PDF (*.pdf)")
        dialog.setFileMode(QFileDialog.ExistingFile)
        try:
            if dialog.exec() == QFileDialog.Accepted and dialog.selectedFiles():
                self.load_workspace(dialog.selectedFiles()[0])
        finally:
            dialog.deleteLater()

    def load_workspace(self, path):
        if not self._can_workspace_work():
            return False
        self.source_tabs.setCurrentIndex(1)
        return self._submit_workspace("load", lambda cancel, progress: PdfWorkspace.open(path, cancel=cancel))

    def close_workspace(self):
        if self._busy:
            return
        self.workspace = None
        if self.preview_dialog is not None:
            self.preview_dialog.close()
        self._thumbnail_cache.clear()
        self._preview_key = None
        self.pages_list.clear()
        self.page_preview.clear()
        self._refresh_page_labels()
        self._update_workspace_controls()
        self._error = None
        self._set_status("ready")

    def _can_workspace_work(self):
        if self._busy or self._pool is None:
            return False
        if getattr(self.window(), "pending", 0):
            self._error = None
            self._set_status("busy")
            return False
        return True

    def _submit_workspace(self, kind, work):
        if not self._can_workspace_work():
            return False
        self._workspace_job = kind
        self._cancel = threading.Event()
        self._results = 0
        if kind != "render":
            self._error = None
            self._set_status("working", label=self.tr_text("editor_tab"))
        self.progress.setRange(0, 0)
        self._set_busy(True)
        self._future = self._pool.submit(work, self._cancel, self._bridge.progress.emit)
        self._future.add_done_callback(self._bridge.finished.emit)
        return True

    def _refresh_page_labels(self):
        if self.workspace is None:
            self.editor_summary.setText(self.tr_text("editor_empty"))
            return
        for index, page in enumerate(self.workspace.pages):
            item = self.pages_list.item(index)
            if item is not None:
                item.setText(self.tr_text("page_label", number=index + 1, source=page.source_index + 1))
                item.setToolTip(item.text() + f" · +{page.rotation}°")
        self.editor_summary.setText(self.tr_text("editor_count", name=self.workspace.source.name,
                                               count=self.workspace.page_count, selected=len(self.selected_page_indices())))

    def _fill_pages(self, selected_sources=None):
        self._refreshing_pages = True
        try:
            self.pages_list.clear()
            for page in self.workspace.pages:
                item = QListWidgetItem()
                item.setData(Qt.UserRole, page.source_index)
                item.setFlags(item.flags() | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)
                self.pages_list.addItem(item)
                if selected_sources is not None and page.source_index in selected_sources:
                    item.setSelected(True)
            if selected_sources is None and self.pages_list.count():
                self.pages_list.setCurrentRow(0)
        finally:
            self._refreshing_pages = False
        self._preview_key = None
        self._refresh_page_labels()
        self._update_workspace_controls()
        self._schedule_render()

    def _page_selection_changed(self):
        if self._refreshing_pages:
            return
        self._refresh_page_labels()
        self._update_workspace_controls()
        self._schedule_render()

    def _pages_reordered(self, *unused):
        if self.workspace is None or self._refreshing_pages:
            return
        previous = {page.source_index: index for index, page in enumerate(self.workspace.pages)}
        order = [previous[self.pages_list.item(index).data(Qt.UserRole)] for index in range(self.pages_list.count())]
        self.workspace.reorder(order)
        self._refresh_page_labels()
        self._schedule_render()

    def rotate_selected_pages(self):
        self._edit_pages("rotate")

    def delete_selected_pages(self):
        self._edit_pages("delete")

    def _edit_pages(self, operation):
        if not self._can_workspace_work() or self.workspace is None:
            return
        indices = self.selected_page_indices()
        if not indices:
            self._error = None
            self._set_status("selection_empty")
            return
        selected_sources = {self.workspace.pages[index].source_index for index in indices}
        try:
            getattr(self.workspace, operation)(indices)
        except pdf_tools.PdfToolError as error:
            self._error = error
            self._render_status()
            return
        self._error = None
        self._set_status("editor_ready")
        self._fill_pages(selected_sources if operation == "rotate" else None)
        pulse_widget(self.pages_list)

    def choose_workspace_save(self, *, selected=False):
        if not self._can_workspace_work() or self.workspace is None:
            return
        label = "extract_pages" if selected else "save_pages"
        default = self.workspace.source.with_name(self.workspace.source.stem + ("-extracted.pdf" if selected else "-edited.pdf"))
        path, _ = QFileDialog.getSaveFileName(self, self.tr_text(label), str(default), "PDF (*.pdf)",
                                            options=QFileDialog.DontUseNativeDialog | QFileDialog.DontConfirmOverwrite)
        if path:
            self.save_workspace(path, selected=selected)

    def save_workspace(self, path=None, *, selected=False):
        if not self._can_workspace_work() or self.workspace is None:
            return False
        indices = self.selected_page_indices() if selected else None
        if selected and not indices:
            self._error = None
            self._set_status("selection_empty")
            return False
        workspace = self.workspace
        return self._submit_workspace("save", lambda cancel, progress: workspace.save(path, selected=indices,
                                                                                     cancel=cancel, progress=progress))

    def _schedule_render(self, *unused):
        if self._refreshing_pages or self.workspace is None or self._pool is None:
            return
        if self._busy:
            self._render_pending = True
            return
        if not self._render_scheduled:
            self._render_scheduled = True
            QTimer.singleShot(0, self._render_workspace)

    def _render_workspace(self):
        self._render_scheduled = False
        if self.workspace is None or self._pool is None or self.source_tabs.currentIndex() != 1:
            return
        if self._busy or getattr(self.window(), "pending", 0):
            self._render_pending = True
            return
        workspace = self.workspace
        visible = [index for index in range(self.pages_list.count())
                   if self.pages_list.visualItemRect(self.pages_list.item(index)).intersects(self.pages_list.viewport().rect())]
        current = self.pages_list.currentRow()
        if not 0 <= current < workspace.page_count:
            current = self.selected_page_indices()[0] if self.selected_page_indices() else 0
        wanted = list(dict.fromkeys([current] + visible))[:12]
        missing = []
        for index in wanted:
            page = workspace.pages[index]
            key = (page.source_index, page.rotation)
            if key in self._thumbnail_cache:
                self.pages_list.item(index).setIcon(self._thumbnail_cache[key])
                self._thumbnail_cache.move_to_end(key)
            else:
                missing.append((index, key))
        page = workspace.pages[current]
        preview_key = (page.source_index, page.rotation)
        needs_preview = preview_key != self._preview_key
        if not missing and not needs_preview:
            return

        def render(cancel, progress):
            images = [(key, workspace.render(index, 140, cancel=cancel)) for index, key in missing]
            preview = workspace.render(current, 1100, cancel=cancel) if needs_preview else None
            return images, preview_key, preview

        self._submit_workspace("render", render)

    def _finish_workspace(self, future):
        kind = self._workspace_job
        self._workspace_job = None
        self._future = None
        completed = False
        try:
            value = future.result()
            if self._cancel.is_set() and kind != "save":
                raise pdf_tools.Cancelled()
            if kind == "load":
                self.workspace = value
                self._thumbnail_cache.clear()
                self.page_preview.clear()
            elif kind == "save":
                self._results = 1
                self.result_ready.emit(str(self.workspace.source), str(value), "")
            elif kind == "render":
                images, preview_key, preview = value
                for key, image in images:
                    self._thumbnail_cache[key] = QIcon(_pixmap(image))
                while len(self._thumbnail_cache) > 48:
                    key, _ = self._thumbnail_cache.popitem(last=False)
                    for index, page in enumerate(self.workspace.pages):
                        if (page.source_index, page.rotation) == key:
                            self.pages_list.item(index).setIcon(QIcon())
                if preview is not None:
                    self.page_preview.set_image(preview)
                    if self.preview_dialog is not None:
                        self.preview_dialog.raster = self.page_preview.original
                        self.preview_dialog.fit()
                    self._preview_key = preview_key
                for index, page in enumerate(self.workspace.pages):
                    icon = self._thumbnail_cache.get((page.source_index, page.rotation))
                    if icon is not None:
                        self.pages_list.item(index).setIcon(icon)
            completed = True
        except Exception as error:
            self._error = error
            self._render_status()
            if not isinstance(error, pdf_tools.Cancelled) and kind == "save":
                self.result_ready.emit(str(self.workspace.source), "", self.error_text(error))
        finally:
            self.progress.setRange(0, 100)
            self._set_busy(False)
        if completed and kind == "load":
            self._fill_pages()
            self._set_status("editor_ready")
        elif completed and kind == "save":
            self._set_status("done", count=1)
        pending = self._render_pending
        self._render_pending = False
        if completed and (kind == "load" or pending):
            self._schedule_render()

    def snapshot_options(self):
        return {"operation": self.operation.currentData(), "pages": self.pages.text(),
                "rotation": self.rotation.currentData(), "compression": self.compression.currentData(),
                "quality": self.quality.value(), "dpi": self.dpi.value(),
                "ocr_language": self.ocr_language.currentData(), "output_format": self.output.currentData() or "pdf",
                "force_ocr": self.force.isChecked(), "psm": self.psm.currentData()}

    def request_preset(self):
        if not self._busy:
            self.preset_requested.emit({"kind": "pdf", "format": "pdf", "options": self.snapshot_options()})

    def apply_preset(self, options):
        if self._busy or not isinstance(options, dict):
            return False
        defaults = vars(pdf_tools.Request("merge", [])).copy()
        defaults.pop("paths")
        if set(options) - set(defaults):
            return False
        values = defaults | options
        integer_rules = {"rotation": {90, 180, 270}, "quality": range(20, 96), "dpi": range(60, 601), "psm": {3, 6, 11}}
        valid = all(isinstance(values[key], str) for key in ("operation", "compression", "ocr_language", "output_format"))
        valid = valid and all(type(values[key]) is int and values[key] in allowed for key, allowed in integer_rules.items())
        valid = valid and values["operation"] in pdf_tools.OPERATIONS and values["compression"] in {"lossless", "images"}
        valid = valid and values["ocr_language"] in {"kor+eng", "kor", "eng"} and type(values["force_ocr"]) is bool
        valid = valid and isinstance(values["pages"], str) and len(values["pages"]) <= 10000
        if valid and values["pages"].strip():
            valid = bool(re.fullmatch(r"\s*[1-9][0-9]*(?:\s*-\s*[1-9][0-9]*)?(?:\s*,\s*[1-9][0-9]*(?:\s*-\s*[1-9][0-9]*)?)*\s*", values["pages"]))
        allowed_outputs = {"pdf", "txt", "docx", "xlsx"} if values["operation"] == "recognize" else {"png", "jpg"} if values["operation"] == "pdf_to_images" else {"pdf", "txt", "docx", "xlsx", "png", "jpg"}
        valid = valid and values["output_format"] in allowed_outputs
        if not valid:
            self._error = None
            self._set_status("preset_invalid")
            return False
        self.operation.setCurrentIndex(self.operation.findData(values["operation"]))
        for widget, key in ((self.rotation, "rotation"), (self.compression, "compression"),
                            (self.ocr_language, "ocr_language"), (self.psm, "psm"), (self.output, "output_format")):
            index = widget.findData(values[key])
            if index >= 0:
                widget.setCurrentIndex(index)
        self.pages.setText(values["pages"])
        self.quality.setValue(values["quality"])
        self.dpi.setValue(values["dpi"])
        self.force.setChecked(values["force_ocr"])
        self.source_tabs.setCurrentIndex(0)
        return True

    def set_reduced_motion(self, enabled):
        from ui_motion import set_reduced_motion
        self._reduced_motion = bool(enabled)
        set_reduced_motion(self, self._reduced_motion)

    @Slot()
    def shutdown(self, *, wait=False):
        if self._busy:
            return False
        if self._pool is not None:
            self._pool.shutdown(wait=wait, cancel_futures=True)
            self._pool = None
        return True
