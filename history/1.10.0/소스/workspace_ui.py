"""실제 파일·레시피·검사 도구를 연결하는 확장 작업 공간."""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QObject, QTimer, QMimeData, QUrl, QSize, QRect, QRectF, QPointF, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPainter, QPen, QPainterPath, QFont, QPixmap, QDrag, QShortcut, QKeySequence
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QComboBox, QLineEdit, QSpinBox,
    QCheckBox, QGroupBox, QPlainTextEdit, QFileDialog, QDialog, QAbstractItemView,
    QScrollArea, QSplitter, QDialogButtonBox, QLayout)
from i18n import tr, TEXT
from ui_motion import make_file_dialog, set_reduced_motion

# 취소 완료 신호가 도착하기 전에 Python 소유자가 해제되지 않게 유지한다.
_ACTIVE_PANELS = set()


class StableFolderWatch:
    """명시적으로 켠 한 폴더에서 두 차례 같은 서명이 관측된 파일만 전달한다."""
    def __init__(self):
        self.folder = None
        self.output = None
        self.previous = {}
        self.processed = set()

    def configure(self, folder, output):
        self.folder = Path(folder).resolve()
        self.output = Path(output).resolve()
        if not self.folder.is_dir():
            raise ValueError('감시 폴더가 없습니다 / Watch folder does not exist')
        if self.output == self.folder:
            raise ValueError('결과 폴더를 감시 폴더와 분리하세요 / Choose a separate output folder')
        self.previous.clear()
        self.processed.clear()

    def scan(self):
        if self.folder is None:
            return []
        observed = {}
        ready = []
        for path in sorted(self.folder.iterdir()):
            if (not path.is_file() or path.is_symlink() or path.name.startswith(('.', '~'))
                    or path.suffix.lower() in {'.tmp', '.part', '.crdownload', '.ini', '.json'}):
                continue
            resolved = path.resolve()
            if resolved == self.output or self.output in resolved.parents:
                continue
            stat = path.stat()
            signature = (str(resolved), stat.st_size, stat.st_mtime_ns)
            observed[str(resolved)] = signature
            if stat.st_size and self.previous.get(str(resolved)) == signature and signature not in self.processed:
                ready.append(str(resolved))
                self.processed.add(signature)
        self.previous = observed
        return ready


