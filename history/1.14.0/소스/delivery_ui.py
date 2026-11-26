"""로컬 전용 호환·선택 메타데이터·문서 전후 비교 대화상자."""
from pathlib import Path
import json
import threading

from PySide6.QtCore import Qt, QThread, Signal, QSize
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QComboBox, QLineEdit, QListWidget, QListWidgetItem,
                               QPlainTextEdit, QFileDialog, QSpinBox, QSplitter, QScrollArea,
                               QGridLayout, QTabWidget, QWidget)
import delivery_tools as tools
import engine
from inspection_ui import PageCanvas
from pdf_tools import Cancelled
from ui_motion import make_file_dialog, install_surface_motions, set_reduced_motion
from theme_manager import manager
from fixed_viewport import fit_window


class _Job(QThread):
    completed = Signal(object)
    failed = Signal(object)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation, self.cancel = operation, threading.Event()

    def run(self):
        try:
            self.completed.emit(self.operation(self.cancel))
        except Exception as error:
            self.failed.emit(error)


class DeliveryDialog(QDialog):
    result_ready = Signal(str, str, str)

    def __init__(self, parent=None, language='ko', paths=None):
        super().__init__(parent)
        self.language, self.job, self._closing = language, None, False
        self._gate_owner, self._action, self._source_at_start = None, '', ''
        self.resize(900, 760)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(16)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        row = QHBoxLayout()
        self.source_combo, self.second_combo, self.target_combo = QComboBox(), QComboBox(), QComboBox()
        self.add_button = QPushButton()
        self.source_label = QLabel()
        layout.addWidget(self.source_label)
        row.addWidget(self.source_combo, 1)
        row.addWidget(self.add_button)
        layout.addLayout(row)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setStyleSheet("QTabWidget::pane {border:0;} QTabBar::tab {padding:10px 18px;border:0;border-bottom:2px solid transparent;} QTabBar::tab:selected {border-bottom-color:#242424;}")
        layout.addWidget(self.tabs, 2)
        self.compatibility_page, self.privacy_page, self.compare_page = QWidget(), QWidget(), QWidget()
        for page in (self.compatibility_page, self.privacy_page, self.compare_page):
            self.tabs.addTab(page, '')
        compatibility = QVBoxLayout(self.compatibility_page)
        compatibility.setContentsMargins(0, 16, 0, 0)
        compatibility.setSpacing(12)
        self.compatibility_button, self.metadata_button = QPushButton(), QPushButton()
        self.strip_button, self.compare_button, self.cancel_button = QPushButton(), QPushButton(), QPushButton()
        self.target_label = QLabel()
        compatibility.addWidget(self.target_label)
        compatibility.addWidget(self.target_combo)
        compatibility.addWidget(self.compatibility_button)
        compatibility.addStretch()
        privacy = QVBoxLayout(self.privacy_page)
        privacy.setContentsMargins(0, 16, 0, 0)
        privacy.setSpacing(12)
        privacy.addWidget(self.metadata_button)
        self.metadata_list = QListWidget()
        privacy.addWidget(self.metadata_list, 1)
        options = QHBoxLayout()
        self.output_edit, self.folder_button = QLineEdit(), QPushButton()
        options.addWidget(self.output_edit, 1)
        options.addWidget(self.folder_button)
        privacy.addLayout(options)
        privacy.addWidget(self.strip_button)
        compare = QVBoxLayout(self.compare_page)
        compare.setContentsMargins(0, 16, 0, 0)
        compare.setSpacing(12)
        compare_options = QHBoxLayout()
        self.page_spin = QSpinBox()
        self.page_spin.setRange(1, 1)
        # NoButtons는 상속된 Qt 스타일에서 편집 영역을 1px로 만들 수 있어 영역만 명시한다.
        self.page_spin.setStyleSheet('QSpinBox::up-button,QSpinBox::down-button {width:0px;height:0px;}')
        self.page_spin.setFixedWidth(90)
        self.previous_page_button, self.next_page_button = QPushButton('−'), QPushButton('+')
        for button in (self.previous_page_button, self.next_page_button):
            button.setFixedWidth(38)
        self.previous_page_button.clicked.connect(self.page_spin.stepDown)
        self.next_page_button.clicked.connect(self.page_spin.stepUp)
        self.page_spin.valueChanged.connect(self._sync_page_buttons)
        self.second_label = QLabel()
        compare.addWidget(self.second_label)
        compare_options.addWidget(self.second_combo, 1)
        compare_options.addWidget(self.previous_page_button)
        compare_options.addWidget(self.page_spin)
        compare_options.addWidget(self.next_page_button)
        compare.addLayout(compare_options)
        compare.addWidget(self.compare_button)
        split = QSplitter()
        self.left_canvas, self.right_canvas = PageCanvas(), PageCanvas()
        self.left_label, self.right_label = QLabel(), QLabel()
        for canvas, label in zip((self.left_canvas, self.right_canvas), (self.left_label, self.right_label)):
            panel = QWidget()
            column = QVBoxLayout(panel)
            column.setContentsMargins(0, 0, 0, 0)
            column.addWidget(label)
            scroll = QScrollArea()
            scroll.setWidget(canvas)
            column.addWidget(scroll, 1)
            split.addWidget(panel)
        compare.addWidget(split, 1)
        layout.addWidget(self.notice)
        self.details, self.status = QPlainTextEdit(), QLabel()
        self.details.setReadOnly(True)
        self.status.setWordWrap(True)
        layout.addWidget(self.details, 1)
        footer = QHBoxLayout()
        footer.addWidget(self.status, 1)
        footer.addWidget(self.cancel_button)
        layout.addLayout(footer)
        self._tab_results = {}
        self._active_tab = 0
        self._root_layout = layout
        self.tabs.currentChanged.connect(self._tab_changed)
        self._paths = []
        self.add_paths(paths or [])
        self.add_button.clicked.connect(self._choose_files)
        self.folder_button.clicked.connect(self._choose_folder)
        self.source_combo.currentIndexChanged.connect(self._source_changed)
        self.second_combo.currentIndexChanged.connect(self._invalidate_compare)
        self.compatibility_button.clicked.connect(self._compatibility)
        self.metadata_button.clicked.connect(self._metadata)
        self.strip_button.clicked.connect(self._strip)
        self.compare_button.clicked.connect(self._compare)
        self.cancel_button.clicked.connect(self._cancel)
        self._source_changed()
        self.set_language(language)
        self._set_busy(False)
        self._tab_changed(0)
        install_surface_motions(self)
        manager()._style(self)
        fit_window(self, QSize(900, 760))

    def _tr(self, ko, en):
        return ko if self.language == 'ko' else en

    def set_language(self, language):
        self.language = language
        self.setWindowTitle(self._tr('파일 완성도 도구', 'File delivery tools'))
        for index, (ko, en) in enumerate((('호환 안내', 'Compatibility'), ('개인정보', 'Privacy'), ('전후 비교', 'Compare'))):
            self.tabs.setTabText(index, self._tr(ko, en))
        for label, ko, en in ((self.source_label, '원본 파일', 'Source file'),
                              (self.target_label, '출력 형식', 'Output format'),
                              (self.second_label, '비교할 파일', 'Comparison file'),
                              (self.left_label, '원본', 'Original'),
                              (self.right_label, '비교 파일', 'Comparison')):
            label.setText(self._tr(ko, en))
        self.source_combo.setPlaceholderText(self._tr('파일을 선택하세요', 'Choose a file'))
        self.second_combo.setPlaceholderText(self._tr('비교할 파일을 선택하세요', 'Choose a comparison file'))
        self.target_combo.setPlaceholderText(self._tr('출력 형식을 선택하세요', 'Choose an output format'))
        self.target_combo.setAccessibleName(self._tr('출력 형식', 'Output format'))
        self.details.setPlaceholderText(self._tr('검사 결과가 여기에 표시됩니다.', 'Inspection results appear here.'))
        self.left_canvas.placeholder = self._tr('파일을 선택한 뒤 비교를 실행하세요.', 'Choose files, then run comparison.')
        self.right_canvas.placeholder = self._tr('비교 결과가 여기에 표시됩니다.', 'Comparison appears here.')
        self.left_canvas.update()
        self.right_canvas.update()
        self.previous_page_button.setToolTip(self._tr('이전 페이지', 'Previous page'))
        self.next_page_button.setToolTip(self._tr('다음 페이지', 'Next page'))
        self.previous_page_button.setAccessibleName(self.previous_page_button.toolTip())
        self.next_page_button.setAccessibleName(self.next_page_button.toolTip())
        self.source_combo.setAccessibleName(self._tr('원본 파일', 'Source file'))
        self.second_combo.setAccessibleName(self._tr('비교할 파일', 'Comparison file'))
        self._update_notice()
        for widget, ko, en in ((self.add_button, '파일 선택', 'Choose files'),
                               (self.folder_button, '저장 폴더', 'Output folder'),
                               (self.compatibility_button, '호환 확인', 'Compatibility'),
                               (self.metadata_button, '메타데이터 탐지', 'Inspect metadata'),
                               (self.strip_button, '선택 제거 사본 저장', 'Save selected removal'),
                               (self.compare_button, '문서 전후 비교', 'Compare documents'),
                               (self.cancel_button, '취소', 'Cancel')):
            widget.setText(self._tr(ko, en))
        self.output_edit.setPlaceholderText(self._tr('새 사본 저장 폴더', 'Folder for new copies'))
        self.page_spin.setPrefix(self._tr('페이지 ', 'Page '))
        # 언어를 바꿀 때 사용자가 선택한 제거 항목과 검사 결과는 보존한다.
        if not self.status.text():
            self.status.setText(self._tr('파일과 작업을 선택하세요.', 'Choose files and an action.'))

    def _update_notice(self):
        notices = (
            ('출력 형식을 고르고 호환 확인을 누르세요. 서식 보존을 보장하는 검사는 아닙니다.',
             'Choose an output format, then check compatibility. This does not guarantee formatting preservation.'),
            ('탐지 후 제거할 항목을 선택하세요. 원본을 보존하며 새 사본에만 적용합니다. 본문·첨부·댓글은 별도로 검토하세요.',
             'Inspect, then select metadata to remove in a new copy. Originals are preserved. Review content, attachments and comments separately.'),
            ('비교할 파일을 고르고 문서 전후 비교를 누르세요. 페이지별 화면과 텍스트 차이를 함께 확인합니다.',
             'Choose a comparison file, then compare documents. Review page images alongside extracted text differences.'),
        )
        self.notice.setText(self._tr(*notices[self.tabs.currentIndex()]))

    def _tab_changed(self, index):
        # 탭마다 검사 결과를 보존하여 다른 작업의 결과와 혼동하지 않게 한다.
        self._tab_results[self._active_tab] = self.details.toPlainText()
        self._active_tab = index
        self.details.setPlainText(self._tab_results.get(index, ''))
        self._update_notice()
        # 짧은 호환 입력은 내용 높이만 차지하고, 비교 화면에는 미리보기 공간을 배정한다.
        self.tabs.setMaximumHeight((190, 370, 16777215)[index])
        self._root_layout.setStretchFactor(self.tabs, (0, 2, 3)[index])

    def _sync_page_buttons(self, *unused):
        idle = not self.is_busy()
        self.previous_page_button.setEnabled(idle and self.page_spin.value() > self.page_spin.minimum())
        self.next_page_button.setEnabled(idle and self.page_spin.value() < self.page_spin.maximum())

    def set_reduced_motion(self, enabled):
        set_reduced_motion(self, enabled)

    def add_paths(self, paths):
        for path in paths:
            value = str(path)
            if value not in self._paths and Path(value).is_file():
                self._paths.append(value)
                self.source_combo.addItem(Path(value).name, value)
                self.second_combo.addItem(Path(value).name, value)
        if self.second_combo.count() > 1:
            self.second_combo.setCurrentIndex(1)

    def _source_changed(self, *unused):
        self.metadata_list.clear()
        self._tab_results.clear()
        self.details.clear()
        self.target_combo.clear()
        source = self.source_combo.currentData()
        if source:
            self.target_combo.addItems(engine.targets([Path(source)]))
        self._invalidate_compare()

    def _invalidate_compare(self, *unused):
        self.left_canvas.set_image(None)
        self.right_canvas.set_image(None)
        self._tab_results.pop(2, None)
        if self.tabs.currentIndex() == 2:
            self.details.clear()
        self.page_spin.setMaximum(1)
        self._sync_page_buttons()

    def _choose_files(self):
        dialog = make_file_dialog(self, 'pick_files_title')
        dialog.setFileMode(QFileDialog.ExistingFiles)
        if dialog.exec():
            self.add_paths(dialog.selectedFiles())

    def _choose_folder(self):
        dialog = make_file_dialog(self, 'pick_folder_title', folder=True)
        if dialog.exec():
            self.output_edit.setText(dialog.selectedFiles()[0])

    def _compatibility(self):
        source, target = self.source_combo.currentData(), self.target_combo.currentText()
        self._start(lambda cancel: tools.compatibility_report(source, target, cancel), 'compatibility')

    def _metadata(self):
        source = self.source_combo.currentData()
        self._start(lambda cancel: tools.metadata_report(source, cancel), 'metadata')

    def _strip(self):
        source, output = self.source_combo.currentData(), self.output_edit.text()
        keys = [self.metadata_list.item(i).data(Qt.UserRole) for i in range(self.metadata_list.count())
                if self.metadata_list.item(i).checkState() == Qt.Checked]
        self._start(lambda cancel: tools.strip_metadata(source, keys, output, cancel), 'strip')

    def _compare(self):
        left, right, page = self.source_combo.currentData(), self.second_combo.currentData(), self.page_spin.value() - 1
        self._start(lambda cancel: tools.compare_documents(left, right, cancel, page), 'compare')

    def _start(self, operation, action):
        if self.is_busy():
            return False
        owner = self.parentWidget()
        if owner is not None and callable(getattr(owner, 'work_busy', None)) and owner.work_busy():
            self.status.setText(self._tr('다른 작업이 끝난 뒤 실행하세요.', 'Wait for the other operation to finish.'))
            return False
        self._action, self._source_at_start = action, self.source_combo.currentData() or ''
        if owner is not None and type(getattr(owner, 'pending', None)) is int:
            owner.pending += 1
            self._gate_owner = owner
        self.job = _Job(operation, self)
        self.job.completed.connect(self._completed)
        self.job.failed.connect(self._failed)
        self.job.finished.connect(self._finished)
        self._set_busy(True)
        self.status.setText(self._tr('처리 중 · 취소할 수 있습니다.', 'Working · Cancellation is available.'))
        self.job.start()
        return True

    def _set_busy(self, busy):
        self.tabs.tabBar().setEnabled(not busy)
        for widget in (self.source_combo, self.second_combo, self.target_combo, self.add_button,
                       self.output_edit, self.folder_button, self.metadata_list, self.page_spin,
                       self.compatibility_button, self.metadata_button, self.strip_button, self.compare_button):
            widget.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self._sync_page_buttons()

    def _completed(self, result):
        if self._action == 'strip':
            self.status.setText(self._tr('원본 보존 · 새 사본: ', 'Original preserved · New copy: ') + str(result))
            self.result_ready.emit(self._source_at_start, str(result), '')
            return
        if self._action == 'metadata':
            self.metadata_list.clear()
            for entry in result['entries']:
                item = QListWidgetItem(entry['label'] + ': ' + entry['value'])
                item.setData(Qt.UserRole, entry['key'])
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
                self.metadata_list.addItem(item)
            self.details.setPlainText(result['notice'][self.language] + '\n' + result['limitations'][self.language])
        elif self._action == 'compare':
            for canvas, image in zip((self.left_canvas, self.right_canvas), result['images']):
                canvas.set_image(image)
            self.page_spin.setMaximum(max(result['left']['page_count'], result['right']['page_count']))
            self._sync_page_buttons()
            self.details.setPlainText((result['text_diff'] or self._tr('추출 텍스트가 같습니다.', 'Extracted text is identical.')) + '\n' + result['limitations'][self.language])
        else:
            labels = [('source', '입력 형식', 'Input format'), ('format', '출력 형식', 'Output format'),
                      ('supported', '변환 지원', 'Conversion supported'), ('checked', '내부 제한 검사', 'Limited internal inspection'),
                      ('macros', '매크로 흔적', 'Macro evidence'), ('formulas', '수식·필드 흔적 수', 'Formula / field evidence count'),
                      ('fonts', '글꼴 흔적', 'Font evidence'), ('external_links', '외부 관계 수', 'External relationship count')]
            lines = [self._tr(ko, en) + ': ' + json.dumps(result[key], ensure_ascii=False) for key, ko, en in labels]
            lines.extend(result['notes'][self.language])
            lines.append(result['limitations'][self.language])
            self.details.setPlainText('\n'.join(lines))
        self.status.setText(self._tr('완료 · 결과는 로컬 전용입니다.', 'Complete · Results are local only.'))

    def _failed(self, error):
        if isinstance(error, (Cancelled, engine.Cancelled)):
            message = self._tr('취소됨 · 원본을 보존했습니다.', 'Cancelled · Originals preserved.')
        elif isinstance(error, tools.DeliveryError):
            message = self._tr(error.ko, error.en)
        else:
            message = self._tr('처리에 실패했습니다. 파일과 도구 상태를 확인하세요.', 'Processing failed. Check the file and tool availability.')
            message += '\n' + str(error) if self.language == 'ko' else '\n' + type(error).__name__
        self.status.setText(message)
        if self._action == 'strip' and not isinstance(error, (Cancelled, engine.Cancelled)):
            self.result_ready.emit(self._source_at_start, '', message)

    def _finished(self):
        job, self.job = self.job, None
        if self._gate_owner is not None:
            self._gate_owner.pending -= 1
            self._gate_owner = None
        self._set_busy(False)
        if job:
            job.deleteLater()
        if self._closing:
            self.close()

    def _cancel(self):
        if self.job:
            self.job.cancel.set()
            self.cancel_button.setEnabled(False)

    def is_busy(self):
        return self.job is not None

    def shutdown(self):
        self._cancel()
        return not self.is_busy()

    def reject(self):
        if self.is_busy():
            self._closing = True
            self._cancel()
        else:
            super().reject()

    def closeEvent(self, event):
        if self.is_busy():
            self._closing = True
            self._cancel()
            event.ignore()
        else:
            super().closeEvent(event)

    def showEvent(self, event):
        self._closing = False
        super().showEvent(event)


def open_dialog(parent=None, language='ko', paths=None):
    dialog = DeliveryDialog(parent, language, paths)
    dialog.show()
    return dialog
