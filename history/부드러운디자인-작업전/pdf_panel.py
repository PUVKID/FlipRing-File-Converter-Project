"""흑백 PDF/OCR 패널. 무거운 작업은 별도 스레드에서 로컬 처리한다."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot, Qt, QCoreApplication
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QListWidget, QFileDialog, QLineEdit, QSpinBox, QCheckBox, QProgressBar,
    QScrollArea, QFormLayout, QAbstractItemView,
)
import pdf_tools


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
}


class _Bridge(QObject):
    progress = Signal(int, int, str)
    result = Signal(str, str, str)
    finished = Signal(object)


class PdfToolsPanel(QWidget):
    result_ready = Signal(str, str, str)

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
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self.scroll)
        host = QWidget()
        self.scroll.setWidget(host)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(9)
        self.files_label = QLabel()
        layout.addWidget(self.files_label)
        self.files = QListWidget()
        self.files.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.files.setMinimumHeight(90)
        self.files.setMaximumHeight(140)
        layout.addWidget(self.files)
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
        layout.addLayout(row)
        self.form = QFormLayout()
        self.form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.operation = QComboBox()
        for key in ("merge", "split", "extract", "delete", "rotate", "images_to_pdf", "pdf_to_images", "compress", "recognize"):
            self.operation.addItem(key, key)
        self._row("operation", self.operation)
        self.pages = QLineEdit()
        self._row("pages", self.pages)
        self.rotation = QComboBox()
        for angle in (90, 180, 270):
            self.rotation.addItem(f"{angle}°", angle)
        self._row("rotation", self.rotation)
        self.compression = QComboBox()
        for key in ("lossless", "images"):
            self.compression.addItem(key, key)
        self._row("compression", self.compression)
        self.quality = QSpinBox()
        self.quality.setRange(20, 95)
        self.quality.setValue(80)
        self._row("quality", self.quality)
        self.dpi = QSpinBox()
        self.dpi.setRange(60, 600)
        self.dpi.setValue(200)
        self.dpi.setSingleStep(25)
        self._row("dpi", self.dpi)
        self.ocr_language = QComboBox()
        for label, code in (("bilingual", "kor+eng"), ("korean", "kor"), ("english", "eng")):
            self.ocr_language.addItem(label, code)
        self._row("ocr_language", self.ocr_language)
        self.output = QComboBox()
        self._row("output", self.output)
        self.psm = QComboBox()
        for label, code in (("automatic", 3), ("block", 6), ("sparse", 11)):
            self.psm.addItem(label, code)
        self._row("layout", self.psm)
        layout.addLayout(self.form)
        self.force = QCheckBox()
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
        row = QHBoxLayout()
        self.start_button = QPushButton()
        self.cancel_button = QPushButton()
        self.cancel_button.setEnabled(False)
        self.start_button.clicked.connect(self.start)
        self.cancel_button.clicked.connect(self.cancel)
        row.addWidget(self.start_button)
        row.addWidget(self.cancel_button)
        layout.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch()
        self.operation.currentIndexChanged.connect(self._options_changed)
        self.compression.currentIndexChanged.connect(self._options_changed)
        self.output.currentIndexChanged.connect(self._notes_changed)
        self.set_language(self.language)
        self._options_changed()

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

    def _notes_changed(self):
        self.pdf_note.setVisible(self.operation.currentData() == "recognize" and self.output.currentData() == "pdf")

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, self.tr_text("pick"), "",
                                               "PDF / Images (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp *.heic *.gif)",
                                               options=QFileDialog.DontUseNativeDialog)
        self.set_files(self.input_paths() + paths)

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

    def remove_files(self):
        for item in self.files.selectedItems():
            self.files.takeItem(self.files.row(item))

    def move_file(self, offset):
        row = self.files.currentRow()
        if 0 <= row + offset < self.files.count() and row >= 0:
            item = self.files.takeItem(row)
            self.files.insertItem(row + offset, item)
            self.files.setCurrentRow(row + offset)

    def is_busy(self):
        return self._busy

    def _set_busy(self, value):
        self._busy = value
        for widget in (self.files, self.add_button, self.remove_button, self.up_button, self.down_button,
                       self.operation, self.pages, self.rotation, self.compression, self.quality, self.dpi,
                       self.ocr_language, self.output, self.psm, self.force, self.start_button):
            widget.setEnabled(not value)
        self.cancel_button.setEnabled(value)
        self.progress.setVisible(value)

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
            self._set_status("cancelling")

    @Slot(int, int, str)
    def _on_progress(self, done, total, label):
        if not self._cancel.is_set():
            self.progress.setValue(int(done * 100 / max(total, 1)))
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

    @Slot(object)
    def _finish(self, future):
        # Future 완료 뒤에만 GUI 입력을 복구하므로 반복 실행과 종료 정리가 경합하지 않는다.
        try:
            future.result()
        except Exception as error:
            self._on_error(error)
        self._set_busy(False)
        if self._error is None:
            self._set_status("cancelled" if self._cancel.is_set() else "done", count=self._results)
        self._future = None

    @Slot()
    def shutdown(self, *, wait=False):
        if self._busy:
            return False
        if self._pool is not None:
            self._pool.shutdown(wait=wait, cancel_futures=True)
            self._pool = None
        return True
