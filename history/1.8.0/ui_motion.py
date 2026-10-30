"""앱 내부 표면의 유한 피드백과 공통 파일 선택창. 실제 입력·파일 처리는 Qt에 맡긴다."""
from __future__ import annotations

from pathlib import Path
import weakref

from PySide6.QtCore import Qt, QObject, QEvent, QVariantAnimation, QEasingCurve, QRectF, QPointF, QTimer, QUrl, QSignalBlocker, QSize
from PySide6.QtGui import QColor, QPainter, QPen, QPainterPath, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QFileDialog,
    QDialogButtonBox, QAbstractItemView, QComboBox, QLineEdit, QAbstractSpinBox,
    QAbstractButton, QProgressBar, QMenu, QToolButton, QFileIconProvider, QMessageBox, QTreeView, QHeaderView,
)
from shiboken6 import isValid
import engine
from i18n import tr


def reduced_motion():
    application = QApplication.instance()
    return bool(application and application.property('flipringReducedMotion'))


def start_motion(animation):
    """감소 모드에서도 완료 신호와 최종 상태를 적용한다."""
    animation.start()
    if reduced_motion():
        animation.setCurrentTime(animation.duration())


def set_reduced_motion(root, enabled):
    application = QApplication.instance()
    if application is None: return
    application.setProperty('flipringReducedMotion', bool(enabled))
    if enabled:
        # 이미 열린 휠·팝업을 포함하며 타이머와 실제 작업 진행은 변경하지 않는다.
        for window in application.topLevelWidgets():
            for animation in window.findChildren(QVariantAnimation):
                if isValid(animation) and animation.state() == QVariantAnimation.Running:
                    animation.setCurrentTime(animation.duration())


SURFACE_STYLE = """
QFileDialog#flipringPicker {background:#fafafa;}
QFileDialog#flipringPicker QWidget {font-family:'SUIT';font-size:13px;color:#262626;}
QFileDialog#flipringPicker QLabel#pickerTitle {font-size:24px;font-weight:600;}
QFileDialog#flipringPicker QLabel#pickerCaption {color:#737373;font-size:12px;}
QFileDialog#flipringPicker QLabel#pickerSummary {color:#646464;font-size:12px;}
QFileDialog#flipringPicker QFrame#pickerHeader {background:transparent;border:0;}
QFileDialog#flipringPicker QAbstractItemView {background:#ffffff;border:1px solid #e7e7e7;border-radius:12px;padding:8px;outline:0;}
QFileDialog#flipringPicker QAbstractItemView::item {min-height:32px;padding:5px 7px;border:0;}
QFileDialog#flipringPicker QAbstractItemView::item:selected {background:#eaeaea;color:#242424;border-radius:6px;}
QFileDialog#flipringPicker QAbstractItemView::item:hover {background:#f3f3f3;}
QFileDialog#flipringPicker QListView#sidebar {background:#f1f1f1;border:0;border-radius:12px;padding:10px;}
QFileDialog#flipringPicker QHeaderView::section {background:#fafafa;border:0;border-bottom:1px solid #ededed;padding:9px;color:#6a6a6a;}
QFileDialog#flipringPicker QHeaderView {padding:0;border:0;border-radius:0;}
QFileDialog#flipringPicker QSplitter::handle {background:transparent;width:14px;}
QFileDialog#flipringPicker QLineEdit,QFileDialog#flipringPicker QComboBox {background:#ffffff;border:1px solid #e4e4e4;border-radius:9px;padding:9px 11px;min-height:18px;}
QFileDialog#flipringPicker QComboBox {padding-right:30px;}
QFileDialog#flipringPicker QComboBox::drop-down {border:0;width:26px;}
QFileDialog#flipringPicker QToolButton {background:#f1f1f1;border:0;border-radius:8px;padding:7px;min-width:20px;min-height:20px;}
QFileDialog#flipringPicker QToolButton:checked {background:#dedede;}
QFileDialog#flipringPicker QPushButton {background:#ffffff;border:1px solid #dedede;border-radius:9px;padding:10px 22px;min-height:18px;font-weight:500;}
QFileDialog#flipringPicker QPushButton[primary="true"] {background:#222222;border-color:#222222;color:#ffffff;}
QFileDialog#flipringPicker QScrollBar:vertical {background:#fafafa;width:7px;}
QFileDialog#flipringPicker QScrollBar::handle:vertical {background:#c4c4c4;min-height:28px;border-radius:3px;}
QFileDialog#flipringPicker QScrollBar::add-line:vertical,QFileDialog#flipringPicker QScrollBar::sub-line:vertical {height:0;}
QFileDialog#flipringPicker QScrollBar::add-page:vertical,QFileDialog#flipringPicker QScrollBar::sub-page:vertical {background:none;}
QMenu {background:#ffffff;color:#262626;border:1px solid #dfdfdf;border-radius:10px;padding:7px;}
QMenu::item {padding:10px 23px;border-radius:7px;}
QMenu::item:selected {background:#ededed;color:#262626;}
QMenu::item:disabled {color:#898989;}
QMenu::separator {height:1px;background:#ededed;margin:5px 10px;}
QMessageBox {background:#fafafa;}
QMessageBox QLabel {font-family:'SUIT';font-size:14px;color:#303030;padding:14px;}
QMessageBox QLabel#messageTitle {font-size:20px;font-weight:600;padding:0;color:#242424;}
QMessageBox QPushButton {font-family:'SUIT';font-size:13px;background:#242424;color:#ffffff;border:0;border-radius:9px;padding:10px 26px;min-height:19px;}
"""


