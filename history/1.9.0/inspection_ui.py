"""OCR 교정·동일 페이지 비교·검토 후보·사용자 영역 가림 창."""
from __future__ import annotations

from pathlib import Path
import threading

from PySide6.QtCore import Qt, QThread, Signal, Slot, QRectF, QSize, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (QDialog, QWidget, QLabel, QPushButton, QVBoxLayout,
                               QHBoxLayout, QComboBox, QLineEdit, QPlainTextEdit,
                               QScrollArea, QListWidget, QListWidgetItem, QSpinBox,
                               QProgressBar, QFileDialog, QSplitter)

import inspection_tools as tools
from pdf_tools import Cancelled, PdfToolError, check_cancel
from fixed_viewport import fit_window
from ui_motion import make_file_dialog, install_surface_motions, set_reduced_motion


class _Job(QThread):
    completed = Signal(object)
    failed = Signal(object)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation
        self.cancel = threading.Event()

    def run(self):
        try:
            self.completed.emit(self.operation(self.cancel))
        except Exception as error:
            self.failed.emit(error)


class PageCanvas(QWidget):
    """표시 좌표를 원본의 정규화 좌표로 변환하며 선택만 표시한다."""
    rectangle_added = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = QImage()
        self.zoom = 100
        self.regions = []
        self.words = []
        self.highlight = None
        self.drawing = False
        self.anchor = None
        self.cursor_position = None
        self.placeholder = ''
        self.setMinimumSize(320, 350)
        self.setFocusPolicy(Qt.StrongFocus)

    def set_image(self, image):
        if image is None:
            self.image = QImage()
        else:
            converted = image.convert('RGBA')
            self.image = QImage(converted.tobytes(), converted.width, converted.height,
                                converted.width * 4, QImage.Format_RGBA8888).copy()
        self.set_zoom(self.zoom)

    def set_zoom(self, zoom):
        self.zoom = zoom
        # 양쪽 캔버스에 같은 절대 배율을 적용하며 작은 화면은 스크롤로 탐색한다.
        size = QSize(max(320, round(self.image.width() * zoom / 100)),
                     max(350, round(self.image.height() * zoom / 100)))
        self.setMinimumSize(size)
        self.resize(size)
        self.update()

    def set_draw_enabled(self, enabled):
        self.drawing = enabled
        self.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)

    def image_rect(self):
        width, height = self.image.width() * self.zoom / 100, self.image.height() * self.zoom / 100
        return QRectF(max(0, (self.width() - width) / 2), max(0, (self.height() - height) / 2), width, height)

    def _box(self, rect):
        bounds = self.image_rect()
        return QRectF(bounds.x() + rect[0] * bounds.width(), bounds.y() + rect[1] * bounds.height(),
                      rect[2] * bounds.width(), rect[3] * bounds.height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#e9e9e9'))
        if self.image.isNull():
            painter.setPen(QColor('#666666'))
            painter.drawText(self.rect().adjusted(20, 20, -20, -20), Qt.AlignCenter | Qt.TextWordWrap, self.placeholder)
            return
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawImage(self.image_rect(), self.image)
        for word in self.words:
            if word['confidence'] is not None and word['confidence'] < 70:
                painter.setPen(QPen(QColor('#555555'), 1, Qt.DashLine))
                painter.drawRect(self._box(word['rect']))
        for rect in self.regions:
            painter.fillRect(self._box(rect), QColor(0, 0, 0, 155))
            painter.setPen(QPen(QColor('#000000'), 2))
            painter.drawRect(self._box(rect))
        if self.highlight:
            painter.setPen(QPen(QColor('#222222'), 3, Qt.DashLine))
            painter.drawRect(self._box(self.highlight))
        if self.anchor is not None and self.cursor_position is not None:
            painter.setPen(QPen(QColor('#000000'), 2, Qt.DashLine))
            painter.drawRect(QRectF(self.anchor, self.cursor_position).normalized())

    def mousePressEvent(self, event):
        if self.drawing and not self.image.isNull() and event.button() == Qt.LeftButton and self.image_rect().contains(event.position()):
            self.anchor = event.position()
            self.cursor_position = self.anchor
            self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.anchor is not None:
            self.cursor_position = event.position()
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.anchor is not None and event.button() == Qt.LeftButton:
            chosen = QRectF(self.anchor, event.position()).normalized().intersected(self.image_rect())
            bounds = self.image_rect()
            if chosen.width() >= 2 and chosen.height() >= 2:
                self.rectangle_added.emit([(chosen.x() - bounds.x()) / bounds.width(),
                                           (chosen.y() - bounds.y()) / bounds.height(),
                                           chosen.width() / bounds.width(), chosen.height() / bounds.height()])
            self.anchor = self.cursor_position = None
            self.update()
        super().mouseReleaseEvent(event)


class InspectionDialog(QDialog):
    result_ready = Signal(str, str, str)

    def __init__(self, parent=None, language='ko', paths=None, mode='ocr'):
        super().__init__(parent)
        self.language = 'en' if language == 'en' else 'ko'
        self.paths = list(dict.fromkeys(str(p) for p in (paths or [])))
        self.mode = mode if mode in {'ocr', 'compare', 'audit', 'redact'} else 'ocr'
        self.rectangles = []
        self.recognized = None
        self.findings = []
        self._last_infos = []
        self.job = None
        self._closing = False
        self._gate_owner = None
        self._source_at_start = ''
        self._action = ''
        self.setObjectName('inspectionDialog')
        self.setModal(True)
        self.setMaximumSize(1160, 820)
        self.setStyleSheet('''
            QDialog#inspectionDialog {background:#f8f8f8;}
            QDialog#inspectionDialog QWidget {font-family:'SUIT';font-size:13px;color:#292929;}
            QDialog#inspectionDialog QLabel#inspectionHeading {font-size:25px;font-weight:600;}
            QDialog#inspectionDialog QLabel#inspectionHint {color:#686868;}
            QDialog#inspectionDialog QPushButton {background:white;border:1px solid #d6d6d6;border-radius:8px;padding:9px 13px;min-height:18px;}
            QDialog#inspectionDialog QPushButton:focus {border:2px solid #333333;}
            QDialog#inspectionDialog QPushButton[primary="true"] {background:#262626;color:white;}
            QDialog#inspectionDialog QPushButton:disabled {color:#999999;background:#eeeeee;}
            QDialog#inspectionDialog QLineEdit,QDialog#inspectionDialog QComboBox,QDialog#inspectionDialog QSpinBox {background:white;border:1px solid #d6d6d6;border-radius:7px;padding:7px;min-height:18px;}
            QDialog#inspectionDialog QPlainTextEdit,QDialog#inspectionDialog QListWidget {background:white;border:1px solid #d6d6d6;border-radius:8px;padding:7px;}
            QDialog#inspectionDialog QListWidget::item:selected {background:#dddddd;color:#111111;}
            QDialog#inspectionDialog QProgressBar {border:0;background:#e6e6e6;height:4px;}
            QDialog#inspectionDialog QProgressBar::chunk {background:#555555;}
        ''')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        body = QWidget()
        body.setMinimumWidth(700)
        content = QVBoxLayout(body)
        content.setSpacing(12)
        self.heading = QLabel()
        self.heading.setObjectName('inspectionHeading')
        content.addWidget(self.heading)
        self.hint = QLabel()
        self.hint.setObjectName('inspectionHint')
        self.hint.setWordWrap(True)
        content.addWidget(self.hint)
        inputs = QHBoxLayout()
        self.mode_combo = QComboBox()
        for value in ('ocr', 'compare', 'audit', 'redact'):
            self.mode_combo.addItem(value, value)
        self.mode_combo.setCurrentIndex(('ocr', 'compare', 'audit', 'redact').index(self.mode))
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        inputs.addWidget(self.mode_combo)
        self.source_combo = QComboBox()
        self.source_combo.setMinimumWidth(180)
        self.source_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.source_combo.currentIndexChanged.connect(self._source_changed)
        inputs.addWidget(self.source_combo, 1)
        self.second_combo = QComboBox()
        self.second_combo.setMinimumWidth(160)
        self.second_combo.currentIndexChanged.connect(self._comparison_source_changed)
        inputs.addWidget(self.second_combo, 1)
        self.add_button = QPushButton()
        self.add_button.clicked.connect(self._choose_files)
        inputs.addWidget(self.add_button)
        content.addLayout(inputs)
        controls = QHBoxLayout()
        self.page_label = QLabel()
        controls.addWidget(self.page_label)
        self.page_spin = QSpinBox()
        self.page_spin.setRange(1, 1)
        self.page_spin.valueChanged.connect(self._schedule_preview)
        controls.addWidget(self.page_spin)
        self.zoom_label = QLabel()
        controls.addWidget(self.zoom_label)
        self.zoom_spin = QSpinBox()
        self.zoom_spin.setRange(20, 200)
        self.zoom_spin.setSingleStep(10)
        self.zoom_spin.setValue(50)
        self.zoom_spin.setSuffix('%')
        self.zoom_spin.valueChanged.connect(self._zoom_changed)
        controls.addWidget(self.zoom_spin)
        self.ocr_language = QComboBox()
        for label, code in (('한국어 + English', 'kor+eng'), ('한국어', 'kor'), ('English', 'eng')):
            self.ocr_language.addItem(label, code)
        controls.addWidget(self.ocr_language)
        self.clear_button = QPushButton()
        self.clear_button.clicked.connect(self._clear_regions)
        controls.addWidget(self.clear_button)
        controls.addStretch()
        self.run_button = QPushButton()
        self.run_button.setProperty('primary', True)
        self.run_button.clicked.connect(self._run)
        controls.addWidget(self.run_button)
        content.addLayout(controls)
        self.splitter = QSplitter(Qt.Horizontal)
        self.left_canvas, self.right_canvas = PageCanvas(), PageCanvas()
        self.left_canvas.rectangle_added.connect(self._add_region)
        self.canvas_scrolls = []
        for picture in (self.left_canvas, self.right_canvas):
            wrapper = QScrollArea()
            wrapper.setWidgetResizable(True)
            wrapper.setWidget(picture)
            self.canvas_scrolls.append(wrapper)
            self.splitter.addWidget(wrapper)
        # 양쪽 스크롤도 함께 이동해 같은 위치를 비교한다.
        for axis in ('horizontalScrollBar', 'verticalScrollBar'):
            first, second = (getattr(s, axis)() for s in self.canvas_scrolls)
            first.valueChanged.connect(second.setValue)
            second.valueChanged.connect(first.setValue)
        self.editor = QPlainTextEdit()
        self.editor.setMinimumWidth(280)
        self.splitter.addWidget(self.editor)
        self.splitter.setMinimumHeight(320)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 1)
        content.addWidget(self.splitter, 1)
        self.metadata = QLabel()
        self.metadata.setWordWrap(True)
        self.metadata.setTextInteractionFlags(Qt.TextSelectableByMouse)
        content.addWidget(self.metadata)
        self.candidate_list = QListWidget()
        self.candidate_list.setMinimumHeight(110)
        self.candidate_list.setMaximumHeight(165)
        self.candidate_list.currentItemChanged.connect(self._select_finding)
        content.addWidget(self.candidate_list)
        self.region_fields = []
        regions = QHBoxLayout()
        self.region_label = QLabel()
        regions.addWidget(self.region_label)
        for value in ('0.1', '0.1', '0.3', '0.1'):
            edit = QLineEdit(value)
            edit.setMaximumWidth(75)
            self.region_fields.append(edit)
            regions.addWidget(edit)
        self.add_region_button = QPushButton()
        self.add_region_button.clicked.connect(self._add_region_fields)
        regions.addWidget(self.add_region_button)
        self.update_region_button = QPushButton()
        self.update_region_button.clicked.connect(self._update_region_fields)
        regions.addWidget(self.update_region_button)
        self.remove_region_button = QPushButton()
        self.remove_region_button.clicked.connect(self._remove_region)
        regions.addWidget(self.remove_region_button)
        regions.addStretch()
        self.region_widget = QWidget()
        self.region_widget.setLayout(regions)
        content.addWidget(self.region_widget)
        outputs = QHBoxLayout()
        self.output_label = QLabel()
        outputs.addWidget(self.output_label)
        self.output_edit = QLineEdit(str(Path(self.paths[0]).parent) if self.paths else '')
        outputs.addWidget(self.output_edit, 1)
        self.folder_button = QPushButton()
        self.folder_button.clicked.connect(self._choose_folder)
        outputs.addWidget(self.folder_button)
        self.format_combo = QComboBox()
        self.format_combo.addItems(['TXT', 'PDF', 'DOCX', 'XLSX'])
        outputs.addWidget(self.format_combo)
        self.export_button = QPushButton()
        self.export_button.clicked.connect(self._export)
        outputs.addWidget(self.export_button)
        content.addLayout(outputs)
        self.scroll.setWidget(body)
        layout.addWidget(self.scroll, 1)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        layout.addWidget(self.progress)
        footer = QHBoxLayout()
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        footer.addWidget(self.status, 1)
        self.cancel_button = QPushButton()
        self.cancel_button.clicked.connect(self._cancel)
        footer.addWidget(self.cancel_button)
        self.close_button = QPushButton()
        self.close_button.clicked.connect(self.reject)
        footer.addWidget(self.close_button)
        layout.addLayout(footer)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self._load_preview)
        self._populate_paths()
        self._zoom_changed(self.zoom_spin.value())
        self.set_language(self.language)
        install_surface_motions(self)
        fit_window(self, QSize(1100, 790))
        if self.paths:
            self.preview_timer.start(0)

    def _tr(self, ko, en):
        return en if self.language == 'en' else ko

    def set_language(self, language):
        self.language = 'en' if language == 'en' else 'ko'
        titles = [('OCR 교정', 'OCR correction'), ('파일 비교', 'File comparison'),
                  ('결과 검사', 'Result inspection'), ('영역 가림', 'Redact regions')]
        for index, (ko, en) in enumerate(titles):
            self.mode_combo.setItemText(index, self._tr(ko, en))
        self.setWindowTitle('FlipRing · ' + self._tr(*titles[self.mode_combo.currentIndex()]))
        self.heading.setText(self._tr(*titles[self.mode_combo.currentIndex()]))
        self.hint.setText(self._tr('원본은 보존합니다. OCR·개인정보·품질은 검토 후보이며 완전한 탐지를 보장하지 않습니다. 가림은 직접 지정한 영역만 새 파일의 실제 픽셀에 적용합니다.',
                                   'Originals are preserved. OCR, privacy and quality findings need review and may be incomplete. Redaction changes pixels in a new copy only for regions you select.'))
        for widget, ko, en in ((self.add_button, '파일 추가', 'Add files'), (self.page_label, '페이지', 'Page'),
                               (self.zoom_label, '동일 배율', 'Shared zoom'), (self.clear_button, '영역 전체 지우기', 'Clear regions'),
                               (self.output_label, '새 결과 폴더', 'New output folder'), (self.folder_button, '폴더 선택', 'Choose folder'),
                               (self.export_button, '교정본 저장', 'Export edited text'), (self.cancel_button, '작업 취소', 'Cancel task'),
                               (self.close_button, '닫기', 'Close'), (self.region_label, '정규화 x / y / 폭 / 높이', 'Normalized x / y / width / height'),
                               (self.add_region_button, '영역 추가', 'Add region'), (self.update_region_button, '선택 수정', 'Update selected'),
                               (self.remove_region_button, '선택 삭제', 'Remove selected')):
            widget.setText(self._tr(ko, en))
        actions = {'ocr': ('문자 인식', 'Recognize text'), 'compare': ('두 파일 비교', 'Compare files'),
                   'audit': ('후보 검사', 'Inspect candidates'), 'redact': ('가린 복사본 저장', 'Save redacted copy')}
        self.run_button.setText(self._tr(*actions[self.mode]))
        self.editor.setPlaceholderText(self._tr('두 파일을 선택한 다음 비교를 실행하세요.', 'Select two files, then run comparison.') if self.mode == 'compare' else
                                       self._tr('문자 인식 후 직접 교정하세요. 파일의 내용은 번역하지 않습니다.',
                                                'Recognize text, then edit it here. File content is not translated.'))
        for canvas_widget in (self.left_canvas, self.right_canvas):
            canvas_widget.placeholder = self._tr('파일을 추가하고 페이지를 선택하세요.', 'Add a file and select a page.')
            canvas_widget.update()
        self._set_mode_visibility()
        self._refresh_candidates()
        if self._last_infos:
            self._show_info(self._last_infos)
        if not self.is_busy():
            self.status.setText(self._tr('대기 · 원본 보존 · 새 이름 저장', 'Ready · Originals preserved · New file names'))

    def set_reduced_motion(self, enabled):
        set_reduced_motion(self, enabled)

    def _set_mode_visibility(self):
        self.second_combo.setVisible(self.mode == 'compare')
        self.canvas_scrolls[1].setVisible(self.mode == 'compare')
        self.editor.setVisible(self.mode in {'ocr', 'compare'})
        self.editor.setReadOnly(self.mode == 'compare')
        self.ocr_language.setVisible(self.mode == 'ocr')
        for widget in (self.clear_button, self.region_widget):
            widget.setVisible(self.mode == 'redact')
        for widget in (self.format_combo, self.export_button):
            widget.setVisible(self.mode == 'ocr')
        self.left_canvas.set_draw_enabled(self.mode == 'redact' and not self.is_busy())

    def _populate_paths(self):
        for combo in (self.source_combo, self.second_combo):
            combo.blockSignals(True)
            current = combo.currentData()
            combo.clear()
            for path in self.paths:
                combo.addItem(Path(path).name, path)
                combo.setItemData(combo.count() - 1, path, Qt.ToolTipRole)
            combo.setCurrentIndex(max(0, combo.findData(current)))
            combo.blockSignals(False)
        if len(self.paths) > 1 and self.second_combo.currentIndex() == self.source_combo.currentIndex():
            self.second_combo.setCurrentIndex(1)

    def _mode_changed(self):
        self.mode = self.mode_combo.currentData()
        self.set_language(self.language)
        self._schedule_preview()

    def _source_changed(self):
        self.rectangles.clear()
        self.recognized = None
        self.findings = []
        self.editor.clear()
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(1)
        self.page_spin.blockSignals(False)
        self._refresh_candidates()
        self._schedule_preview()

    def _comparison_source_changed(self, *unused):
        if self.mode == 'compare':
            # 이전 두 파일의 차이를 새 선택 결과로 보여 주지 않는다.
            self.editor.clear()
            self.status.setText(self._tr('선택이 바뀌었습니다. 두 파일 비교를 실행하세요.',
                                         'Selection changed. Run comparison for these two files.'))
        self._schedule_preview()

    def _choose_files(self):
        dialog = make_file_dialog(self, 'pick_files_title', name_filter='PDF / Images (*.pdf *.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.gif *.heic *.avif)')
        try:
            if dialog.exec() == QFileDialog.Accepted:
                self.paths = list(dict.fromkeys(self.paths + dialog.selectedFiles()))
                self._populate_paths()
                if not self.output_edit.text() and self.paths:
                    self.output_edit.setText(str(Path(self.paths[0]).parent))
                self._schedule_preview()
        finally:
            dialog.deleteLater()

    def _choose_folder(self):
        dialog = make_file_dialog(self, 'pick_folder_title', folder=True)
        try:
            if dialog.exec() == QFileDialog.Accepted and dialog.selectedFiles():
                self.output_edit.setText(dialog.selectedFiles()[0])
        finally:
            dialog.deleteLater()

    def _zoom_changed(self, value):
        for picture in (self.left_canvas, self.right_canvas):
            picture.set_zoom(value)

    def _schedule_preview(self, *unused):
        if hasattr(self, 'preview_timer') and not self.is_busy():
            self.preview_timer.start(100)

    def _load_preview(self):
        source = self.source_combo.currentData()
        if not source or self.is_busy():
            return
        other = self.second_combo.currentData() if self.mode == 'compare' else None
        page = self.page_spin.value() - 1
        def operation(cancel):
            infos, images = [], []
            for path in (source, other):
                check_cancel(cancel)
                if path:
                    info = tools._info(path, cancel)
                    infos.append(info)
                    images.append(tools.render_page(path, page) if page < info['page_count'] else None)
                else:
                    images.append(None)
            return {'infos': infos, 'images': images}
        self._start(operation, 'preview')

    def _run(self):
        source, other = self.source_combo.currentData(), self.second_combo.currentData()
        output = self.output_edit.text()
        language, regions = self.ocr_language.currentData(), [dict(page=r['page'], rect=list(r['rect'])) for r in self.rectangles]
        if not source:
            self.status.setText(self._tr('먼저 파일을 추가하세요.', 'Add a file first.'))
            return
        mode = self.mode
        def operation(cancel):
            if mode == 'ocr':
                return tools.recognize_editable(source, language, cancel)
            if mode == 'compare':
                if not other:
                    raise PdfToolError('input_files')
                return tools.compare_files(source, other, cancel)
            if mode == 'audit':
                return tools.audit_file(source, cancel)
            return tools.redact_file(source, regions, output, cancel)
        self._start(operation, mode)

    def _export(self):
        source = self.source_combo.currentData()
        if not source:
            self.status.setText(self._tr('파일을 선택하세요.', 'Select a file.'))
            return
        text, output, name, format_name = self.editor.toPlainText(), self.output_edit.text(), Path(source).stem, self.format_combo.currentText().lower()
        def operation(cancel):
            check_cancel(cancel)
            return tools.export_edited_text(text, output, name, format_name)
        self._start(operation, 'export')

    def _start(self, operation, action):
        if self.is_busy():
            return False
        self.preview_timer.stop()
        self._source_at_start = self.source_combo.currentData() or ''
        self._action = action
        owner = self.parentWidget()
        if owner is not None and type(getattr(owner, 'pending', None)) is int:
            owner.pending += 1
            self._gate_owner = owner
        self.job = _Job(operation, self)
        self.job.completed.connect(self._completed)
        self.job.failed.connect(self._failed)
        self.job.finished.connect(self._finished)
        self._set_busy(True)
        self.status.setText(self._tr('처리 중 · 실제 작업이 끝나면 결과를 표시합니다.', 'Working · Results appear after processing finishes.'))
        self.job.start()
        return True

    def _set_busy(self, busy):
        for widget in (self.mode_combo, self.source_combo, self.second_combo, self.add_button,
                       self.page_spin, self.ocr_language, self.run_button, self.export_button,
                       self.output_edit, self.folder_button, self.clear_button, self.region_widget,
                       self.candidate_list):
            widget.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.progress.setRange(0, 0 if busy else 1)
        self.progress.setVisible(busy)
        self.left_canvas.set_draw_enabled(self.mode == 'redact' and not busy)

    @Slot(object)
    def _completed(self, result):
        if self._action == 'preview':
            for picture, image in zip((self.left_canvas, self.right_canvas), result['images']):
                picture.set_image(image)
            count = max((i['page_count'] for i in result['infos']), default=1)
            self.page_spin.blockSignals(True)
            self.page_spin.setMaximum(count)
            self.page_spin.blockSignals(False)
            self._show_info(result['infos'])
            self._update_overlays()
            if self.mode == 'compare':
                self.status.setText(self._tr('미리보기 준비 · 두 파일 비교를 실행하세요.',
                                             'Preview ready · Run comparison for these two files.'))
                return
        elif self._action == 'ocr':
            self.recognized = result
            self.editor.setPlainText(result['text'])
            self.findings = [{'kind': 'confidence', 'page': w['page'], 'rect': w['rect'],
                              'score': w['confidence'], 'text': w['text']} for w in result['words'] if w['confidence'] < 70]
            self._refresh_candidates()
            self._update_overlays()
        elif self._action == 'compare':
            self.editor.setPlainText(result['text_diff'] or self._tr('추출 텍스트가 같습니다.', 'Extracted text is identical.'))
            self._show_info([result['left'], result['right']])
        elif self._action == 'audit':
            self.findings = result
            self._refresh_candidates()
        else:
            self.result_ready.emit(self._source_at_start, str(result), '')
            self.status.setText(self._tr('새 파일 저장: ', 'New file saved: ') + str(result))
            return
        self.status.setText(self._tr('완료 · 원본을 보존했습니다.', 'Complete · Original preserved.'))

    def _show_info(self, infos):
        self._last_infos = infos
        rows = []
        index = self.page_spin.value() - 1
        for info in infos:
            page = next((p for p in info['pages'] if p['page'] == index), None)
            size = (f"{page['width']:g} × {page['height']:g} {page['unit']}" if page else
                    self._tr('이 번호의 페이지 없음', 'No page at this number'))
            rows.append(f"{Path(info['path']).name} · {info['bytes']:,} " + self._tr('바이트', 'bytes') + f" · {info['page_count']} " +
                        self._tr('페이지', 'pages') + ' · ' + size)
        self.metadata.setText('\n'.join(rows))

    @Slot(object)
    def _failed(self, error):
        if isinstance(error, Cancelled):
            message = self._tr('취소됨 · 원본과 완료한 결과는 보존합니다.', 'Cancelled · Originals and completed results are preserved.')
        elif isinstance(error, PdfToolError):
            labels = {'input_files': ('파일이 없거나 읽을 수 없습니다.', 'The file is missing or unreadable.'),
                      'redaction_rect': ('가릴 영역을 확인하세요. 페이지와 0~1 좌표가 필요합니다.', 'Check redaction regions, page numbers and coordinates from 0 to 1.'),
                      'output_write': ('실제 출력 폴더와 쓰기 권한을 확인하세요.', 'Check the output folder and write access.'),
                      'encrypted_pdf': ('암호화 PDF는 지원하지 않습니다.', 'Encrypted PDFs are unsupported.'),
                      'invalid_pdf': ('손상된 PDF를 읽을 수 없습니다.', 'Cannot read the damaged PDF.'),
                      'ocr_missing': ('로컬 OCR 도구 또는 모델이 없습니다.', 'The local OCR tool or language model is missing.')}
            message = self._tr(*labels.get(error.code, ('처리에 실패했습니다.', 'Processing failed.'))) + f' [{error.code}]'
        else:
            message = self._tr('처리에 실패했습니다: ', 'Processing failed: ') + str(error)
        self.status.setText(message)
        if self._action in {'redact', 'export'} and not isinstance(error, Cancelled):
            self.result_ready.emit(self._source_at_start, '', message)

    @Slot()
    def _finished(self):
        job = self.job
        self.job = None
        if self._gate_owner is not None:
            self._gate_owner.pending -= 1
            self._gate_owner = None
        self._set_busy(False)
        if job is not None:
            job.deleteLater()
        if self._closing:
            self.close()

    def _cancel(self):
        if self.job is not None:
            self.job.cancel.set()
            self.cancel_button.setEnabled(False)
            self.status.setText(self._tr('취소 요청 · 현재 작업 정리를 기다립니다.', 'Cancellation requested · Waiting for cleanup.'))

    def is_busy(self):
        return self.job is not None

    def shutdown(self):
        self.preview_timer.stop()
        self._cancel()
        return not self.is_busy()

    def reject(self):
        if self.is_busy():
            self._closing = True
            self._cancel()
            return
        self.preview_timer.stop()
        super().reject()

    def closeEvent(self, event):
        self.preview_timer.stop()
        if self.is_busy():
            self._closing = True
            self._cancel()
            event.ignore()
            return
        super().closeEvent(event)

    def _add_region(self, rect):
        if not self.is_busy():
            self.rectangles.append({'page': self.page_spin.value() - 1, 'rect': list(rect)})
            self._refresh_candidates()
            self._update_overlays()

    def _add_region_fields(self):
        try:
            rect = [float(field.text()) for field in self.region_fields]
            tools._rectangles([{'page': 0, 'rect': rect}], 1)
        except (ValueError, PdfToolError):
            self.status.setText(self._tr('영역은 0~1 좌표이며 폭·높이가 양수여야 합니다.', 'Use coordinates from 0 to 1 with positive width and height.'))
            return
        self._add_region(rect)

    def _clear_regions(self):
        self.rectangles.clear()
        self._refresh_candidates()
        self._update_overlays()

    def _update_region_fields(self):
        index = self.candidate_list.currentRow()
        if not 0 <= index < len(self.rectangles) or self.is_busy():
            self.status.setText(self._tr('수정할 영역을 목록에서 선택하세요.', 'Select a region from the list to update.'))
            return
        try:
            rect = [float(field.text()) for field in self.region_fields]
            tools._rectangles([{'page': 0, 'rect': rect}], 1)
        except (ValueError, PdfToolError):
            self.status.setText(self._tr('0~1 좌표와 양수 폭·높이를 확인하세요.', 'Check coordinates from 0 to 1 and positive dimensions.'))
            return
        self.rectangles[index]['rect'] = rect
        self._refresh_candidates()
        self.candidate_list.setCurrentRow(index)
        self._update_overlays()

    def _remove_region(self):
        index = self.candidate_list.currentRow()
        if 0 <= index < len(self.rectangles) and not self.is_busy():
            self.rectangles.pop(index)
            self.left_canvas.highlight = None
            self._refresh_candidates()
            self._update_overlays()

    def _update_overlays(self):
        page = self.page_spin.value() - 1
        self.left_canvas.regions = [r['rect'] for r in self.rectangles if r['page'] == page]
        self.left_canvas.words = [w for w in (self.recognized or {}).get('words', []) if w['page'] == page]
        self.left_canvas.update()

    def _refresh_candidates(self):
        self.candidate_list.clear()
        values = self.rectangles if self.mode == 'redact' else self.findings
        names = {'blank': ('빈 페이지 후보', 'Blank page candidate'), 'duplicate': ('중복 페이지 후보', 'Duplicate page candidate'),
                 'blur': ('흐림 후보', 'Blur candidate'), 'edge': ('가장자리 잘림 후보', 'Edge content candidate'),
                 'email': ('이메일 후보', 'Email candidate'), 'phone': ('전화번호 후보', 'Phone candidate'),
                 'confidence': ('OCR 낮은 확신도', 'Low OCR confidence')}
        for value in values:
            label = self._tr('직접 지정한 가림 영역', 'User selected redaction region') if self.mode == 'redact' else self._tr(*names.get(value['kind'], ('검토 후보', 'Review candidate')))
            text = f"{value['page'] + 1} · {label}"
            if value.get('text'):
                text += f" · {value['text']} · {value['score']:.1f}%"
            elif 'score' in value:
                text += f" · {value['score']:.3g}"
            if 'rect' in value:
                text += ' · [' + ', '.join(f'{n:.3f}' for n in value['rect']) + ']'
            if 'duplicate_of' in value:
                text += f" → {value['duplicate_of'] + 1}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, value)
            self.candidate_list.addItem(item)
        if not values:
            self.candidate_list.addItem(self._tr('검토 후보 없음 · 완전한 탐지를 의미하지 않습니다.', 'No review candidates · This does not imply complete detection.'))

    def _select_finding(self, current, previous):
        value = current.data(Qt.UserRole) if current else None
        if not isinstance(value, dict):
            return
        if self.page_spin.value() != value['page'] + 1:
            self.page_spin.setValue(value['page'] + 1)
        self.left_canvas.highlight = value.get('rect')
        if self.mode == 'redact' and 'rect' in value:
            for field, number in zip(self.region_fields, value['rect']):
                field.setText(f'{number:.8g}')
        self.left_canvas.update()
