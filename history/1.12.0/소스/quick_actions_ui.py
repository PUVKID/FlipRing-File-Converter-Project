"""빠른 작업 화면. 긴 파일 작업은 작업자에서 수행하고 Qt 신호로만 화면을 갱신한다."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import threading
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import Qt, QObject, Signal, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QImage, QPixmap, QShortcut, QKeySequence
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QComboBox, QLineEdit, QSpinBox,
    QCheckBox, QGroupBox, QPlainTextEdit, QFileDialog, QInputDialog, QMessageBox,
    QAbstractItemView, QScrollArea, QProgressBar, QSplitter, QMenu)

import quick_actions as core
from ui_motion import make_file_dialog, set_reduced_motion

_ACTIVE = set()
_TEXT = {
    'manage': ('작업 관리', 'Manage actions'),
    'wheel': ('선택 작업을 원형 메뉴에 표시', 'Show selected action in radial menu'),
    'title': ('빠른 작업', 'Quick actions'),
    'hint': ('파일·폴더를 추가하고 작업을 대기열에 넣으세요. 원본은 보존합니다.', 'Add files or folders, then queue a task. Originals are preserved.'),
    'files': ('파일 추가', 'Add files'), 'folder': ('폴더 추가', 'Add folder'),
    'remove': ('입력 제거', 'Remove input'), 'output': ('결과 폴더', 'Output folder'),
    'browse': ('찾아보기', 'Browse'), 'options': ('작업 설정', 'Task settings'),
    'format': ('출력 형식', 'Output format'), 'quality': ('품질 (20–95)', 'Quality (20–95)'),
    'width': ('너비 px · 0=자동', 'Width px · 0=auto'), 'height': ('높이 px · 0=자동', 'Height px · 0=auto'),
    'target': ('목표 KiB · 0=없음', 'Target KiB · 0=none'),
    'zip': ('변환 후 ZIP으로 묶기', 'Bundle converted files as ZIP'),
    'template': ('이름 규칙', 'Name template'), 'filter': ('확장자 필터', 'Extension filter'),
    'save': ('작업 저장', 'Save action'), 'rename': ('이름 변경', 'Rename'),
    'delete': ('작업 삭제', 'Delete action'), 'import': ('가져오기', 'Import'),
    'export': ('내보내기', 'Export'), 'names': ('이름 미리보기', 'Preview names'),
    'check': ('실행 전 점검', 'Check readiness'), 'queue': ('대기열 추가', 'Add to queue'),
    'up': ('위로', 'Move up'), 'down': ('아래로', 'Move down'),
    'drop': ('대기 작업 삭제', 'Remove waiting task'), 'pause': ('일시 정지', 'Pause'),
    'resume': ('계속', 'Resume'), 'cancel': ('현재 작업 취소', 'Cancel current'),
    'retry': ('실패 작업 재시도', 'Retry failed tasks'), 'replay': ('선택 설정 재실행', 'Replay selected task'),
    'open': ('결과 폴더 열기', 'Open result folder'), 'reveal': ('파일 선택', 'Reveal file'),
    'copy': ('경로 복사', 'Copy path'), 'cleanup': ('선택 결과 정리', 'Archive selected results'),
    'undo': ('정리 되돌리기', 'Undo archive'), 'error': ('오류 복사', 'Copy errors'),
    'summary': ('요약 저장', 'Save summary'), 'before': ('원본', 'Original'), 'after': ('결과', 'Result'),
    'waiting': ('대기', 'Waiting'), 'running': ('처리 중', 'Running'),
    'completed': ('완료', 'Completed'), 'failed': ('실패', 'Failed'), 'cancelled': ('취소', 'Cancelled'),
    'paused': ('일시 정지 · 현재 파일 작업은 계속됩니다.', 'Paused · the current task continues.'),
    'ready': ('준비됨', 'Ready'), 'busy': ('다른 변환 작업이 끝난 뒤 계속합니다.', 'Waiting for another conversion to finish.'),
    'pick': ('먼저 입력과 결과 폴더를 지정해 주세요.', 'Select inputs and an output folder first.'),
    'name': ('작업 이름', 'Action name'), 'selected': ('사용자 작업을 선택해 주세요.', 'Select a saved user action.'),
    'preflight': ('예상 필요 공간(보수적 추정)', 'Estimated space (conservative)'),
    'free': ('사용 가능', 'Free'), 'met': ('목표 달성', 'Target met'), 'unmet': ('목표 미달성', 'Target not met'),
    'preview': ('이미지·PDF는 미리보기, 문서는 파일 정보와 기존 문서 작업으로 연결됩니다.', 'Images and PDFs show previews; documents show metadata and link to document tools.'),
    'document': ('문서 작업 열기', 'Open document tools'),
    'empty': ('선택된 파일이 없습니다.', 'No file selected.'),
    'details': ('자세한 상태', 'Details'),
    'shortcuts': ('Ctrl+O 파일 · Ctrl+Enter 대기열 · Delete 입력 제거 · Esc 현재 취소', 'Ctrl+O add · Ctrl+Enter queue · Delete remove input · Esc cancel'),
}


class _Bridge(QObject):
    done = Signal(int, object, str)
    event = Signal(str, object)


def _preview(raw, language='ko'):
    """실제 파일만 읽고 작은 RGBA 바이트를 반환한다. 문서 실행은 하지 않는다."""
    from PIL import Image, ImageDraw, ImageOps
    path = core.safe_path(raw)
    size = path.stat().st_size
    result = {'path': str(path), 'info': f'{path.name}\n{size:,} bytes', 'size': size, 'pixels': None}
    image = None
    try:
        if path.suffix.lower() == '.pdf':
            import pypdfium2 as pdfium
            from pdf_lock import PDFIUM_LOCK
            if not PDFIUM_LOCK.acquire(blocking=False):
                result['info'] += ('\nPDF busy' if language == 'en' else '\nPDF 처리 중')
                return result
            try:
                with pdfium.PdfDocument(str(path)) as document:
                    result['info'] += f' · {len(document)} ' + ('pages' if language == 'en' else '페이지')
                    if len(document):
                        page = document[0]
                        try:
                            width, height = page.get_size()
                            bitmap = page.render(scale=min(1, 450 / max(width, height)))
                            try:
                                image = bitmap.to_pil().convert('RGBA').copy()
                            finally:
                                bitmap.close()
                        finally:
                            page.close()
            finally:
                PDFIUM_LOCK.release()
        else:
            import engine
            kind, extension = engine.classify(path)
            if kind in ('문서', '프레젠테이션', '스프레드시트'):
                result['info'] += '\n' + extension.upper()
                result['document'] = True
                return result
            with Image.open(path) as opened:
                result['info'] += f' · {opened.width} × {opened.height} px'
                image = ImageOps.exif_transpose(opened)
                image.thumbnail((450, 240))
                image = image.convert('RGBA').copy()
        if image:
            image.thumbnail((450, 240))
            background = Image.new('RGBA', image.size, (235, 235, 235, 255))
            draw = ImageDraw.Draw(background)
            for y in range(0, image.height, 12):
                for x in range(0, image.width, 12):
                    if (x // 12 + y // 12) % 2:
                        draw.rectangle((x, y, x + 11, y + 11), fill=(200, 200, 200, 255))
            background.alpha_composite(image)
            result['pixels'] = (background.tobytes(), background.width, background.height)
    except Exception as error:
        result['info'] += '\n' + str(error)
    return result


class QuickActionsPanel(QWidget):
    def __init__(self, owner, language='ko'):
        super().__init__(owner if isinstance(owner, QWidget) else None)
        self.owner, self.language = owner, language
        self._closed = False
        self._reduced_motion = False
        self._pickers = []
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='FlipRing-quick')
        self._tasks, self._sequence = {}, 0
        self._bridge = _Bridge(self)
        self._bridge.done.connect(self._done)
        self._bridge.event.connect(self._event)
        self._cancel = threading.Event()
        self._scan_cancel = threading.Event()
        self._jobs, self._active_job = [], None
        self._paused = False
        self._inputs, self._outputs, self._last_errors = [], [], []
        self._preview_serial = 0
        self._ledger = core.OutputLedger()
        self._labels, self._buttons = [], []
        self._queue_controls, self._result_controls, self._preview_controls = [], [], []
        settings = getattr(owner, 'settings', None)
        configured = settings.fileName() if settings is not None else ''
        base = Path(configured).parent if configured and not str(configured).startswith('\\') else Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'FlipRing'
        if not configured or Path(configured).suffix.lower() != '.ini':
            base = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'FlipRing'
        self.store = core.ActionStore(base / 'quick-actions.json')
        self._saved = []
        layout = QVBoxLayout(self)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        body = QWidget(); self.body_layout = QVBoxLayout(body)
        scroll.setWidget(body); layout.addWidget(scroll)
        self.title = self._label('title'); self.title.setStyleSheet('font-size:22px;font-weight:700;')
        self.body_layout.addWidget(self.title); self.body_layout.addWidget(self._label('hint'))
        row = QHBoxLayout()
        for key, slot in [('files', self.choose_files), ('folder', self.choose_folder), ('remove', self.remove_inputs)]:
            button = self._button(key, slot); row.addWidget(button)
            if key == 'remove': self.remove_input_button = button
        self.body_layout.addLayout(row)
        self.inputs = QListWidget(); self.inputs.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.inputs.setMaximumHeight(105); self.inputs.currentRowChanged.connect(self.preview_input)
        self.body_layout.addWidget(self.inputs)
        row = QHBoxLayout(); row.addWidget(self._label('output'))
        self.output = QLineEdit(); row.addWidget(self.output, 1); row.addWidget(self._button('browse', self.choose_output))
        self.body_layout.addLayout(row)
        row = QHBoxLayout(); self.presets = QComboBox(); self.presets.currentIndexChanged.connect(self.load_action)
        row.addWidget(self.presets, 1)
        manage = self._button('manage', lambda: None); menu = QMenu(manage)
        for key, slot in [('save', self.save_action), ('rename', self.rename_action), ('delete', self.delete_action), ('import', self.import_action), ('export', self.export_action)]:
            action = menu.addAction(self.t(key)); action.triggered.connect(slot); self._buttons.append((action, key))
        manage.setMenu(menu); row.addWidget(manage)
        self.body_layout.addLayout(row)
        self.wheel_enabled = QCheckBox()
        self._buttons.append((self.wheel_enabled, 'wheel'))
        self.wheel_enabled.setChecked(str(settings.value('quick/wheel', 'true') if settings is not None else 'true').lower() in ('true', '1'))
        self.wheel_enabled.toggled.connect(self._save_wheel)
        self.body_layout.addWidget(self.wheel_enabled)
        basic = QHBoxLayout(); basic.addWidget(self._label('format'))
        self.options = QGroupBox(); self._labels.append((self.options, 'options'))
        form = QFormLayout(self.options)
        self.format = QComboBox()
        self.format.addItems(sorted({fmt for _, values in core.engine.TABLE.values() for fmt in values.split()}))
        basic.addWidget(self.format, 1); self.body_layout.addLayout(basic)
        options_toggle = self._button('options', lambda checked: self.options.setVisible(checked))
        options_toggle.setCheckable(True); self.body_layout.addWidget(options_toggle)
        self.quality = QSpinBox(); self.quality.setRange(20, 95); self.quality.setValue(85)
        self.width = QSpinBox(); self.width.setRange(0, 12000)
        self.height = QSpinBox(); self.height.setRange(0, 12000)
        self.target = QSpinBox(); self.target.setRange(0, 1024 * 1024 * 1024)
        self.zip = QCheckBox(); self._buttons.append((self.zip, 'zip'))
        self.template = QLineEdit('{name}'); self.template.setPlaceholderText('{name}_{index:03d}_{date}')
        self.extensions = QLineEdit(); self.extensions.setPlaceholderText('jpg, png, pdf')
        for key, widget in [('quality', self.quality), ('width', self.width), ('height', self.height), ('target', self.target), ('template', self.template), ('filter', self.extensions)]:
            form.addRow(self._label(key), widget)
        form.addRow(self.zip)
        self.body_layout.addWidget(self.options); self.options.hide()
        row = QHBoxLayout()
        for key, slot in [('names', self.preview_names), ('check', self.check_readiness)]:
            row.addWidget(self._button(key, slot))
        form.addRow(row)
        self.body_layout.addWidget(self._button('queue', self.enqueue))
        self.queue = QListWidget(); self.queue.setMaximumHeight(130)
        self.body_layout.addWidget(self.queue)
        row = QHBoxLayout()
        for key, slot in [('up', lambda: self.move_job(-1)), ('down', lambda: self.move_job(1)), ('drop', self.remove_job), ('pause', self.pause), ('resume', self.resume)]:
            button = self._button(key, slot); row.addWidget(button); self._queue_controls.append(button)
        self.body_layout.addLayout(row)
        row = QHBoxLayout()
        for key, slot in [('cancel', self.cancel), ('retry', self.retry_failed), ('replay', self.replay)]:
            button = self._button(key, slot); row.addWidget(button); self._queue_controls.append(button)
        self.body_layout.addLayout(row)
        self.progress = QProgressBar(); self.body_layout.addWidget(self.progress)
        self.status = QLabel(); self.status.setWordWrap(True); self.body_layout.addWidget(self.status)
        self.results = QListWidget(); self.results.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.results.setMaximumHeight(110); self.results.currentRowChanged.connect(self.preview_result)
        self.body_layout.addWidget(self.results)
        row = QHBoxLayout()
        for key, slot in [('open', self.open_folder), ('reveal', self.reveal_result), ('copy', self.copy_path), ('cleanup', self.cleanup), ('undo', self.undo)]:
            button = self._button(key, slot); row.addWidget(button); self._result_controls.append(button)
        self.body_layout.addLayout(row)
        row = QHBoxLayout()
        for key, slot in [('error', self.copy_errors), ('summary', self.export_summary)]:
            button = self._button(key, slot); row.addWidget(button); self._queue_controls.append(button)
        self.body_layout.addLayout(row)
        previews = QHBoxLayout(); self.pictures, self.metadata = [], []
        for key in ('before', 'after'):
            column = QVBoxLayout(); label = self._label(key); column.addWidget(label); self._preview_controls.append(label)
            picture = QLabel(); picture.setAlignment(Qt.AlignCenter); picture.setMinimumHeight(110)
            info = QLabel(); info.setWordWrap(True); info.setTextInteractionFlags(Qt.TextSelectableByMouse)
            column.addWidget(picture); column.addWidget(info); previews.addLayout(column, 1)
            self.pictures.append(picture); self.metadata.append(info); self._preview_controls.extend([picture, info])
        self.body_layout.addLayout(previews)
        self.savings = QLabel(); self.body_layout.addWidget(self.savings)
        guidance = self._label('preview'); document = self._button('document', self.document_tools)
        self.body_layout.addWidget(guidance); self.body_layout.addWidget(document)
        self._preview_controls.extend([self.savings, guidance, document])
        self.details = QPlainTextEdit(); self.details.setReadOnly(True); self.details.setMaximumHeight(100)
        self.body_layout.addWidget(self.details)
        self.details.textChanged.connect(lambda: self.details.setVisible(bool(self.details.toPlainText())))
        self.details.hide()
        self.body_layout.addWidget(self._label('shortcuts'))
        for sequence, slot in [('Ctrl+O', self.choose_files), ('Ctrl+Return', self.enqueue), ('Escape', self.cancel)]:
            shortcut = QShortcut(QKeySequence(sequence), self); shortcut.setContext(Qt.WidgetWithChildrenShortcut); shortcut.activated.connect(slot)
        delete = QShortcut(QKeySequence('Delete'), self.inputs); delete.setContext(Qt.WidgetShortcut); delete.activated.connect(self.remove_inputs)
        self._timer = QTimer(self); self._timer.setInterval(300); self._timer.timeout.connect(self._next)
        self.set_language(language)
        self.reload_actions()
        self._sync_visibility()
        self.body_layout.addStretch(1)

    def _sync_visibility(self):
        self.inputs.setVisible(bool(self._inputs)); self.remove_input_button.setVisible(bool(self._inputs))
        self.queue.setVisible(bool(self._jobs)); self.progress.setVisible(bool(self._jobs))
        self.results.setVisible(bool(self._outputs))
        for widget in self._queue_controls: widget.setVisible(bool(self._jobs))
        for widget in self._result_controls: widget.setVisible(bool(self._outputs))
        for widget in self._preview_controls: widget.setVisible(bool(self._inputs or self._outputs))

    def t(self, key):
        pair = _TEXT.get(key, (key, key))
        return pair[self.language == 'en']

    def _label(self, key):
        widget = QLabel(); self._labels.append((widget, key)); return widget

    def _button(self, key, slot):
        widget = QPushButton(); self._buttons.append((widget, key)); widget.clicked.connect(slot); return widget

    def set_language(self, language):
        self.language = 'en' if language == 'en' else 'ko'
        for widget, key in self._labels:
            if isinstance(widget, QGroupBox): widget.setTitle(self.t(key))
            else: widget.setText(self.t(key))
        for widget, key in self._buttons: widget.setText(self.t(key))
        self.presets.blockSignals(True)
        for index, name in enumerate(('Photo JPG', 'Submission JPG + ZIP', 'Document PDF')):
            if index < self.presets.count(): self.presets.setItemText(index, name if self.language == 'en' else core.BUILTINS[index]['name'])
        self.presets.blockSignals(False)
        self.refresh_queue()
        self.status.setText(self.t('ready'))
        for dialog in self._pickers:
            dialog.set_language(self.language)

    def set_reduced_motion(self, enabled):
        self._reduced_motion = bool(enabled)
        for dialog in self._pickers: set_reduced_motion(dialog, enabled)

    def _submit(self, operation, callback, on_error=None):
        if self._closed:
            return
        self._sequence += 1; number = self._sequence
        self._tasks[number] = (callback, on_error); _ACTIVE.add(self)
        future = self._pool.submit(operation)
        def finished(item):
            try:
                result, error = item.result(), ''
            except BaseException as exception:
                result, error = None, str(exception)
            self._bridge.done.emit(number, result, error)
        future.add_done_callback(finished)

    def _done(self, number, result, error):
        callbacks = self._tasks.pop(number, None)
        if not self._closed and callbacks:
            callback, on_error = callbacks
            if error:
                self.report(error)
                if on_error: on_error(error)
            else: callback(result)
        if self._closed and not self._tasks:
            self._active_job = None
            self._pool.shutdown(wait=False, cancel_futures=True); _ACTIVE.discard(self)
        elif not self._tasks:
            _ACTIVE.discard(self)

    def report(self, message):
        self.status.setText(str(message)); self.details.setPlainText(str(message))
        self._last_errors.append(str(message))

    def choose_paths(self, key, *, folder=False, save=False, single=False, initial='', name_filter=''):
        dialog = make_file_dialog(self, self.t(key), folder=folder, name_filter=name_filter)
        dialog.set_language(self.language)
        if save:
            dialog.setAcceptMode(QFileDialog.AcceptSave); dialog.setFileMode(QFileDialog.AnyFile); dialog.setDefaultSuffix('json')
        elif single: dialog.setFileMode(QFileDialog.ExistingFile)
        if initial:
            if folder: dialog.setDirectory(initial)
            else: dialog.selectFile(initial)
        self._pickers.append(dialog); set_reduced_motion(dialog, self._reduced_motion)
        try: return dialog.selectedFiles() if dialog.exec() == QFileDialog.Accepted else []
        finally:
            self._pickers.remove(dialog); dialog.deleteLater()

    def _save_wheel(self, checked):
        settings = getattr(self.owner, 'settings', None)
        if settings is not None:
            settings.setValue('quick/wheel', checked); settings.sync()

    def wheel_action(self):
        if self._closed or not self.wheel_enabled.isChecked(): return None
        try: return self.action()
        except (ValueError, TypeError): return None

    def wheel_label(self):
        action = self.wheel_action()
        return action['name'] if action else ''

    def enqueue_paths(self, paths):
        """휠의 입력·설정을 즉시 스냅샷으로 잡아 화면 입력 목록과 독립 처리한다."""
        action = self.wheel_action()
        if not action or not paths: return
        captured = [str(path) for path in paths]
        output = self.output.text().strip() or str(Path(captured[0]).parent / 'FlipRing 결과')
        def ready(result):
            if result['skipped']: self.details.setPlainText('\n'.join(result['skipped']))
            if result['inputs']: self._append_job(result['inputs'], action, output)
            else: self.report(self.t('empty'))
        self._submit(lambda: core.collect_inputs(captured, action['extensions'], self._scan_cancel), ready)

    def choose_files(self):
        paths = self.choose_paths('files')
        if paths: self.add_paths(paths)

    def choose_folder(self):
        paths = self.choose_paths('folder', folder=True)
        if paths: self.add_paths(paths)

    def add_paths(self, paths):
        extensions = self.extensions.text()
        self._submit(lambda: core.collect_inputs(paths, extensions, self._scan_cancel), self._collected)

    def _collected(self, result):
        known = {os.path.normcase(row['source']) for row in self._inputs}
        for row in result['inputs']:
            if os.path.normcase(row['source']) not in known:
                self._inputs.append(row); known.add(os.path.normcase(row['source']))
                item = QListWidgetItem(row['relative']); item.setToolTip(row['source']); self.inputs.addItem(item)
        if result['skipped']: self.details.setPlainText('\n'.join(result['skipped']))
        self.status.setText(f"{len(self._inputs):,} " + ('files' if self.language == 'en' else '파일'))
        self._sync_visibility()

    def remove_inputs(self):
        for index in sorted((self.inputs.row(i) for i in self.inputs.selectedItems()), reverse=True):
            self._inputs.pop(index); self.inputs.takeItem(index)
        self._sync_visibility()

    def choose_output(self):
        paths = self.choose_paths('output', folder=True, initial=self.output.text())
        if paths: self.output.setText(paths[0])

    def action(self):
        index = self.presets.currentIndex()
        name = (self.presets.currentData() or {}).get('name', '빠른 작업')
        return core.validate_action({'version': 1, 'name': name, 'format': self.format.currentText(),
            'quality': self.quality.value(), 'width': self.width.value(), 'height': self.height.value(),
            'max_bytes': self.target.value() * 1024, 'zip': self.zip.isChecked(),
            'template': self.template.text(), 'extensions': self.extensions.text()})

    def reload_actions(self, select=None):
        try: self._saved = self.store.load()
        except Exception as error: self.report(error); self._saved = []
        self.presets.blockSignals(True); self.presets.clear()
        for row in [*core.BUILTINS, *self._saved]: self.presets.addItem(row['name'], copy.deepcopy(row))
        self.presets.blockSignals(False)
        settings = getattr(self.owner, 'settings', None)
        preferred = select or (settings.value('quick/selected', '') if settings is not None else '')
        self.presets.setCurrentIndex(max(0, self.presets.findText(preferred)))
        self.load_action(self.presets.currentIndex())
        self.set_language(self.language)

    def load_action(self, index):
        action = self.presets.itemData(index)
        if not action: return
        self.format.setCurrentText(action['format']); self.quality.setValue(action['quality'])
        self.width.setValue(action['width']); self.height.setValue(action['height'])
        self.target.setValue(action['max_bytes'] // 1024); self.zip.setChecked(action['zip'])
        self.template.setText(action['template']); self.extensions.setText(action['extensions'])
        settings = getattr(self.owner, 'settings', None)
        if settings is not None: settings.setValue('quick/selected', action['name'])

    def save_action(self):
        name, ok = QInputDialog.getText(self, self.t('save'), self.t('name'))
        if not ok: return
        try:
            action = self.action(); action['name'] = name
            self.store.save(action); self.reload_actions(name)
        except Exception as error: self.report(error)

    def _selected_saved(self):
        row = self.presets.currentData()
        if not row or self.presets.currentIndex() < len(core.BUILTINS): raise ValueError(self.t('selected'))
        return row

    def rename_action(self):
        try:
            row = copy.deepcopy(self._selected_saved())
            name, ok = QInputDialog.getText(self, self.t('rename'), self.t('name'), text=row['name'])
            if ok:
                previous = row['name']; row['name'] = name
                self.store.save(row, previous); self.reload_actions(name)
        except Exception as error: self.report(error)

    def delete_action(self):
        try:
            row = self._selected_saved(); self.store.delete(row['name']); self.reload_actions()
        except Exception as error: self.report(error)

    def import_action(self):
        paths = self.choose_paths('import', single=True, name_filter='JSON (*.json)')
        if not paths: return
        path = paths[0]
        def operation():
            source = core.safe_path(path)
            if source.stat().st_size > 2 * 1024 * 1024: raise ValueError('JSON > 2MiB')
            row = core.validate_action(json.loads(source.read_text(encoding='utf-8-sig')))
            self.store.save(row); return row
        self._submit(operation, lambda row: self.reload_actions(row['name']))

    def export_action(self):
        try: row = self.action()
        except Exception as error: self.report(error); return
        paths = self.choose_paths('export', save=True, initial='빠른작업.json', name_filter='JSON (*.json)')
        path = paths[0] if paths else ''
        if path: self._submit(lambda: self._write_json(path, row), lambda _: self.status.setText(self.t('completed')))

    @staticmethod
    def _write_json(path, value):
        # 사용자가 저장창에서 지정한 문서만 저장한다. 변환 결과 발행과 별개이다.
        Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

    def _request(self):
        if not self._inputs or not self.output.text().strip(): raise ValueError(self.t('pick'))
        action = self.action()
        allowed = {s.strip().lower().lstrip('.') for s in action['extensions'].replace(';', ',').split(',') if s.strip()}
        inputs = [copy.deepcopy(r) for r in self._inputs if not allowed or Path(r['source']).suffix.lower().lstrip('.') in allowed]
        if not inputs: raise ValueError(self.t('empty'))
        return inputs, action, self.output.text().strip()

    def preview_names(self):
        try:
            records, action, output = self._request()
            self.details.setPlainText('\n'.join(str(Path(output) / Path(r['relative']).parent / core.output_name(r, action, i)) for i, r in enumerate(records, 1)) + '\n' + ('Collisions receive a number.' if self.language == 'en' else '이름 충돌 시 번호가 붙습니다.'))
        except Exception as error: self.report(error)

    def check_readiness(self):
        try: records, action, output = self._request()
        except Exception as error: self.report(error); return
        def show(report):
            lines = [f"{self.t('preflight')}: {report['estimated']:,} bytes · {self.t('free')}: {report['free']:,} bytes"]
            lines.extend(row['source'] + ': ' + (self.t('ready') if row['ok'] else row['error']) for row in report['files'])
            if report['error']: lines.append(report['error'])
            self.details.setPlainText('\n'.join(lines)); self.status.setText(self.t('ready') if report['ok'] else self.t('failed'))
        self._submit(lambda: core.preflight(records, action, output, self._scan_cancel), show)

    def enqueue(self):
        try: records, action, output = self._request()
        except Exception as error: self.report(error); return
        self._append_job(records, action, output)

    def _append_job(self, records, action, output):
        job = {'id': core.uuid.uuid4().hex[:8], 'inputs': copy.deepcopy(records), 'action': copy.deepcopy(action), 'output': output, 'state': 'waiting', 'result': None, 'file_states': {r['source']: 'waiting' for r in records}}
        self._jobs.append(job); self.refresh_queue(); self._timer.start(); self._next()

    def refresh_queue(self):
        selected = self.queue.currentRow() if hasattr(self, 'queue') else -1
        if not hasattr(self, 'queue'): return
        self.queue.clear()
        if hasattr(self, 'progress'): self._sync_visibility()
        for job in self._jobs:
            item = QListWidgetItem(f"{job['id']} · {job['action']['name']} · {len(job['inputs'])} files · {self.t(job['state'])}")
            if job.get('result'): item.setToolTip(job['result'].get('error', ''))
            self.queue.addItem(item)
        if 0 <= selected < self.queue.count(): self.queue.setCurrentRow(selected)

    def _other_busy(self):
        if bool(getattr(self.owner, 'pending', False)): return True
        installer = getattr(self.owner, 'installer', None)
        if installer is not None and installer.is_busy(): return True
        for name in ('pdf_panel', 'workspace_panel'):
            panel = getattr(self.owner, name, None)
            if panel is not None and panel is not self and getattr(panel, 'is_busy', lambda: False)(): return True
        return False

    def _next(self):
        if self._closed or self._paused or self._active_job is not None or self._tasks: return
        job = next((row for row in self._jobs if row['state'] == 'waiting'), None)
        if not job: self._timer.stop(); return
        if self._other_busy(): self.status.setText(self.t('busy')); return
        self._active_job = job; job['state'] = 'running'; self._cancel = threading.Event()
        self._update_progress()
        self.refresh_queue()
        token = self._cancel
        def operation():
            if job.get('bundle_rows'):
                previous = copy.deepcopy(job['previous'])
                try:
                    bundle = core.create_bundle(job['bundle_rows'], job['output'], token)
                    return {**previous, 'status': 'completed', 'outputs': [bundle], 'error': '', 'bundle_pending': False}
                except (core.pdf_tools.Cancelled, core.engine.Cancelled):
                    return {**previous, 'status': 'cancelled', 'outputs': [], 'error': ''}
                except Exception as error:
                    return {**previous, 'status': 'failed', 'outputs': [], 'error': str(error)}
            return core.run_action(job['inputs'], job['action'], job['output'], token,
                lambda event: self._bridge.event.emit(job['id'], event))
        self._submit(operation, lambda result: self._job_done(job, result), lambda error: self._job_done(job, {'status': 'failed', 'outputs': [], 'files': [], 'error': error, 'warnings': []}))

    def _event(self, identifier, event):
        if self._closed: return
        self.status.setText(self.t(event['state']) + ' · ' + Path(event['source']).name)
        if self._active_job and self._active_job['id'] == identifier:
            self._active_job['file_states'][event['source']] = event['state']
            for index, row in enumerate(self._inputs):
                if row['source'] == event['source']:
                    self.inputs.item(index).setText(row['relative'] + ' · ' + self.t(event['state']))
            self._update_progress()

    def _job_done(self, job, result):
        job['result'] = result; job['state'] = result['status']; self._active_job = None
        finished = {r['source'] for r in result.get('files', []) if r['state'] == 'completed'}
        for source in job['file_states']:
            job['file_states'][source] = 'completed' if source in finished else result['status']
        self._update_progress()
        for index, row in enumerate(self._inputs):
            if row['source'] in job['file_states']:
                self.inputs.item(index).setText(row['relative'] + ' · ' + self.t(job['file_states'][row['source']]))
        self._ledger.register(result['outputs'])
        for row in result['outputs']:
            self._outputs.append(row)
            status = self.t('met') if row['constraints_met'] else self.t('unmet')
            self.results.addItem(f"{Path(row['path']).name} · {row['size']:,} bytes · {status}")
            self.results.item(self.results.count() - 1).setToolTip(row['path'])
        self.refresh_queue(); self.status.setText(self.t(result['status']))
        detail = '\n'.join([result['error'], *result['warnings']]).strip()
        if detail: self.report(detail)
        self._next()

    def _update_progress(self):
        states = [state for job in self._jobs for state in job['file_states'].values()]
        self.progress.setRange(0, max(1, len(states)))
        self.progress.setValue(sum(s in ('completed', 'failed', 'cancelled') for s in states))

    def move_job(self, offset):
        index = self.queue.currentRow(); destination = index + offset
        if index < 0 or not 0 <= destination < len(self._jobs): return
        if self._jobs[index]['state'] != 'waiting' or self._jobs[destination]['state'] != 'waiting': return
        self._jobs[index], self._jobs[destination] = self._jobs[destination], self._jobs[index]
        self.refresh_queue(); self.queue.setCurrentRow(destination)

    def remove_job(self):
        index = self.queue.currentRow()
        if index >= 0 and self._jobs[index]['state'] == 'waiting': self._jobs.pop(index); self.refresh_queue()

    def pause(self): self._paused = True; self.status.setText(self.t('paused'))
    def resume(self): self._paused = False; self._timer.start(); self._next()
    def cancel(self): self._cancel.set()

    def retry_failed(self):
        for job in list(self._jobs):
            if job['state'] == 'failed' and not job.get('retried'):
                job['retried'] = True
                completed = {r['source'] for r in job['result']['files'] if r['state'] == 'completed'}
                records = [r for r in job['inputs'] if r['source'] not in completed]
                if records:
                    self._append_job(records, job['action'], job['output'])
                elif job['result'].get('bundle_pending'):
                    self._paused, paused = True, self._paused
                    self._append_job([], job['action'], job['output'])
                    retry = self._jobs[-1]; retry['bundle_rows'] = job.get('bundle_rows') or copy.deepcopy(job['result']['outputs'])
                    retry['previous'] = job['result']; self._paused = paused; self._next()

    def replay(self):
        index = self.queue.currentRow()
        if index >= 0:
            job = self._jobs[index]; self._append_job(job['inputs'], job['action'], job['output'])

    def preview_input(self, index):
        if 0 <= index < len(self._inputs): self._show_preview(self._inputs[index]['source'], '')

    def preview_result(self, index):
        if 0 <= index < len(self._outputs):
            row = self._outputs[index]; self._show_preview(row['source'], row['path'])

    def _show_preview(self, source, output):
        self._preview_serial += 1; serial = self._preview_serial
        for picture in self.pictures: picture.clear()
        for info in self.metadata: info.setText(self.t('empty'))
        self.savings.clear()
        language = self.language
        def operation(): return [_preview(p, language) if p else None for p in (source, output)]
        def show(rows):
            if serial != self._preview_serial: return
            for i, row in enumerate(rows):
                if not row: continue
                self.metadata[i].setText(row['info'])
                if row['pixels']:
                    raw, width, height = row['pixels']; image = QImage(raw, width, height, width * 4, QImage.Format_RGBA8888).copy()
                    self.pictures[i].setPixmap(QPixmap.fromImage(image).scaled(400, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            if all(rows) and rows[0]['size']:
                saving = 100 * (1 - rows[1]['size'] / rows[0]['size'])
                self.savings.setText((f'용량 변화: {saving:.1f}% 절감 (반올림)' if self.language != 'en' else f'Size change: {saving:.1f}% saved (rounded)'))
        self._submit(operation, show)

    def _selected_outputs(self):
        return [self._outputs[self.results.row(item)] for item in self.results.selectedItems()]

    def open_folder(self):
        row = self._selected_outputs()
        path = Path(row[0]['path']).parent if row else Path(self.output.text())
        if str(path) and path.is_dir(): QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def reveal_result(self):
        rows = self._selected_outputs()
        if not rows: return
        path = rows[0]['path']
        if not Path(path).exists(): self.report(self.t('empty')); return
        reveal = getattr(self.owner, 'reveal_preview', None)
        if callable(reveal): reveal(path)
        else:
            # 호스트의 검증된 선택 API가 없는 단독 화면에서는 폴더만 연다.
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def copy_path(self): QApplication.clipboard().setText('\n'.join(r['path'] for r in self._selected_outputs()))
    def copy_errors(self): QApplication.clipboard().setText('\n'.join(self._last_errors))

    def cleanup(self):
        if self._active_job or self._tasks: self.report(self.t('busy')); return
        paths = [r['path'] for r in self._selected_outputs()]
        self._submit(lambda: self._ledger.cleanup(paths), lambda result: self.details.setPlainText(json.dumps(result, ensure_ascii=False, indent=2)))

    def undo(self):
        if self._active_job or self._tasks: self.report(self.t('busy')); return
        self._submit(self._ledger.undo, lambda result: self.details.setPlainText(json.dumps(result, ensure_ascii=False, indent=2)))

    def export_summary(self):
        rows = copy.deepcopy(self._jobs)
        paths = self.choose_paths('summary', save=True, initial='작업요약.json', name_filter='JSON (*.json)')
        path = paths[0] if paths else ''
        if path: self._submit(lambda: self._write_json(path, rows), lambda _: self.status.setText(self.t('completed')))

    def document_tools(self):
        panel = getattr(self.owner, 'workspace_panel', None)
        selected = self._selected_outputs()
        paths = [r['path'] for r in selected] if selected else [r['source'] for r in self._inputs]
        if panel is not None and paths:
            panel.add_files(paths)
        # 호스트가 제공하는 기존 페이지 탐색 API만 사용한다.
        if hasattr(self.owner, 'open_page'):
            self.owner.open_page(6)
        elif panel is not None:
            panel.setFocus()
        self.status.setText(self.t('preview'))

    def is_busy(self): return bool(self._tasks or self._active_job)

    def shutdown(self):
        self._closed = True; self._timer.stop(); self._cancel.set(); self._scan_cancel.set()
        for dialog in list(self._pickers): dialog.reject()
        for job in self._jobs:
            if job['state'] == 'waiting': job['state'] = 'cancelled'
        if self._tasks: return False
        self._active_job = None
        self._pool.shutdown(wait=False, cancel_futures=True); _ACTIVE.discard(self); return True

    def closeEvent(self, event):
        if not self.shutdown(): event.ignore()
        else: super().closeEvent(event)