class FeedbackOverlay(QWidget):
    """항목 위치를 바꾸지 않고 테두리·광선만 그리는 입력 투명 레이어."""

    def __init__(self, host):
        super().__init__(host)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.amount = 0.0
        self.rectangle = None
        self.origin = None
        self.travel = 1.0
        self.setGeometry(host.rect())
        self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rectangle = self.current_rectangle()
        painter.setPen(QPen(QColor(54, 54, 54, round(105 * self.amount)), 1.1))
        painter.setBrush(QColor(90, 90, 90, round(8 * self.amount)))
        painter.drawRoundedRect(rectangle, 8, 8)
        painter.setPen(QPen(QColor(42, 42, 42, round(145 * self.amount)), 2, Qt.SolidLine, Qt.RoundCap))
        width = max(0, rectangle.width() - 18) * (0.18 + 0.65 * self.amount)
        painter.drawLine(QPointF(rectangle.left() + 9, rectangle.bottom() - 1),
                         QPointF(rectangle.left() + 9 + width, rectangle.bottom() - 1))
        painter.end()

    def current_rectangle(self):
        """현재 그리는 위치를 재사용해 빠른 행 이동도 그 지점에서 이어간다."""
        rectangle = self.rectangle if self.rectangle is not None else QRectF(self.rect()).adjusted(3, 3, -3, -3)
        if self.origin is not None:
            start = self.origin
            rectangle = QRectF(start.x() + (rectangle.x() - start.x()) * self.travel,
                               start.y() + (rectangle.y() - start.y()) * self.travel,
                               start.width() + (rectangle.width() - start.width()) * self.travel,
                               start.height() + (rectangle.height() - start.height()) * self.travel)
        return rectangle