class WorkspaceVisual(QWidget):
    """파일 수와 실제 단계에 반응하는 유한 입체 카드 모션."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(106)
        self.setMaximumHeight(106)
        self.phase = 1.0
        self.state = 'ready'
        self.count = 0
        self.formats = []
        self.reduced = False
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(360)
        self.animation.setEasingCurve(QEasingCurve.InOutCubic)
        self.animation.valueChanged.connect(self._frame)

    def _frame(self, value):
        self.phase = float(value)
        self.update()

    def respond(self, state, paths=None):
        self.state = state
        if paths is not None:
            self.count = len(paths)
            self.formats = [Path(p).suffix[1:].upper() or 'FILE' for p in paths[:3]]
        self.animation.stop()
        self.phase = 1.0 if self.reduced or not self.isVisible() else 0.0
        if self.phase == 0:
            self.animation.setStartValue(0.0)
            self.animation.setEndValue(1.0)
            self.animation.start()
        self.update()

    def set_reduced_motion(self, enabled):
        self.reduced = bool(enabled)
        if enabled:
            self.animation.stop()
            self.phase = 1.0
        self.update()

    def hideEvent(self, event):
        self.animation.stop()
        self.phase = 1.0
        super().hideEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        center = self.width() / 2
        n = min(3, max(1, self.count))
        for i in range(n):
            spread = (i - (n-1)/2) * (75 - 23*self.phase if self.state == 'working' else 65)
            x = center - 33 + spread
            y = 17 + abs(i-(n-1)/2)*6 - (8*self.phase if self.state == 'complete' else 0)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0,0,0,18))
            p.drawRoundedRect(QRectF(x+6,y+8,63,80),8,8)
            shape = QPainterPath()
            fold = 17 - 5*self.phase
            shape.moveTo(x,y)
            shape.lineTo(x+63-fold,y)
            shape.lineTo(x+63,y+fold)
            shape.lineTo(x+63,y+80)
            shape.lineTo(x,y+80)
            shape.closeSubpath()
            p.setPen(QPen(QColor('#555555'),1))
            p.setBrush(QColor('#ffffff'))
            p.drawPath(shape)
            p.setBrush(QColor('#dddddd'))
            flap = QPainterPath(QPointF(x+63-fold,y))
            flap.lineTo(x+63-fold,y+fold)
            flap.lineTo(x+63,y+fold)
            flap.closeSubpath()
            p.drawPath(flap)
            p.setPen(QColor('#222222'))
            f = QFont(self.font()); f.setBold(True); f.setPointSize(12); p.setFont(f)
            p.drawText(QRectF(x+3,y+36,57,25),Qt.AlignCenter,self.formats[i] if i<len(self.formats) else '+')
        p.setPen(QPen(QColor('#333333'),2))
        p.setBrush(Qt.NoBrush)
        ring = QRectF(center+100,36,36,36)
        if self.state == 'working':
            p.drawArc(ring,30*16,int((80+240*self.phase)*16))
        elif self.state == 'complete':
            p.drawEllipse(ring)
            p.drawLine(QPointF(center+108,54),QPointF(center+116,62))
            p.drawLine(QPointF(center+116,62),QPointF(center+130,47))
        elif self.state in {'failed','cancelled'}:
            p.drawEllipse(ring)
            p.drawText(ring,Qt.AlignCenter,'!' if self.state=='failed' else '×')
        p.end()


class FileCards(QListWidget):
    files_dropped = Signal(list)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setAcceptDrops(True)
        self.setSpacing(5)
        self.setMinimumHeight(124)
        self.setStyleSheet('QListWidget{background:#fafafa;border:1px solid #dddddd;border-radius:10px;} QListWidget::item{background:white;border:1px solid #dedede;border-radius:7px;padding:10px;} QListWidget::item:selected{background:#e5e5e5;border:2px solid #242424;color:#111;} QListWidget:focus{border:2px solid #555;}')
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
        else: super().dragEnterEvent(event)
    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
        else: super().dragMoveEvent(event)
    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            self.files_dropped.emit([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
            event.setDropAction(Qt.CopyAction); event.accept()
        else: super().dropEvent(event)


class ResultList(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setMaximumHeight(90)
    def startDrag(self, actions):
        paths = [i.data(Qt.UserRole) for i in self.selectedItems()]
        if paths:
            mime = QMimeData(); mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
            drag = QDrag(self); drag.setMimeData(mime); drag.exec(Qt.CopyAction)


class WorkspaceBridge(QObject):
    event = Signal(dict)
    done = Signal(dict)


class CommandDialog(QDialog):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.setWindowTitle(panel.t('ws_commands'))
        self.resize(520,360)
        layout = QVBoxLayout(self)
        self.search = QLineEdit(); self.search.setPlaceholderText(panel.t('ws_search'))
        layout.addWidget(self.search)
        self.list = QListWidget(); layout.addWidget(self.list)
        self.commands = panel.commands()
        self.search.textChanged.connect(self.refresh)
        self.search.returnPressed.connect(self.run)
        self.list.itemActivated.connect(self.run)
        self.search.installEventFilter(self)
        self.refresh('')
    def refresh(self, query):
        self.list.clear()
        for label, action, needs_files in self.commands:
            if query.casefold() not in label.casefold(): continue
            reason = self.panel.t('ws_busy') if self.panel.global_busy() else self.panel.t('ws_empty') if needs_files and not self.panel.paths else ''
            item = QListWidgetItem(label + (' · '+reason if reason else ''))
            item.setData(Qt.UserRole,action); item.setData(Qt.UserRole+1,not bool(reason)); self.list.addItem(item)
        self.list.setCurrentRow(0)
    def eventFilter(self, watched, event):
        from PySide6.QtCore import QEvent
        if watched is self.search and event.type()==QEvent.KeyPress and event.key() in (Qt.Key_Down,Qt.Key_Up):
            offset = 1 if event.key()==Qt.Key_Down else -1
            self.list.setCurrentRow(max(0,min(self.list.count()-1,self.list.currentRow()+offset))); return True
        return super().eventFilter(watched,event)
    def run(self, *args):
        item = self.list.currentItem()
        if item is not None and item.data(Qt.UserRole+1):
            action = item.data(Qt.UserRole); self.accept(); action()


class CaptureOverlay(QWidget):
    captured = Signal(object)
    def __init__(self, screen, language):
        super().__init__(None,Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint|Qt.Tool)
        self.screen = screen; self.language = language; self.origin = None; self.selection = QRect()
        self.setGeometry(screen.geometry()); self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowOpacity(.25); self.setCursor(Qt.CrossCursor); self.setFocusPolicy(Qt.StrongFocus)
    def paintEvent(self, event):
        p=QPainter(self); p.fillRect(self.rect(),QColor('#777777')); p.setPen(QPen(Qt.white,3))
        p.drawRect(self.selection)
        p.drawText(self.rect().adjusted(24,24,-24,-24),Qt.AlignTop,tr(self.language,'ws_capture_hint'))
    def mousePressEvent(self,event): self.origin=event.position().toPoint()
    def mouseMoveEvent(self,event):
        if self.origin is not None:
            self.selection=QRect(self.origin,event.position().toPoint()).normalized(); self.update()
    def mouseReleaseEvent(self,event):
        if self.origin is None: return
        rect=QRect(self.origin,event.position().toPoint()).normalized(); self.hide()
        # 사용자 지정 영역이 확정된 뒤에만 화면 픽셀을 읽는다.
        if rect.width()>2 and rect.height()>2: QTimer.singleShot(100,lambda: self._grab(rect))
        else: self.close()
    def _grab(self,rect):
        shot=self.screen.grabWindow(0,rect.x()+self.screen.geometry().x(),rect.y()+self.screen.geometry().y(),rect.width(),rect.height())
        self.captured.emit(shot); self.close()
    def keyPressEvent(self,event):
        if event.key()==Qt.Key_Escape: self.close()


class WorkspacePanel(QWidget):
    def __init__(self, owner, language='ko'):
        super().__init__(owner)
        self.owner=owner; self.language=language
        self.paths=[]; self._busy=False; self._closed=False; self._cancel=threading.Event()
        self._pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='작업공간')
        self.bridge=WorkspaceBridge(self)
        self.bridge.event.connect(self.on_event,Qt.QueuedConnection)
        self.bridge.done.connect(self.on_done,Qt.QueuedConnection)
        self._labels=[]; self._dialogs=[]; self._pickers=[]; self._capture=None
        settings_path=Path(owner.settings.fileName()).parent
        self.data_dir=settings_path/'workspace'; self.data_dir.mkdir(parents=True,exist_ok=True)
        self.output_dir=self.data_dir/'results'; self.output_dir.mkdir(exist_ok=True)
        self.watcher=StableFolderWatch(); self.watch_timer=QTimer(self); self.watch_timer.setInterval(1200)
        self.watch_timer.timeout.connect(self.scan_watch); self.watch_queue=[]
        layout=QVBoxLayout(self); layout.setContentsMargins(0,0,0,0); layout.setSpacing(10)
        toolbar=QHBoxLayout(); layout.addLayout(toolbar)
        self.add_button=self.button('ws_add',self.choose_files); toolbar.addWidget(self.add_button)
        toolbar.addWidget(self.button('ws_clipboard',self.import_clipboard))
        toolbar.addWidget(self.button('ws_capture',self.start_capture))
        toolbar.addStretch(); toolbar.addWidget(self.button('ws_commands',self.open_commands))
        split=QSplitter(Qt.Horizontal); layout.addWidget(split,1)
        center_scroll=QScrollArea(); center_scroll.setWidgetResizable(True); center_scroll.setFrameShape(QScrollArea.NoFrame)
        self.center_scroll=center_scroll
        center=QWidget(); body=QVBoxLayout(center); body.setContentsMargins(0,0,8,0); body.setSpacing(9)
        body.setSizeConstraint(QLayout.SetMinimumSize)
        center_scroll.setWidget(center); split.addWidget(center_scroll)
        self.visual=WorkspaceVisual(); body.addWidget(self.visual)
        self.files=FileCards(); self.files.setMinimumHeight(124); self.files.files_dropped.connect(self.add_files)
        self.files.currentItemChanged.connect(self.preview_selection); self.files.model().rowsMoved.connect(self.sync_paths)
        body.addWidget(self.files,1)
        row=QHBoxLayout(); body.addLayout(row)
        row.addWidget(self.button('ws_remove',self.remove_files)); row.addStretch()
        self.count_label=QLabel(); row.addWidget(self.count_label)
        self.recipe_combo=QComboBox(); self.recipe_combo.currentIndexChanged.connect(self.load_selected_recipe); body.addWidget(self.recipe_combo)
        actions=QHBoxLayout(); body.addLayout(actions)
        self.operation=QComboBox()
        for key in ('convert','combine_pdf','collage','gif','watermark','receipts_xlsx','rename','audit','normalize_pages','compress_pdf','resize','ocr'):
            self.operation.addItem(key,key)
        actions.addWidget(self.operation,1); actions.addWidget(self.button('ws_use_step',self.use_operation))
        self.step_list=QListWidget(); self.step_list.setFixedHeight(56); self.step_list.currentRowChanged.connect(self.select_step); body.addWidget(self.step_list)
        steps=QHBoxLayout()
        steps.addWidget(self.button('ws_step_add',self.add_step)); steps.addWidget(self.button('ws_step_up',lambda:self.move_step(-1)))
        steps.addWidget(self.button('ws_step_down',lambda:self.move_step(1))); steps.addWidget(self.button('ws_step_remove',self.remove_step))
        self.status=QLabel(); self.status.setWordWrap(True); body.addWidget(self.status)
        self.results=ResultList(); body.addWidget(self.results); self.results.hide()
        self.result_actions_widget=QWidget(); result_actions=QHBoxLayout(self.result_actions_widget)
        result_actions.setContentsMargins(0,0,0,0); body.addWidget(self.result_actions_widget); self.result_actions_widget.hide()
        result_actions.addWidget(self.button('ws_copy_file',lambda:self.copy_result(True))); result_actions.addWidget(self.button('ws_copy_path',lambda:self.copy_result(False)))
        right_scroll=QScrollArea(); right_scroll.setWidgetResizable(True); right_scroll.setFrameShape(QScrollArea.NoFrame)
        right=QWidget(); options=QVBoxLayout(right); options.setContentsMargins(8,0,0,0); options.setSpacing(9)
        right_scroll.setWidget(right); split.addWidget(right_scroll); split.setSizes([535,300])
        self.preview=QLabel(); self.preview.setAlignment(Qt.AlignCenter); self.preview.setMinimumHeight(125)
        self.preview.setStyleSheet('background:white;border:1px solid #dedede;border-radius:9px;'); options.addWidget(self.preview)
        form=QFormLayout(); options.addLayout(form)
        self.format=QComboBox(); self.format.addItem('—','')
        for fmt in ('pdf','png','jpg','webp','gif','txt','docx','xlsx','tiff'): self.format.addItem(fmt.upper(),fmt)
        self.form_label(form,'ws_format',self.format)
        self.max_bytes=QSpinBox(); self.max_bytes.setRange(0,1000000); self.max_bytes.setSuffix(' KiB'); self.form_label(form,'ws_max',self.max_bytes)
        self.quality_enabled=QCheckBox(); self._labels.append((self.quality_enabled,'ws_quality_enable'))
        form.addRow(self.quality_enabled)
        self.dpi=QSpinBox(); self.dpi.setRange(60,600); self.dpi.setValue(150); self.form_label(form,'ws_dpi',self.dpi)
        self.quality=QSpinBox(); self.quality.setRange(20,95); self.quality.setValue(85); self.form_label(form,'ws_quality',self.quality)
        self.dpi.setEnabled(False); self.quality.setEnabled(False)
        self.quality_enabled.toggled.connect(self.dpi.setEnabled); self.quality_enabled.toggled.connect(self.quality.setEnabled)
        self.a4=QCheckBox(); self._labels.append((self.a4,'ws_a4')); options.addWidget(self.a4)
        self.name_template=QLineEdit('{name}_{index}'); self.name_template.textChanged.connect(self.preview_names)
        options.addWidget(self.label('ws_name')); options.addWidget(self.name_template)
        self.names_preview=QLabel(); self.names_preview.setWordWrap(True); options.addWidget(self.names_preview)
        options.addWidget(self.button('ws_name_apply',self.use_rename))
        inspection=QHBoxLayout(); options.addLayout(inspection)
        for mode,key in (('ocr','ws_ocr'),('compare','ws_compare'),('audit','ws_audit'),('redact','ws_redact')):
            inspection.addWidget(self.button(key,lambda checked=False,m=mode:self.open_inspection(m)))
        self.advanced=QGroupBox(); self.advanced.setCheckable(True); self.advanced.setChecked(False)
        self._labels.append((self.advanced,'ws_advanced')); options.addWidget(self.advanced)
        adv=QVBoxLayout(self.advanced)
        self.advanced_body=QWidget(); adv.addWidget(self.advanced_body); al=QVBoxLayout(self.advanced_body); al.setContentsMargins(0,0,0,0)
        self.recipe_editor=QPlainTextEdit(); self.recipe_editor.setMinimumHeight(145); self.recipe_editor.textChanged.connect(self.refresh_steps); al.addWidget(self.recipe_editor)
        al.addLayout(steps)
        r=QHBoxLayout(); al.addLayout(r)
        r.addWidget(self.button('ws_save',self.save_recipe)); r.addWidget(self.button('ws_import',self.import_recipe)); r.addWidget(self.button('ws_export',self.export_recipe))
        r2=QHBoxLayout(); al.addLayout(r2)
        r2.addWidget(self.button('ws_delete_recipe',self.delete_recipe)); r2.addWidget(self.button('ws_wheel',self.edit_wheel))
        al.addWidget(self.button('ws_output',self.choose_output)); al.addWidget(self.button('ws_watch_folder',self.choose_watch_folder))
        self.watch_enabled=QCheckBox(); self._labels.append((self.watch_enabled,'ws_watch_enable')); self.watch_enabled.toggled.connect(self.toggle_watch); al.addWidget(self.watch_enabled)
        self.watch_label=QLabel(); self.watch_label.setWordWrap(True); al.addWidget(self.watch_label)
        self.advanced.toggled.connect(self.advanced_body.setVisible); self.advanced_body.hide(); options.addStretch()
        execute=QHBoxLayout(); layout.addLayout(execute)
        self.output_label=QLabel(str(self.output_dir)); self.output_label.setWordWrap(True); execute.addWidget(self.output_label,1)
        self.cancel_button=self.button('ws_cancel',self.cancel); self.cancel_button.setEnabled(False); execute.addWidget(self.cancel_button)
        self.run_button=self.button('ws_run',self.run_recipe); self.run_button.setObjectName('primaryButton'); execute.addWidget(self.run_button)
        self.shortcut=QShortcut(QKeySequence('Ctrl+K'),owner); self.shortcut.activated.connect(self.open_commands)
        self.recipe_editor.setPlainText(json.dumps({'version':1,'name':'Convert','steps':[{'op':'convert','format':'png'}]},ensure_ascii=False,indent=2))
        self.set_status('ws_empty'); self.reload_recipes(); self.set_language(language)

    def t(self,key,**kwargs): return tr(self.language,key,**kwargs)
    def label(self,key):
        label=QLabel(); self._labels.append((label,key)); label.setText(self.t(key)); return label
    def button(self,key,action):
        b=QPushButton(self.t(key)); b.setMinimumHeight(32); b.clicked.connect(action); self._labels.append((b,key)); return b
    def form_label(self,form,key,widget): form.addRow(self.label(key),widget)
    def set_status(self,key,detail=''):
        self._status_key=key; self._status_detail=detail; self.status.setText(self.t(key)+(('\n'+detail) if detail else ''))
    def set_language(self,language):
        self.language='en' if language=='en' else 'ko'
        for widget,key in self._labels:
            if isinstance(widget,QGroupBox): widget.setTitle(self.t(key))
            else: widget.setText(self.t(key))
        self.count_label.setText(self.t('ws_count',count=len(self.paths))); self.files.setToolTip(self.t('ws_cards_hint'))
        for i in range(self.operation.count()): self.operation.setItemText(i,self.t('ws_op_'+self.operation.itemData(i)))
        self.recipe_combo.setItemText(0,self.t('ws_recipe'))
        self.refresh_steps()
        if hasattr(self,'_status_key'): self.set_status(self._status_key,self._status_detail)
        for dialog in self._dialogs:
            if hasattr(dialog,'set_language'): dialog.set_language(self.language)
        for dialog in self._pickers: self.localize_picker(dialog)
        self.preview_names()
    def set_reduced_motion(self,enabled):
        self.visual.set_reduced_motion(enabled)
        for dialog in self._dialogs:
            if hasattr(dialog,'set_reduced_motion'): dialog.set_reduced_motion(enabled)
        for dialog in self._pickers: set_reduced_motion(dialog,enabled)
    def is_busy(self): return self._busy or any(getattr(d,'is_busy',lambda:False)() for d in self._dialogs)
    def global_busy(self): return bool(self.owner.pending or self.owner.pdf_panel.is_busy() or self.is_busy())
    def choose_files(self):
        paths=self.choose_paths('ws_add')
        if paths: self.add_files(paths)
    def localize_picker(self,dialog):
        dialog.set_language(self.language)
        if dialog.acceptMode()==QFileDialog.AcceptSave:
            dialog.setLabelText(QFileDialog.Accept,self.t('ws_save'))
    def choose_paths(self,title,*,folder=False,save=False,name_filter='',initial='',single=False):
        """기존 공통 선택창의 모델·모션·현지화와 취소 의미를 재사용한다."""
        dialog=make_file_dialog(self,self.t(title),folder=folder,name_filter=name_filter)
        dialog.title_key=title
        if save:
            dialog.setAcceptMode(QFileDialog.AcceptSave); dialog.setFileMode(QFileDialog.AnyFile); dialog.setDefaultSuffix('json')
        elif single: dialog.setFileMode(QFileDialog.ExistingFile)
        if initial:
            if folder: dialog.setDirectory(initial)
            else: dialog.selectFile(initial)
        self._pickers.append(dialog); self.localize_picker(dialog)
        set_reduced_motion(dialog,self.visual.reduced)
        try:
            return dialog.selectedFiles() if dialog.exec()==QFileDialog.Accepted else []
        finally:
            self._pickers.remove(dialog); dialog.deleteLater()
    def add_files(self,paths): self.set_files(self.paths+paths)
    def set_files(self,paths):
        if self._busy: return False
        clean=[]
        for p in paths:
            path=Path(p)
            if path.is_file() and str(path) not in clean: clean.append(str(path))
        self.paths=clean; self.files.clear()
        for path in clean:
            p=Path(path); item=QListWidgetItem(f'{p.suffix[1:].upper() or "FILE"}    {p.name}\n{p.stat().st_size:,} bytes')
            item.setData(Qt.UserRole,path); item.setToolTip(path); item.setSizeHint(QSize(200,58)); self.files.addItem(item)
        if clean: self.files.setCurrentRow(0)
        else: self.preview.clear()
        self.count_label.setText(self.t('ws_count',count=len(clean))); self.preview_names()
        self.visual.respond('file' if clean else 'ready',clean); self.set_status('ws_ready' if clean else 'ws_empty'); return True
    def sync_paths(self,*args):
        self.paths=[self.files.item(i).data(Qt.UserRole) for i in range(self.files.count())]; self.preview_names()
    def remove_files(self):
        selected={i.data(Qt.UserRole) for i in self.files.selectedItems()}; self.set_files([p for p in self.paths if p not in selected])
    def preview_selection(self,*args):
        item=self.files.currentItem()
        if not item: return
        path=item.data(Qt.UserRole); pixmap=QPixmap(path)
        if not pixmap.isNull(): self.preview.setPixmap(pixmap.scaled(260,150,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        else: self.preview.setText(Path(path).suffix[1:].upper()+'\n'+Path(path).name)
    def current_recipe(self):
        from workspace_core import validate_recipe
        return validate_recipe(json.loads(self.recipe_editor.toPlainText()))
    def refresh_steps(self):
        try: steps=json.loads(self.recipe_editor.toPlainText()).get('steps',[])
        except (ValueError,AttributeError): return
        if not isinstance(steps,list): return
        current=self.step_list.currentRow(); self.step_list.clear()
        for i,step in enumerate(steps):
            operation=str(step.get('op','?')) if isinstance(step,dict) else '?'
            key='ws_op_'+operation
            label=self.t(key) if key in TEXT else operation
            self.step_list.addItem(f'{i+1:02d}  {label}')
        if steps: self.step_list.setCurrentRow(min(max(0,current),len(steps)-1))
    def select_step(self,index):
        try:
            step=json.loads(self.recipe_editor.toPlainText())['steps'][index]
            if index>=0: self.operation.setCurrentIndex(self.operation.findData(step['op']))
        except (ValueError,KeyError,IndexError,TypeError): pass
    def default_step(self):
        op=self.operation.currentData()
        defaults={'convert':{'format':self.format.currentData() or 'png'},'rename':{'template':self.name_template.text()},
                  'watermark':{'text':'FlipRing'},'resize':{'width':1200},'normalize_pages':{'page_size':'A4'}}
        return {'op':op,**defaults.get(op,{})}
    def write_recipe(self,recipe): self.recipe_editor.setPlainText(json.dumps(recipe,ensure_ascii=False,indent=2))
    def use_operation(self): self.write_recipe({'version':1,'name':self.operation.currentData(),'steps':[self.default_step()]})
    def use_rename(self): self.operation.setCurrentIndex(self.operation.findData('rename')); self.use_operation()
    def add_step(self):
        try:
            recipe=json.loads(self.recipe_editor.toPlainText()); recipe['steps'].append(self.default_step()); self.write_recipe(recipe)
        except (ValueError,KeyError,TypeError) as exc: self.set_status('ws_failed',str(exc))
    def move_step(self,direction):
        try:
            recipe=json.loads(self.recipe_editor.toPlainText()); i=self.step_list.currentRow(); j=i+direction
            if 0<=i<len(recipe['steps']) and 0<=j<len(recipe['steps']):
                recipe['steps'][i],recipe['steps'][j]=recipe['steps'][j],recipe['steps'][i]; self.write_recipe(recipe); self.step_list.setCurrentRow(j)
        except (ValueError,KeyError,TypeError) as exc: self.set_status('ws_failed',str(exc))
    def remove_step(self):
        try:
            recipe=json.loads(self.recipe_editor.toPlainText()); i=self.step_list.currentRow()
            if i>=0: recipe['steps'].pop(i); self.write_recipe(recipe)
        except (ValueError,KeyError,TypeError) as exc: self.set_status('ws_failed',str(exc))
    def reload_recipes(self):
        from workspace_core import RecipeStore
        self.store=RecipeStore(self.data_dir/'recipes.json')
        try:
            self.saved_recipes=self.store.load(); self.recipe_combo.clear(); self.recipe_combo.addItem(self.t('ws_recipe'),None)
            for recipe in self.saved_recipes: self.recipe_combo.addItem(recipe['name'],recipe)
        except (ValueError,OSError,TypeError) as exc: self.set_status('ws_failed',str(exc))
    def load_selected_recipe(self,index):
        recipe=self.recipe_combo.itemData(index)
        if isinstance(recipe,dict): self.write_recipe(recipe)
    def save_recipe(self):
        try: self.store.save(self.current_recipe()); self.reload_recipes(); return True
        except (ValueError,OSError,TypeError) as exc: self.set_status('ws_failed',str(exc)); return False
    def delete_recipe(self):
        recipe=self.recipe_combo.currentData()
        if recipe:
            try: self.store.delete(recipe['name']); self.reload_recipes()
            except (ValueError,OSError) as exc: self.set_status('ws_failed',str(exc))
    def import_recipe(self):
        paths=self.choose_paths('ws_import',name_filter='JSON (*.json)',single=True)
        if paths:
            path=paths[0]
            try:
                from workspace_core import validate_recipe
                recipe=validate_recipe(json.loads(Path(path).read_text(encoding='utf-8-sig')))
                self.write_recipe(recipe); self.store.save(recipe); self.reload_recipes()
            except (ValueError,OSError) as exc: self.set_status('ws_failed',str(exc))
    def export_recipe(self):
        try: recipe=self.current_recipe()
        except (ValueError,TypeError) as exc: self.set_status('ws_failed',str(exc)); return
        paths=self.choose_paths('ws_export',save=True,name_filter='JSON (*.json)',initial=recipe['name']+'.json')
        if paths:
            path=paths[0]
            try:
                # 사용자가 고른 기존 파일도 조용히 덮어쓰지 않는다.
                with open(path,'x',encoding='utf-8') as stream: json.dump(recipe,stream,ensure_ascii=False,indent=2)
            except OSError as exc: self.set_status('ws_failed',str(exc))
    def preview_names(self):
        if not hasattr(self,'names_preview'): return
        try:
            from workspace_core import preview_names
            names=preview_names(self.paths,self.name_template.text())
            self.names_preview.setText('\n'.join(row['name'] for row in names[:3]) or self.t('ws_name_hint'))
        except (ValueError,OSError) as exc: self.names_preview.setText(str(exc))
    def target(self):
        target={}
        if self.quality_enabled.isChecked(): target.update(quality=self.quality.value(),dpi=self.dpi.value())
        if self.format.currentData(): target['format']=self.format.currentData()
        if self.max_bytes.value(): target['max_bytes']=self.max_bytes.value()*1024
        if self.a4.isChecked(): target['page_size']='A4'
        return target
    def validate_quality_target(self,paths,recipe,target):
        """명시 품질 목표가 문서·텍스트 출력에 붙기 전에 사용자에게 안내한다."""
        if not self.quality_enabled.isChecked(): return
        import engine
        formats={engine.ALIASES.get(Path(path).suffix[1:].lower(),Path(path).suffix[1:].lower()) for path in paths}
        for step in recipe['steps']:
            op=step['op']
            if op in ('convert','ocr'): formats={step.get('format','txt')}
            elif op in ('combine_pdf','compress_pdf'): formats={'pdf'}
            elif op=='normalize_pages' and step.get('page_size','A4')!='original': formats={'pdf'}
            elif op=='receipts_xlsx': formats={'xlsx'}
            elif op=='collage': formats={step.get('format','png')}
            elif op=='gif': formats={'gif'}
            elif op in ('resize','watermark','redact'): formats={'pdf' if fmt=='pdf' else 'png' for fmt in formats}
        if target.get('format'): formats={target['format']}
        if target.get('page_size')=='A4': formats={'pdf'}
        if not formats or not formats <= {'png','jpg','webp','tiff','avif','bmp','gif','pdf'}:
            raise ValueError(self.t('ws_quality_unsupported'))
    def run_recipe(self,checked=False,paths=None,recipe=None):
        if self.global_busy() or self._closed: self.set_status('ws_busy'); return False
        selected=list(paths or self.paths)
        if not selected: self.set_status('ws_empty'); return False
        try:
            from workspace_core import validate_recipe
            request=validate_recipe(recipe) if recipe is not None else self.current_recipe()
            target=self.target()
            self.validate_quality_target(selected,request,target)
        except (ValueError,TypeError,OSError) as exc: self.set_status('ws_failed',str(exc)); return False
        output=str(self.output_dir)
        self._busy=True; self._cancel=threading.Event(); self._active_paths=selected; self.owner.pending+=1
        _ACTIVE_PANELS.add(self)
        self.run_button.setEnabled(False); self.cancel_button.setEnabled(True); self.files.setEnabled(False)
        self.visual.respond('working',selected); self.set_status('ws_working'); self.results.clear(); self.results.hide(); self.result_actions_widget.hide()
        # 입력 스냅샷만 작업자에게 넘기며 Qt 위젯은 GUI 슬롯에서만 갱신한다.
        cancel=self._cancel; bridge=self.bridge
        def work():
            from workspace_core import execute_workspace
            try: result=execute_workspace(selected,request,target=target,output_dir=output,cancel=cancel,on_event=bridge.event.emit)
            except Exception as exc: result={'outputs':[],'status':'failed','error':str(exc),'warnings':[],'constraints_met':False}
            bridge.done.emit(result)
        self._future=self._pool.submit(work); return True
    def on_event(self,event):
        label=str(event.get('label',''))
        key={'_quality':'ws_stage_quality','_size':'ws_stage_size'}.get(label,'ws_op_'+label)
        if key in TEXT: label=self.t(key)
        self.visual.respond('working'); self.set_status('ws_working',f'{event.get("step",0)} / {event.get("total",0)} · {label}')
    def on_done(self,result):
        if not self._busy: return
        self._busy=False; self.owner.pending=max(0,self.owner.pending-1)
        self.run_button.setEnabled(True); self.cancel_button.setEnabled(False); self.files.setEnabled(True)
        outputs=result.get('outputs',[]); state=result.get('status','complete')
        if state in {'completed','success','done'}: state='complete'
        if self._cancel.is_set() and state not in {'failed','complete'}: state='cancelled'
        error=result.get('error','')
        for output in outputs:
            item=QListWidgetItem(Path(output).name); item.setData(Qt.UserRole,output); item.setToolTip(output); self.results.addItem(item)
            self.owner.append_record(self._active_paths[0],output,'')
        if self.results.count():
            self.results.setCurrentRow(0); self.results.show(); self.result_actions_widget.show()
        if error: self.owner.append_record(self._active_paths[0],'',error)
        if state in {'failed','cancelled'} and self.watch_enabled.isChecked(): self.watch_enabled.setChecked(False)
        warnings='\n'.join(str(w) for w in result.get('warnings',[]))
        if result.get('constraints_met') is False and not error: warnings=self.t('ws_constraint')+'\n'+warnings
        self.visual.respond(state if state in {'failed','cancelled'} else 'complete')
        self.set_status('ws_failed' if state=='failed' else 'ws_cancelled' if state=='cancelled' else 'ws_complete',error or warnings)
        self.owner.update_status()
        if self.watch_enabled.isChecked() and self.watch_queue: QTimer.singleShot(0,self.run_watch_next)
        _ACTIVE_PANELS.discard(self)
        if self._closed:
            self._pool.shutdown(wait=False,cancel_futures=True)
            self.close()
    def cancel(self): self._cancel.set(); self.set_status('ws_cancelling')
    def choose_output(self):
        paths=self.choose_paths('ws_output',folder=True,initial=str(self.output_dir))
        if paths:
            folder=paths[0]
            if self.watch_enabled.isChecked(): self.watch_enabled.setChecked(False)
            self.output_dir=Path(folder); self.output_label.setText(folder)
    def choose_watch_folder(self):
        paths=self.choose_paths('ws_watch_folder',folder=True)
        if paths:
            folder=paths[0]
            self.watch_enabled.setChecked(False); self._watch_folder=folder; self.watch_label.setText(folder)
    def toggle_watch(self,enabled):
        if not enabled:
            self.watch_timer.stop(); self.watch_queue.clear(); self.watch_label.setText(self.t('ws_watch_stopped')); return
        try:
            if not hasattr(self,'_watch_folder'): raise ValueError(self.t('ws_watch_choose'))
            self._watch_recipe=self.current_recipe(); self.watcher.configure(self._watch_folder,self.output_dir)
            self.watch_label.setText(str(self.watcher.folder)); self.watch_timer.start()
        except (ValueError,OSError) as exc:
            self.watch_enabled.setChecked(False); self.set_status('ws_failed',str(exc))
    def scan_watch(self):
        try:
            self.watch_queue.extend(p for p in self.watcher.scan() if p not in self.watch_queue); self.run_watch_next()
        except OSError as exc: self.watch_enabled.setChecked(False); self.set_status('ws_failed',str(exc))
    def run_watch_next(self):
        if self.watch_enabled.isChecked() and self.watch_queue and not self.global_busy():
            path=self.watch_queue.pop(0); self.set_files([path]); self.run_recipe(paths=[path],recipe=self._watch_recipe)
    def import_clipboard(self):
        clipboard=QApplication.clipboard(); image=clipboard.image(); mime=clipboard.mimeData()
        if mime.hasUrls(): self.add_files([u.toLocalFile() for u in mime.urls() if u.isLocalFile()]); return
        folder=self.data_dir/'imports'; folder.mkdir(exist_ok=True)
        if not image.isNull():
            path=folder/f'clipboard-{time.time_ns()}.png'
            if not image.save(str(path)): self.set_status('ws_failed',self.t('ws_import_error')); return
        elif clipboard.text():
            path=folder/f'clipboard-{time.time_ns()}.txt'; path.write_text(clipboard.text(),encoding='utf-8')
        else: self.set_status('ws_failed',self.t('ws_clipboard_empty')); return
        self.add_files([str(path)])
    def start_capture(self):
        if self.global_busy(): self.set_status('ws_busy'); return
        from PySide6.QtGui import QCursor
        screen=QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        self._capture=CaptureOverlay(screen,self.language); self._capture.captured.connect(self.capture_ready)
        self._capture.show(); self._capture.activateWindow(); self._capture.setFocus()
    def capture_ready(self,pixmap):
        folder=self.data_dir/'imports'; folder.mkdir(exist_ok=True); path=folder/f'capture-{time.time_ns()}.png'
        if pixmap.isNull() or not pixmap.save(str(path)): self.set_status('ws_failed',self.t('ws_import_error')); return
        self.add_files([str(path)])
    def copy_result(self,as_file):
        item=self.results.currentItem()
        if item is None: return
        path=item.data(Qt.UserRole)
        if not Path(path).is_file(): self.set_status('ws_failed',self.t('ws_missing')); return
        if as_file:
            mime=QMimeData(); mime.setUrls([QUrl.fromLocalFile(path)]); QApplication.clipboard().setMimeData(mime)
        else: QApplication.clipboard().setText(path)
    def open_inspection(self,mode):
        if self.global_busy(): self.set_status('ws_busy'); return
        if not self.paths: self.set_status('ws_empty'); return
        from inspection_ui import InspectionDialog
        dialog=InspectionDialog(self.owner,language=self.language,paths=self.paths.copy(),mode=mode)
        dialog.result_ready.connect(self.owner.append_record); self._dialogs.append(dialog); dialog.show()
    def commands(self):
        return [(self.t('ws_add'),self.choose_files,False),(self.t('ws_clipboard'),self.import_clipboard,False),
                (self.t('ws_capture'),self.start_capture,False),(self.t('ws_run'),self.run_recipe,True),
                *[(self.t(key),lambda m=mode:self.open_inspection(m),True) for mode,key in [('ocr','ws_ocr'),('compare','ws_compare'),('audit','ws_audit'),('redact','ws_redact')]],
                (self.t('ws_wheel'),self.edit_wheel,False)]
    def open_commands(self):
        dialog=CommandDialog(self); dialog.exec()
    def wheel_preferences(self):
        try:
            pref=json.loads(self.owner.settings.value('workspace/wheel','{}'))
            if not isinstance(pref,dict): return {}
            if any(not isinstance(pref.get(key,[]),list) or any(not isinstance(value,str) for value in pref.get(key,[])) for key in ('order','hidden')): return {}
            if not isinstance(pref.get('recipe',''),str): return {}
            return pref
        except (ValueError,TypeError): return {}
    def ordered_formats(self,formats):
        pref=self.wheel_preferences(); order=pref.get('order',[]); hidden=pref.get('hidden',[])
        return sorted([f for f in formats if f not in hidden],key=lambda f:(order.index(f) if f in order else len(order),formats.index(f)))
    def edit_wheel(self):
        import engine
        formats=list(dict.fromkeys(fmt for spec in engine.TABLE.values() for fmt in spec[1].split()))
        pref=self.wheel_preferences(); order=pref.get('order',[]); formats.sort(key=lambda f:order.index(f) if f in order else len(order))
        dialog=QDialog(self); dialog.setWindowTitle(self.t('ws_wheel')); dialog.resize(400,500); layout=QVBoxLayout(dialog)
        layout.addWidget(QLabel(self.t('ws_wheel_hint')))
        values=QListWidget(); values.setDragDropMode(QAbstractItemView.InternalMove); layout.addWidget(values)
        for fmt in formats:
            item=QListWidgetItem(fmt.upper()); item.setData(Qt.UserRole,fmt); item.setFlags(item.flags()|Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked if fmt in pref.get('hidden',[]) else Qt.Checked); values.addItem(item)
        recipes=QComboBox(); recipes.addItem(self.t('ws_no_recipe'),'')
        for recipe in getattr(self,'saved_recipes',[]): recipes.addItem(recipe['name'],recipe['name'])
        recipes.setCurrentIndex(max(0,recipes.findData(pref.get('recipe','')))); layout.addWidget(recipes)
        reset=QPushButton(self.t('ws_reset')); layout.addWidget(reset)
        def reset_all():
            self.owner.settings.remove('workspace/wheel'); self.owner.settings.sync(); dialog.reject()
        reset.clicked.connect(reset_all)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        if dialog.exec()==QDialog.Accepted:
            items=[values.item(i) for i in range(values.count())]
            pref={'order':[i.data(Qt.UserRole) for i in items],'hidden':[i.data(Qt.UserRole) for i in items if i.checkState()!=Qt.Checked],'recipe':recipes.currentData()}
            self.owner.settings.setValue('workspace/wheel',json.dumps(pref)); self.owner.settings.sync()
    def wheel_recipe(self):
        name=self.wheel_preferences().get('recipe')
        return next((r for r in getattr(self,'saved_recipes',[]) if r['name']==name),None)
    def shutdown(self):
        self._closed=True; self.watch_timer.stop(); self._cancel.set(); self.visual.animation.stop()
        if self._capture is not None:
            try: self._capture.close()
            except RuntimeError: pass
        for dialog in self._dialogs:
            if hasattr(dialog,'shutdown'): dialog.shutdown()
        if self._busy:
            if getattr(self,'_future',None) is not None and self._future.cancel():
                self.bridge.done.emit({'status':'cancelled','outputs':[],'constraints_met':False,'warnings':[]})
            return False
        self._pool.shutdown(wait=False,cancel_futures=True)
        return True
    def closeEvent(self,event):
        if self._busy:
            self.shutdown(); event.ignore(); return
        super().closeEvent(event)