class SurfaceMotion(QObject):
    """표면이 수명을 소유하며, 새 입력은 현재 프레임부터 유한 피드백으로 이어진다."""

    def __init__(self, widget):
        super().__init__(widget)
        self.host = widget.viewport() if isinstance(widget, QAbstractItemView) else widget
        self.overlay = FeedbackOverlay(self.host)
        self.amount = 0.0
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(280)
        self.animation.setEasingCurve(QEasingCurve.InOutSine)
        self.animation.valueChanged.connect(self._frame)
        self.animation.finished.connect(self.stop)
        widget.installEventFilter(self)
        if self.host is not widget:
            self.host.installEventFilter(self)
        if isinstance(widget, QAbstractItemView):
            self._selection_model = None
            self._model = None
            self._connect_view()
            widget.verticalScrollBar().valueChanged.connect(self.selection_pulse)
        if isinstance(widget, QComboBox):
            widget.currentIndexChanged.connect(self.pulse)
            ensure_surface_motion(widget.view().window())
            install_surface_motions(widget.view())
        elif isinstance(widget, QLineEdit):
            widget.textEdited.connect(self.pulse)
        elif isinstance(widget, QAbstractSpinBox) and hasattr(widget, "valueChanged"):
            widget.valueChanged.connect(self.pulse)
        elif isinstance(widget, QAbstractButton):
            widget.clicked.connect(self.pulse)
        elif isinstance(widget, QProgressBar):
            widget.valueChanged.connect(self.pulse)
        elif isinstance(widget, QMenu):
            widget.hovered.connect(self.menu_pulse)

    def _frame(self, value):
        self.amount = float(value)
        self.overlay.amount = self.amount
        self.overlay.travel = min(1.0, self.animation.currentTime() / 170)
        self.overlay.update()

    def _connect_view(self):
        widget = self.parent()
        selection, model = widget.selectionModel(), widget.model()
        if selection is not None and selection is not self._selection_model:
            selection.selectionChanged.connect(self.selection_pulse)
            selection.currentChanged.connect(self.selection_pulse)
            self._selection_model = selection
        if model is not None and model is not self._model:
            model.rowsInserted.connect(self.selection_pulse)
            model.rowsRemoved.connect(self.selection_pulse)
            model.rowsMoved.connect(self.selection_pulse)
            self._model = model

    def pulse(self, *unused, rectangle=None):
        widget = self.parent()
        if not widget.isVisible():
            return
        current = self.amount
        origin = self.overlay.current_rectangle() if self.overlay.rectangle is not None else None
        self.animation.stop()
        self.overlay.origin = origin if rectangle is not None else None
        self.overlay.rectangle = rectangle
        self.overlay.setGeometry(self.host.rect())
        self.overlay.show()
        self.overlay.raise_()
        # 시작값을 현재 값으로 두므로 반복 입력에서도 밝기가 처음으로 튀지 않는다.
        with QSignalBlocker(self.animation):
            self.animation.setStartValue(current)
            self.animation.setKeyValueAt(0.30, 0.9)
            self.animation.setEndValue(0.0)
            self.animation.setCurrentTime(0)
        self._frame(current)
        start_motion(self.animation)

    def selection_pulse(self, *unused):
        widget = self.parent()
        index = widget.currentIndex()
        rectangle = QRectF(widget.visualRect(index)).adjusted(2, 2, -2, -2) if index.isValid() else None
        self.pulse(rectangle=rectangle)

    def menu_pulse(self, action):
        self.pulse(rectangle=QRectF(self.parent().actionGeometry(action)).adjusted(1, 1, -1, -1))

    def stop(self):
        self.animation.stop()
        self.amount = self.overlay.amount = 0.0
        self.overlay.hide()

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind in (QEvent.Resize, QEvent.Show):
            self.overlay.setGeometry(self.host.rect())
            if kind == QEvent.Show:
                if isinstance(self.parent(), QAbstractItemView):
                    self._connect_view()
                self.pulse()
        elif kind in (QEvent.Enter, QEvent.FocusIn, QEvent.MouseButtonPress, QEvent.KeyPress):
            if self.parent().isEnabled():
                self.pulse()
        elif kind in (QEvent.Hide, QEvent.Close):
            self.stop()
            self.overlay.rectangle = self.overlay.origin = None
            hide_tooltip(self.parent())
        elif kind == QEvent.Leave:
            hide_tooltip(self.parent())
        elif kind == QEvent.EnabledChange and not self.parent().isEnabled():
            self.stop()
        elif kind == QEvent.ToolTip:
            text = self.parent().toolTip()
            if isinstance(self.parent(), QAbstractItemView):
                index = self.parent().indexAt(event.pos())
                text = index.data(Qt.ToolTipRole) if index.isValid() else text
            if text:
                show_tooltip(self.parent(), str(text), event.globalPos())
                event.accept()
                return True
        return False


def ensure_surface_motion(widget):
    motion = getattr(widget, "_flipring_surface_motion", None)
    if motion is None:
        motion = SurfaceMotion(widget)
        widget._flipring_surface_motion = motion
    return motion


def install_surface_motions(root):
    """소유권이 있는 컨트롤과 늦게 생기는 팝업에도 한 번만 연결한다."""
    kinds = (QAbstractItemView, QComboBox, QLineEdit, QAbstractSpinBox, QAbstractButton, QMenu, QProgressBar)
    for widget in [root] + root.findChildren(QWidget):
        if isinstance(widget, kinds):
            # 스크롤바의 상시 이동에는 중복 광선을 만들지 않는다. 스크롤되는 내용은 그대로 갱신된다.
            ensure_surface_motion(widget)
    return ensure_surface_motion(root)


def pulse_widget(widget):
    ensure_surface_motion(widget).pulse()


class MotionSystem(QObject):
    """Qt가 나중에 만드는 메뉴·팝업·편집 도움말까지 같은 앱 표면으로 연결한다."""

    def __init__(self, application, button_installer):
        super().__init__(application)
        self.button_installer = button_installer
        application.installEventFilter(self)

    def eventFilter(self, watched, event):
        if not isinstance(watched, QWidget) or isinstance(watched, FeedbackOverlay):
            return False
        kind = event.type()
        if kind == QEvent.Show:
            if isinstance(watched, (QMenu, QMessageBox)):
                if not watched.property("flipringMotionStyle"):
                    watched.setStyleSheet(watched.styleSheet() + SURFACE_STYLE)
                    watched.setProperty("flipringMotionStyle", True)
                if isinstance(watched, QMessageBox):
                    decorate_message(watched)
                install_surface_motions(watched)
                if self.button_installer is not None:
                    self.button_installer(watched)
            elif isinstance(watched, (QAbstractItemView, QComboBox, QLineEdit, QAbstractSpinBox, QAbstractButton)):
                ensure_surface_motion(watched)
                if self.button_installer is not None:
                    self.button_installer(watched)
        elif kind == QEvent.ToolTip:
            text = watched.toolTip()
            owner = watched
            if isinstance(watched.parentWidget(), QAbstractItemView):
                owner = watched.parentWidget()
            if isinstance(owner, QAbstractItemView):
                index = owner.indexAt(event.pos())
                text = index.data(Qt.ToolTipRole) if index.isValid() else text
            if text:
                show_tooltip(owner, str(text), event.globalPos())
                event.accept()
                return True
        elif kind in (QEvent.Leave, QEvent.Hide, QEvent.MouseButtonPress, QEvent.KeyPress):
            hide_tooltip(watched)
        return False


def install_motion_system(application, button_installer=None):
    system = getattr(application, "_flipring_motion_system", None)
    if system is None:
        application._flipring_motion_system = system = MotionSystem(application, button_installer)
    return system


class StateMark(QWidget):
    """실제 작업 상태의 유한 링·체크·취소 표시. 진행률을 추정하지 않는다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(28, 28)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.state = "ready"
        self.phase = 1.0
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(400)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.valueChanged.connect(self._frame)

        # 첫 틱 지연을 보완하도록400ms 종료 이벤트를 등록한다. 이벤트 루프 지연 시 전달도 늦어질 수 있다.
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.setTimerType(Qt.PreciseTimer)
        self.deadline.timeout.connect(self._finish)
        self.animation.finished.connect(self.deadline.stop)

    def _finish(self):
        self.deadline.stop()
        self.animation.setCurrentTime(self.animation.duration())
        self._frame(1.0)

    def _frame(self, value):
        self.phase = float(value)
        self.update()

    def respond(self, state):
        self.state = state
        self.setAccessibleName(state)
        self.animation.stop()
        self.deadline.stop()
        if self.isVisible():
            self.animation.setCurrentTime(0)
            self._frame(float(self.animation.currentValue()))
            self.deadline.start(self.animation.duration())
            start_motion(self.animation)
        else:
            self._frame(1.0)

    def hideEvent(self, event):
        self.animation.stop()
        self.deadline.stop()
        self._frame(1.0)
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.respond(self.state)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#e4e4e4"), 1.3))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QRectF(3, 3, 22, 22))
        painter.setPen(QPen(QColor("#505050"), 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        if self.state in {"working", "cancelling"}:
            painter.drawArc(QRectF(3, 3, 22, 22), round((1 - self.phase) * 230 * 16), 250 * 16)
            if self.state == "cancelling":
                painter.drawLine(11, 14, 17, 14)
        elif self.state == "complete":
            path = QPainterPath(QPointF(8, 14))
            path.lineTo(12, 18)
            path.lineTo(20, 10)
            painter.setOpacity(0.45 + 0.55 * self.phase)
            painter.drawPath(path)
        elif self.state == "error":
            painter.drawLine(10, 10, 18, 18)
            painter.drawLine(18, 10, 10, 18)
        elif self.state == "cancelled":
            painter.drawLine(10, 14, 18, 14)
        else:
            painter.drawEllipse(QPointF(14, 14), 2.2, 2.2)
        painter.end()


class MotionToolTip(QFrame):
    """앱 소유 도움말. 파일명·경로·오류 문자열을 HTML로 실행하지 않는다."""

    def __init__(self):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setObjectName("flipringTooltip")
        self.setStyleSheet("QFrame#flipringTooltip {background:#242424;border:1px solid #494949;border-radius:10px;}"
                           "QLabel {color:#fafafa;font-family:'SUIT';font-size:12px;background:transparent;}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 11)
        self.label = QLabel()
        self.label.setTextFormat(Qt.PlainText)
        self.label.setWordWrap(True)
        self.label.setMaximumWidth(510)
        layout.addWidget(self.label)
        self.owner = None
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.setInterval(6000)
        self.timeout.timeout.connect(self.hide)
        ensure_surface_motion(self)

    def show_text(self, owner, text, point):
        self.owner = weakref.ref(owner)
        self.label.setText(text)
        available = owner.screen().availableGeometry()
        self.label.setMaximumWidth(max(1, min(510, available.width() - 28)))
        self.adjustSize()
        self.move(max(available.left(), min(point.x() + 12, available.right() - self.width())),
                  max(available.top(), min(point.y() + 18, available.bottom() - self.height())))
        self.show()
        pulse_widget(self)
        self.timeout.start()

    def hideEvent(self, event):
        self.timeout.stop()
        super().hideEvent(event)


def show_tooltip(owner, text, point):
    application = QApplication.instance()
    tooltip = getattr(application, "_flipring_tooltip", None)
    if tooltip is None:
        tooltip = application._flipring_tooltip = MotionToolTip()
        application.aboutToQuit.connect(tooltip.close)
    tooltip.show_text(owner, text, point)
    return tooltip


def hide_tooltip(owner):
    tooltip = getattr(QApplication.instance(), "_flipring_tooltip", None)
    if tooltip is not None and tooltip.owner is not None and tooltip.owner() is owner:
        tooltip.hide()


class PickerMark(QWidget):
    """선택창의 위치 이동과 선택에 반응하는 작은 링. 타이머 반복은 없다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(54, 54)
        self.phase = 1.0
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(380)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.valueChanged.connect(self._frame)

    def _frame(self, value):
        self.phase = float(value)
        self.update()

    def respond(self, *unused):
        self.animation.stop()
        self.animation.setCurrentTime(0)
        self._frame(float(self.animation.currentValue()))
        start_motion(self.animation)

    def hideEvent(self, event):
        self.animation.stop()
        self.phase = 1.0
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.respond()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#242424"))
        painter.drawRoundedRect(QRectF(1, 1, 52, 52), 16, 16)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor("#bfbfbf"), 1.2))
        painter.drawEllipse(QPointF(27, 27), 16, 16)
        painter.setPen(QPen(QColor("#ffffff"), 2, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(QRectF(11, 11, 32, 32), round((1 - self.phase) * 110 * 16), 115 * 16)
        painter.drawLine(23, 27, 31, 27)
        painter.drawLine(27, 23, 27, 31)
        painter.end()


class MonoFileIcons(QFileIconProvider):
    """선택창 내부 파일 표시는 흑백으로 통일하며 실제 파일 형식은 Qt 모델이 보존한다."""

    def __init__(self, language):
        super().__init__()
        self.language = language

    def type(self, info):
        # 폴더는 앱 공통 문구다. 그 밖의 확장자별 형식 이름은 시스템 원문으로 보존한다.
        return tr(self.language, "picker_folder_type") if info.isDir() else super().type(info)

    def icon(self, value):
        folder = value.isDir() if hasattr(value, "isDir") else value in (QFileIconProvider.Folder, QFileIconProvider.Drive)
        cached = getattr(self, '_density_icons', {})
        if folder in cached:
            return cached[folder]
        icon = QIcon()
        # 동일한24논리픽셀 도형에 배율별 실제 픽셀을 제공한다.
        for ratio in (1.0, 1.25, 1.5, 2.0):
            side = round(24 * ratio)
            pixmap = QPixmap(side, side)
            pixmap.setDevicePixelRatio(ratio)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(QColor("#6a6a6a"), 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(QColor("#f5f5f5"))
            if folder:
                path = QPainterPath(QPointF(3, 7))
                for point in ((3, 5), (9, 5), (11, 7), (21, 7), (21, 19), (3, 19)):
                    path.lineTo(*point)
                path.closeSubpath()
                painter.drawPath(path)
            else:
                painter.drawRoundedRect(QRectF(5, 3, 14, 18), 2, 2)
                painter.drawLine(8, 9, 16, 9)
                painter.drawLine(8, 13, 16, 13)
                painter.drawLine(8, 17, 13, 17)
            painter.end()
            icon.addPixmap(pixmap)
        cached[folder] = icon
        self._density_icons = cached
        return icon


class MotionFileDialog(QFileDialog):
    """검증된 QFileDialog 모델과 키 동작을 카드형 작업 공간으로 감싼다."""

    def __init__(self, parent, title, language="ko", *, folder=False, name_filter=""):
        super().__init__(parent)
        self.setOption(QFileDialog.DontUseNativeDialog, True)
        self.setObjectName("flipringPicker")
        self.setProperty("flipringFilePicker", True)
        self.setWindowTitle(title)
        self.setWindowIcon(parent.windowIcon() if parent else QIcon())
        self.language = language
        self.folder_mode = folder
        self.title_key = "pick_folder_title" if folder else "picker_pdf_title" if name_filter else "pick_files_title"
        self._header_configured = False
        self.setFileMode(QFileDialog.Directory if folder else QFileDialog.ExistingFiles)
        self.setOption(QFileDialog.ShowDirsOnly, folder)
        self.setViewMode(QFileDialog.Detail)
        self.resize(900, 650)
        from fixed_viewport import fit_window
        fit_window(self, QSize(900, 650))
        self._icon_provider = MonoFileIcons(language)
        self.setIconProvider(self._icon_provider)
        if name_filter:
            self.setNameFilter(name_filter)
        for role, key in ((QFileDialog.LookIn, "dialog_location"), (QFileDialog.FileName, "dialog_filename"),
                          (QFileDialog.FileType, "dialog_filter"), (QFileDialog.Reject, "cancel"),
                          (QFileDialog.Accept, "dialog_choose" if folder else "dialog_open")):
            self.setLabelText(role, tr(language, key))
        layout = self.layout()
        # 기존 모델·보기·입력을 보존하고 탐색 영역을 헤더 아래로 옮긴다.
        items = []
        while layout.count():
            item = layout.itemAt(0)
            position = layout.getItemPosition(0)
            items.append((layout.takeAt(0), position))
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(13)
        self.header = QFrame()
        self.header.setObjectName("pickerHeader")
        header = QHBoxLayout(self.header)
        header.setContentsMargins(0, 0, 0, 14)
        header.setSpacing(16)
        self.mark = PickerMark()
        header.addWidget(self.mark)
        headings = QVBoxLayout()
        headings.setSpacing(5)
        self.heading = QLabel(title)
        self.heading.setObjectName("pickerTitle")
        headings.addWidget(self.heading)
        self.caption = QLabel(tr(language, "picker_folder_caption" if folder else "picker_caption"))
        self.caption.setObjectName("pickerCaption")
        headings.addWidget(self.caption)
        header.addLayout(headings, 1)
        layout.addWidget(self.header, 0, 0, 1, 4)
        button_box = self.findChild(QDialogButtonBox)
        self._button_box = button_box
        button_box.installEventFilter(self)
        button_box.setOrientation(Qt.Horizontal)
        for item, (row, column, row_span, column_span) in items:
            if item.widget() is button_box:
                continue
            if item.widget() is not None:
                layout.addWidget(item.widget(), row + 1, column, row_span, column_span)
            elif item.layout() is not None:
                layout.addLayout(item.layout(), row + 1, column, row_span, column_span)
            else:
                layout.addItem(item, row + 1, column, row_span, column_span)
        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 8, 0, 0)
        self.summary = QLabel(tr(language, "picker_empty"))
        self.summary.setObjectName("pickerSummary")
        self.summary.setWordWrap(True)
        footer_layout.addWidget(self.summary, 1)
        footer_layout.addWidget(button_box)
        layout.addWidget(footer, layout.rowCount(), 0, 1, 4)
        for button in button_box.buttons():
            if button_box.buttonRole(button) == QDialogButtonBox.AcceptRole:
                button.setProperty("primary", True)
        sidebar = self.findChild(QAbstractItemView, "sidebar")
        if sidebar is not None:
            sidebar.setMinimumWidth(155)
            sidebar.setMaximumWidth(200)
        # Qt의 실제 탐색 동작을 그대로 두고 기본 유색 시스템 아이콘만 바꾼다.
        for name, symbol in (("backButton", "back"), ("forwardButton", "forward"),
                             ("toParentButton", "up"), ("newFolderButton", "folder"),
                             ("listModeButton", "list"), ("detailModeButton", "detail")):
            button = self.findChild(QToolButton, name)
            if button is not None:
                button.setIcon(navigation_icon(symbol))
        arrow = engine.asset("combo-chevron.svg").as_posix()
        self.setStyleSheet(SURFACE_STYLE + '\nQComboBox::down-arrow {image:url("' + arrow + '");width:12px;height:8px;}')
        self.currentChanged.connect(self._selection_changed)
        self.directoryEntered.connect(self._directory_changed)
        self._picker_selection_models = []
        for view in self.findChildren(QAbstractItemView):
            selection = view.selectionModel()
            if view.objectName() in {"listView", "treeView"} and selection is not None and selection not in self._picker_selection_models:
                selection.selectionChanged.connect(self._selection_changed)
                self._picker_selection_models.append(selection)
        filename = self.findChild(QLineEdit, "fileNameEdit")
        if filename is not None:
            filename.textEdited.connect(self._selection_changed)
        install_surface_motions(self)

    def _selection_changed(self, *unused):
        files = self.selectedFiles()
        self.summary.setText(tr(self.language, "picker_selected", count=len(files)) if files else
                             tr(self.language, "picker_empty"))
        self.summary.setToolTip("\n".join(files))
        self.mark.respond()
        pulse_widget(self.summary)

    def _directory_changed(self, path):
        self.mark.respond()
        pulse_widget(self.header)
        self._selection_changed(path)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._header_configured:
            tree = self.findChild(QTreeView, "treeView")
            if tree is not None:
                header = tree.header()
                header.setStretchLastSection(False)
                header.setSectionResizeMode(0, QHeaderView.Interactive)
                for column, width in ((1, 80), (2, 135), (3, 175)):
                    header.setSectionResizeMode(column, QHeaderView.Interactive)
                    header.resizeSection(column, width)
                header.sectionResized.connect(self._keep_name_width)
                tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
                tree.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
            self._header_configured = True
        self._fit_name_column()
        self.mark.respond()

    def _keep_name_width(self, column, old_width, width):
        if column == 0 and width < 180:
            tree = self.findChild(QTreeView, 'treeView')
            if tree is not None:
                tree.header().resizeSection(0, 180)

    def _fit_name_column(self):
        tree = self.findChild(QTreeView, 'treeView')
        if tree is not None:
            header = tree.header()
            others = sum(header.sectionSize(column) for column in range(1, header.count()))
            # 작은 창에서도 이름 열의 폭을 유지하고 나머지 열은 가로로 탐색한다.
            header.resizeSection(0, max(180, tree.viewport().width() - others))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._header_configured:
            self._fit_name_column()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.LanguageChange and hasattr(self, "caption"):
            parent = self.parentWidget()
            language = getattr(parent.window(), "language", self.language) if parent else self.language
            self.set_language(language)

    def eventFilter(self, watched, event):
        if watched is getattr(self, "_button_box", None) and event.type() == QEvent.LanguageChange:
            # 상위 선택창이 모든 버튼 라벨을 관리한다. 표준 Open 재번역으로 폴더의 Choose를 덮지 않는다.
            parent = self.parentWidget()
            language = getattr(parent.window(), "language", self.language) if parent else self.language
            self.set_language(language)
            return True
        return super().eventFilter(watched, event)

    def set_language(self, language):
        self.language = "en" if language == "en" else "ko"
        self._icon_provider.language = self.language
        self.setWindowTitle(tr(self.language, self.title_key))
        self.heading.setText(self.windowTitle())
        for role, key in ((QFileDialog.LookIn, "dialog_location"), (QFileDialog.FileName, "dialog_filename"),
                          (QFileDialog.FileType, "dialog_filter"), (QFileDialog.Reject, "cancel"),
                          (QFileDialog.Accept, "dialog_choose" if self.folder_mode else "dialog_open")):
            self.setLabelText(role, tr(self.language, key))
        self.caption.setText(tr(self.language, "picker_folder_caption" if self.folder_mode else "picker_caption"))
        self._selection_changed()

    def done(self, result):
        parent = self.parentWidget()
        super().done(result)
        # 선택과 취소는 즉시 반환하고, 닫힘 응답은 돌아온 작업 공간에서 유한하게 이어진다.
        if parent is not None and isValid(parent):
            pulse_widget(parent)


def make_file_dialog(parent, title, *, folder=False, name_filter=""):
    return MotionFileDialog(parent, title, getattr(parent, "language", "ko"), folder=folder, name_filter=name_filter)


class MotionMessageBox(QMessageBox):
    """모달 호출이 반환되면 소유한 모션·표면도 지연 해제한다."""

    def exec(self):
        try:
            return super().exec()
        finally:
            self.deleteLater()


def decorate_message(dialog):
    """표준 버튼과 반환 코드는 유지하며 메시지 내부에도 같은 헤더를 제공한다."""
    if hasattr(dialog, "_flipring_message_mark"):
        return
    layout = dialog.layout()
    columns = layout.columnCount()
    items = []
    while layout.count():
        position = layout.getItemPosition(0)
        items.append((layout.takeAt(0), position))
    layout.setContentsMargins(24, 24, 24, 20)
    layout.setSpacing(14)
    header = QWidget(dialog)
    row = QHBoxLayout(header)
    row.setContentsMargins(0, 0, 0, 6)
    row.setSpacing(16)
    mark = PickerMark()
    row.addWidget(mark)
    title = QLabel(dialog.windowTitle())
    title.setObjectName("messageTitle")
    title.setWordWrap(True)
    row.addWidget(title, 1)
    layout.addWidget(header, 0, 0, 1, columns)
    for item, (y, x, height, width) in items:
        if item.widget() is not None:
            widget = item.widget()
            if dialog.icon() == QMessageBox.NoIcon and widget.objectName() == "qt_msgbox_label":
                # 아이콘이 없는 본문은 Qt의 빈 아이콘 열까지 사용한다.
                layout.addWidget(widget, y + 1, 0, height, columns)
            else:
                layout.addWidget(widget, y + 1, x, height, width)
        elif item.layout() is not None:
            layout.addLayout(item.layout(), y + 1, x, height, width)
        else:
            layout.addItem(item, y + 1, x, height, width)
    dialog._flipring_message_mark = mark
    for button in dialog.buttons():
        button.setProperty("primary", True)
    message = dialog.findChild(QLabel, "qt_msgbox_label")
    if message is not None:
        message.setWordWrap(True)
        message.setMaximumWidth(580)
    from fixed_viewport import fit_window
    dialog.adjustSize()
    fit_window(dialog, dialog.size().expandedTo(QSize(420, 1)))
    parent = dialog.parentWidget()
    if parent is not None:
        owner = weakref.ref(parent)
        def returned(*unused):
            target = owner()
            if target is not None and isValid(target):
                pulse_widget(target)
        dialog.finished.connect(returned)
    install_surface_motions(dialog)


def navigation_icon(symbol):
    """선택창 탐색 버튼용 앱 자체 선 아이콘을 그린다."""
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor("#505050"), 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    if symbol in {"back", "forward", "up"}:
        painter.translate(10, 10)
        painter.rotate({"back": 0, "forward": 180, "up": 90}[symbol])
        painter.drawLine(5, 0, -5, 0)
        painter.drawLine(-5, 0, -1, -4)
        painter.drawLine(-5, 0, -1, 4)
    elif symbol == "folder":
        painter.drawRoundedRect(QRectF(2, 5, 16, 12), 2, 2)
        painter.drawLine(3, 5, 8, 5)
        painter.drawLine(8, 5, 8, 3)
        painter.drawLine(10, 8, 10, 14)
        painter.drawLine(7, 11, 13, 11)
    else:
        for y in (5, 10, 15):
            painter.drawPoint(4, y)
            painter.drawLine(8, y, 17 if symbol == "list" else 13, y)
            if symbol == "detail":
                painter.drawPoint(17, y)
    painter.end()
    return QIcon(pixmap)
