"""플립링: 트레이와 원형 메뉴 중심의 무료 Windows 인터페이스."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import math
from ui_motion import start_motion, set_reduced_motion
import os
from pathlib import Path
import subprocess
import sys
import time
import threading
import winreg

from PySide6.QtCore import (
    Qt, QTimer, Signal, QObject, QPointF, QRectF, QSettings, QLockFile,
    QUrl, QVariantAnimation, QEasingCurve, QSignalBlocker, QTranslator, QEvent, QSize,
)
from PySide6.QtGui import (
    QColor, QPainter, QPen, QPainterPath, QFont, QFontDatabase,
    QIcon, QPixmap, QCursor, QDesktopServices, QActionGroup, QPalette,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QComboBox, QListWidget, QTabWidget, QCheckBox,
    QSystemTrayIcon, QMenu, QMessageBox, QProgressBar, QGraphicsOpacityEffect,
    QStylePainter, QStyleOptionButton, QStyle, QFrame, QInputDialog, QListWidgetItem, QScrollArea, QSizePolicy,
)
import engine
from flipring_workflow import PresetStore, preflight, BUILTINS
from preview_panel import PreviewPanel
from fixed_viewport import fit_window, scroll_content
from i18n import tr, error_text, QT_KOREAN
from pdf_panel import PdfToolsPanel
from studio_ui import StudioCard, NavButton, FileDropCard, Toggle, HistoryDelegate, svg_icon
from ui_motion import (make_file_dialog, install_surface_motions, pulse_widget, StateMark,
                       install_motion_system, SURFACE_STYLE, MotionMessageBox, decorate_message)

VERSION = 3
APPNAME = "플립링"
AUTOSTART_NAME = "FlipRing"
DATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "PUVKID" / "DragWheel"
TRIGGER_KEYS = [
    ("Shift", 0x10), ("Alt", 0x12), ("Ctrl", 0x11),
    ("Windows", 0x5B), ("Space", 0x20), ("F8", 0x77), ("custom", -1),
]
USER32 = ctypes.WinDLL("user32", use_last_error=True)
USER32.GetAsyncKeyState.argtypes = [ctypes.c_int]
USER32.GetAsyncKeyState.restype = ctypes.c_short
USER32.GetForegroundWindow.restype = wintypes.HWND
USER32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
OLE32 = ctypes.WinDLL("ole32", use_last_error=True)
OLE32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
OLE32.CoInitializeEx.restype = ctypes.c_int32
OLE32.CoUninitialize.argtypes = []
OLE32.CoUninitialize.restype = None
OLE32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
OLE32.CoTaskMemFree.restype = None
SHELL32 = ctypes.WinDLL("shell32", use_last_error=True)
SHELL32.SHParseDisplayName.argtypes = [
    wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
    wintypes.ULONG, ctypes.POINTER(wintypes.ULONG),
]
SHELL32.SHParseDisplayName.restype = ctypes.c_int32
SHELL32.SHOpenFolderAndSelectItems.argtypes = [
    ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p), wintypes.DWORD,
]
SHELL32.SHOpenFolderAndSelectItems.restype = ctypes.c_int32
EXPLORER_CLASSES = {"CabinetWClass", "ExploreWClass", "Progman", "WorkerW"}


def select_in_explorer(path):
    """파일을 실행하지 않고 탐색기에서 해당 파일을 선택한다."""
    filename = str(Path(path).resolve())

    def check(result, operation):
        # HRESULT는 64비트 Windows에서도 부호 있는 32비트 값이다.
        if ctypes.c_int32(result).value < 0:
            raise OSError(f"{operation} (HRESULT 0x{result & 0xffffffff:08X})")

    check(OLE32.CoInitializeEx(None, 0x2), "CoInitializeEx")
    pidl = ctypes.c_void_p()
    try:
        check(SHELL32.SHParseDisplayName(filename, None, ctypes.byref(pidl), 0, None),
              "SHParseDisplayName")
        if not pidl.value:
            raise OSError("SHParseDisplayName (HRESULT 0x80004005)")
        # cidl=0에서는 전체 파일 PIDL 하나로 부모 폴더를 열고 그 파일을 선택한다.
        check(SHELL32.SHOpenFolderAndSelectItems(pidl, 0, None, 0),
              "SHOpenFolderAndSelectItems")
    finally:
        if pidl.value:
            OLE32.CoTaskMemFree(pidl)
        # S_OK와 S_FALSE를 포함한 성공 초기화마다 해제를 정확히 한 번 수행한다.
        OLE32.CoUninitialize()


def ui_font(size=10, weight=QFont.Normal):
    # 동봉 글꼴은 이 앱에만 등록하며 운영체제 글꼴 설정을 바꾸지 않는다.
    font = QFont()
    font.setFamilies(["SUIT", "Segoe UI", "Malgun Gothic", "맑은 고딕"])
    font.setPointSize(size)
    font.setWeight(weight)
    return font


def apply_application_style(application):
    if not hasattr(application, "_flipring_fonts"):
        application._flipring_fonts = {}
        for style in ("Regular", "Medium", "SemiBold"):
            filename = engine.asset(f"fonts/SUIT-{style}.ttf")
            identifier = QFontDatabase.addApplicationFont(str(filename))
            if identifier < 0:
                raise RuntimeError(f"UI font could not be loaded: {filename}")
            application._flipring_fonts[style] = identifier
    application.setStyle("Fusion")
    application.setFont(ui_font())
    palette = QPalette()
    for role, value in {
        QPalette.Window: "#fafafa", QPalette.WindowText: "#171717",
        QPalette.Base: "#ffffff", QPalette.AlternateBase: "#f0f0f0",
        QPalette.Text: "#171717", QPalette.Button: "#ffffff",
        QPalette.ButtonText: "#171717", QPalette.Highlight: "#242424",
        QPalette.HighlightedText: "#ffffff", QPalette.ToolTipBase: "#171717",
        QPalette.ToolTipText: "#ffffff", QPalette.Link: "#404040",
        QPalette.LinkVisited: "#606060", QPalette.PlaceholderText: "#777777",
        QPalette.BrightText: "#ffffff", QPalette.Light: "#ffffff",
        QPalette.Midlight: "#eeeeee", QPalette.Mid: "#bbbbbb",
        QPalette.Dark: "#888888", QPalette.Shadow: "#333333",
        QPalette.Accent: "#242424",
    }.items():
        palette.setColor(role, QColor(value))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor("#999999"))
    application.setPalette(palette)
    install_motion_system(application, install_button_motions)


class DialogTranslator(QTranslator):
    """앱에서 사용하는 Qt 표준 대화상자의 짧은 문구만 현지화한다."""

    def isEmpty(self):
        return False

    def translate(self, context, sourceText, disambiguation=None, n=-1):
        if context in {"QFileDialog", "QFileSystemModel", "QDialogButtonBox", "QMessageBox", "QLineEdit", "QPlatformTheme"}:
            return QT_KOREAN.get(sourceText.replace("&", ""), sourceText)
        # Python의 빈 문자열은 Qt에서 실제 빈 번역이므로 미지정 문구는 원문을 보존한다.
        return sourceText


def apply_language(language):
    # 파일명·시스템 파일 형식·외부 진단은 사용자 데이터로 보존한다.
    application = QApplication.instance()
    tooltip = getattr(application, "_flipring_tooltip", None)
    if tooltip is not None:
        tooltip.hide()
    previous = getattr(application, "_mono_translator", None)
    if previous is not None:
        application.removeTranslator(previous)
        previous.deleteLater()
    application._mono_translator = None
    if language == "ko":
        translator = DialogTranslator(application)
        application.installTranslator(translator)
        application._mono_translator = translator


def down(vk):
    # 최상위 비트만 사용한다. 하위 비트의 이전 호출 이후 상태는 신뢰하지 않는다.
    return bool(USER32.GetAsyncKeyState(vk) & 0x8000)


def icon(busy=False):
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor("#ffffff" if busy else "#d9d9d9"), 5))
    painter.setBrush(QColor("#202020"))
    painter.drawEllipse(6, 6, 52, 52)
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(22, 22, 20, 20)
    if busy:
        painter.setPen(QPen(QColor("#ffffff"), 6))
        painter.drawArc(6, 6, 52, 52, 30 * 16, 110 * 16)
    painter.end()
    return QIcon(pix)


def message_dialog(parent, title, message):
    # 기본 정보/경고 아이콘의 유색 표시 대신 제목과 본문으로 상태를 전달한다.
    dialog = MotionMessageBox(parent)
    dialog.setWindowTitle(title)
    dialog.setWindowIcon(icon())
    dialog.setText(message)
    dialog.setTextFormat(Qt.PlainText)
    dialog.setIcon(QMessageBox.NoIcon)
    dialog.setStandardButtons(QMessageBox.Ok)
    decorate_message(dialog)
    install_button_motions(dialog)
    dialog.setStyleSheet(SURFACE_STYLE)
    install_surface_motions(dialog)
    return dialog


def file_urls(mime):
    """드롭에 포함된 모든 항목이 존재하는 로컬 파일/폴더인지 확인한다."""
    if not mime.hasUrls():
        return []
    urls = mime.urls()
    if not urls or any(not url.isLocalFile() for url in urls):
        return []
    paths = [url.toLocalFile() for url in urls]
    if any(not path or not Path(path).exists() for path in paths):
        return []
    return list(dict.fromkeys(str(Path(path)) for path in paths))


class Bridge(QObject):
    done = Signal(str, str, str)
    started = Signal(str)


class HistoryList(QListWidget):
    """결과 선택은 왼쪽 더블클릭으로만 실행한다."""

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            super().mouseDoubleClickEvent(event)
        else:
            event.ignore()


class ButtonMotion(QObject):
    """입력 처리는 기본 버튼에 맡기고 배경·테두리만 부드럽게 그린다."""

    def __init__(self, button):
        super().__init__(button)
        button._flipring_button_motion = self
        self.amount = 0.0
        self.hovered = False
        self.pressed = False
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(130)
        self.animation.setEasingCurve(QEasingCurve.InOutSine)
        self.animation.valueChanged.connect(self._frame)
        button.installEventFilter(self)

    @property
    def button(self):
        return self.parent()

    def _frame(self, value):
        self.amount = float(value)
        self.button.update()

    def transition(self):
        target = 1.0 if self.button.isEnabled() and (self.hovered or self.pressed) else 0.0
        self.animation.stop()
        if abs(target - self.amount) < 0.001:
            self.button.update()
            return
        with QSignalBlocker(self.animation):
            self.animation.setStartValue(self.amount)
            self.animation.setEndValue(target)
            self.animation.setCurrentTime(0)
        start_motion(self.animation)

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind in (QEvent.Enter, QEvent.Leave):
            self.hovered = kind == QEvent.Enter
            self.transition()
        elif kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
            if event.button() == Qt.LeftButton:
                self.pressed = kind == QEvent.MouseButtonPress
                self.transition()
        elif kind == QEvent.EnabledChange:
            self.pressed = False
            self.transition()
        elif kind == QEvent.Hide:
            self.animation.stop()
            self.amount = 0.0
            self.hovered = self.pressed = False
        elif kind == QEvent.Paint:
            option = QStyleOptionButton()
            self.button.initStyleOption(option)
            painter = QStylePainter(self.button)
            painter.setRenderHint(QPainter.Antialiasing)
            primary = bool(self.button.property("primary"))
            shade = (28 + round(16 * self.amount) if primary else
                     255 - round(13 * self.amount) - (6 if self.button.isDown() else 0))
            border = shade if primary else 226 - round(25 * self.amount)
            if self.button.hasFocus():
                border = 112
            painter.setBrush(QColor(shade, shade, shade))
            painter.setPen(QColor(border, border, border))
            painter.drawRoundedRect(QRectF(self.button.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
            painter.drawControl(QStyle.CE_PushButtonLabel, option)
            painter.end()
            return True
        return False


def install_button_motions(root):
    """버튼이 모션을 직접 소유하게 하여 중복 등록과 전역 수명 보유를 막는다."""
    buttons = ([root] if isinstance(root, QPushButton) else []) + root.findChildren(QPushButton)
    for button in buttons:
        if getattr(button, "_flipring_button_motion", None) is None:
            button._flipring_button_motion = ButtonMotion(button)


class SoftTabs(QTabWidget):
    """페이지 위치와 입력 영역을 고정한 채 새 내용만 옅게 전환한다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fade = QVariantAnimation(self)
        self.fade.setDuration(140)
        self.fade.setEasingCurve(QEasingCurve.InOutSine)
        self.fade.valueChanged.connect(self._fade_frame)
        self.fade.finished.connect(self._finish_fade)
        self._fade_page = None
        self.currentChanged.connect(self._change_page)

    def _fade_frame(self, value):
        if self._fade_page is not None:
            effect = self._fade_page.graphicsEffect()
            if effect is not None:
                effect.setOpacity(float(value))

    def _finish_fade(self):
        self.fade.stop()
        page, self._fade_page = self._fade_page, None
        if page is not None and page.graphicsEffect() is not None:
            # 정지한 효과의 배경 캐시를 제거하고 투명 페이지의 부모 배경을 갱신한다.
            page.setGraphicsEffect(None)
            self.window().update()

    def _change_page(self, index):
        self._finish_fade()
        page = self.widget(index)
        if page is None or not self.isVisible():
            return
        self._fade_page = page
        effect = QGraphicsOpacityEffect(page)
        effect.setOpacity(0.9)
        page.setGraphicsEffect(effect)
        self.fade.setStartValue(0.9)
        self.fade.setEndValue(1.0)
        start_motion(self.fade)

    def hideEvent(self, event):
        self._finish_fade()
        super().hideEvent(event)


class Wheel(QWidget):
    chosen = Signal(list, str)
    SIDE = 340
    OUTER = 150
    INNER = 52

    def __init__(self, controller):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint |
                         Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.controller = controller
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFixedSize(self.SIDE, self.SIDE)
        self.setWindowTitle(controller.text("wheel_title", app=controller.app_name()))
        self.paths = []
        self.options = []
        self.reasons = {}
        self.hover = -2
        self.preview = False
        self._closing = False
        self._drop_consumed = False
        self.reveal = 0.0
        self.weights = {}
        self._hover_from = {}
        self._hover_to = -2
        self.motion = QVariantAnimation(self)
        self.motion.setEasingCurve(QEasingCurve.InOutSine)
        self.motion.valueChanged.connect(self._motion_frame)
        self.motion.finished.connect(self._motion_finished)
        self.highlight = QVariantAnimation(self)
        self.highlight.setDuration(150)
        self.highlight.setStartValue(0.0)
        self.highlight.setEndValue(1.0)
        self.highlight.setEasingCurve(QEasingCurve.InOutSine)
        self.highlight.valueChanged.connect(self._highlight_frame)

    def _motion_frame(self, value):
        self.reveal = float(value)
        self.update()

    def _motion_finished(self):
        if self._closing and self.reveal <= 0.001:
            self.hide()

    def _animate_reveal(self, target):
        current = self.reveal
        self.motion.stop()
        # 설정을 바꾸는 동안 이전 시각의 값이 프레임으로 전달되지 않게 한다.
        with QSignalBlocker(self.motion):
            self.motion.setDuration(max(55, round((250 if target else 190) * abs(target - current))))
            self.motion.setStartValue(current)
            self.motion.setEndValue(target)
            self.motion.setCurrentTime(0)
        start_motion(self.motion)

    def _highlight_frame(self, value):
        progress = float(value)
        keys = set(self._hover_from) | {self._hover_to}
        self.weights = {
            key: self._hover_from.get(key, 0.0) * (1.0 - progress)
                 + (progress if key == self._hover_to else 0.0)
            for key in keys if key != -2
        }
        self.update()

    def set_hover(self, hit):
        if hit == self.hover:
            return
        self.hover = hit
        self.highlight.stop()
        self._hover_from = self.weights.copy()
        self._hover_to = hit
        start_motion(self.highlight)
        self.update()

    def display(self, pos, paths=None, preview=False):
        continuing = self.isVisible()
        self.motion.stop()
        if not continuing:
            self.highlight.stop()
        self._closing = False
        self._drop_consumed = False
        self.preview = preview
        if not continuing:
            self.reveal = 0.0
            self.hover = self._hover_to = -2
            self.weights = {}
            self._hover_from = {}
        self.set_paths(paths or [])
        self.setAcceptDrops(True)
        screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
        bounds = screen.availableGeometry()
        x = max(bounds.left(), min(pos.x() - self.width() // 2, bounds.right() + 1 - self.width()))
        y = max(bounds.top(), min(pos.y() - self.height() // 2, bounds.bottom() + 1 - self.height()))
        self.move(x, y)
        self.show()
        self.raise_()
        # 퇴장·등장 도중 다시 열어도 현재 프레임부터 이어서 표시한다.
        self._animate_reveal(1.0)

    def dismiss(self):
        if not self.isVisible() or self._closing:
            return
        self._closing = True
        # 드롭을 확정한 뒤에는 퇴장 중인 그림이 새 드롭을 받아서는 안 된다.
        self.setAcceptDrops(False)
        self._animate_reveal(0.0)

    def hideEvent(self, event):
        self.motion.stop()
        self.highlight.stop()
        super().hideEvent(event)

    def set_paths(self, paths):
        paths = list(dict.fromkeys(str(Path(path)) for path in paths))
        same_paths = paths == self.paths
        previous_options = self.options
        self.paths = paths
        self.options = engine.targets(self.paths)
        self.reasons = {}
        for target in self.options:
            self.reasons[target] = next(
                (missing for path in self.paths if (missing := engine.requirement(path, target))), None)
        if same_paths and self.options == previous_options:
            # 같은 파일의 도구 상태는 갱신하되 진행 중인 강조는 초기화하지 않는다.
            self.update()
            return
        # 드래그 대상 변경 시 이전 형식의 강조가 새 형식에 남지 않게 한다.
        self.highlight.stop()
        self.weights = {}
        self.hover = -2
        self.update()

    def region(self, point):
        dx = point.x() - self.width() / 2
        dy = point.y() - self.height() / 2
        radius = math.hypot(dx, dy)
        if radius <= self.INNER:
            return -1
        if radius > self.OUTER or not self.options:
            return -2
        angle = math.atan2(dx, -dy) % (2 * math.pi)
        return min(len(self.options) - 1, int(angle / (2 * math.pi) * len(self.options)))

    def _valid_drop(self, event):
        if self._closing or self._drop_consumed or not (event.possibleActions() & Qt.CopyAction):
            return []
        return file_urls(event.mimeData())

    @staticmethod
    def _accept_copy(event):
        # Shift가 제안한 MoveAction 대신 CopyAction을 명시하여 원본 이동을 막는다.
        event.setDropAction(Qt.CopyAction)
        event.accept()

    def dragEnterEvent(self, event):
        paths = self._valid_drop(event)
        if not paths:
            event.ignore()
            return
        self.set_paths(paths)
        self.set_hover(self.region(event.position()))
        self._accept_copy(event)

    def dragMoveEvent(self, event):
        if not self._valid_drop(event):
            event.ignore()
            return
        self.set_hover(self.region(event.position()))
        # 중앙과 비활성 영역도 복사 드롭을 소비하며 변환하지 않는다.
        self._accept_copy(event)

    def dragLeaveEvent(self, event):
        self.set_hover(-2)
        event.accept()

    def dropEvent(self, event):
        paths = self._valid_drop(event)
        if not paths:
            event.ignore()
            return
        self.set_paths(paths)
        hit = self.region(event.position())
        self._accept_copy(event)
        self._drop_consumed = True
        self.dismiss()
        if 0 <= hit < len(self.options):
            target = self.options[hit]
            if not self.reasons[target]:
                self.chosen.emit(self.paths.copy(), target)
            else:
                self.controller.notify(self.controller.text("helper_title"),
                                       self.controller.text("helper_message", tool=self.reasons[target]))

    def mouseMoveEvent(self, event):
        if self.preview and not self._closing:
            self.set_hover(self.region(event.position()))

    def mouseReleaseEvent(self, event):
        if not self.preview or self._closing or event.button() != Qt.LeftButton:
            return
        hit = self.region(event.position())
        self._drop_consumed = True
        self.dismiss()
        if 0 <= hit < len(self.options):
            target = self.options[hit]
            if not self.reasons[target]:
                self.chosen.emit(self.paths.copy(), target)
            else:
                self.controller.notify(self.controller.text("helper_title"),
                                       self.controller.text("helper_message", tool=self.reasons[target]))

    @staticmethod
    def _wedge(center, outer, inner, start, step):
        path = QPainterPath()
        rect = QRectF(center - outer, center - outer, outer * 2, outer * 2)
        small = QRectF(center - inner, center - inner, inner * 2, inner * 2)
        path.arcMoveTo(rect, 90 - start)
        path.arcTo(rect, 90 - start, -step)
        path.arcTo(small, 90 - start - step, step)
        path.closeSubpath()
        return path

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        center = self.width() / 2
        # 창 좌표·크기·전체 opacity는 고정한다. 옅은 바탕은 모션 중에도 드롭 영역을 유지한다.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(24, 24, 24, 8))
        painter.drawEllipse(QPointF(center, center), self.OUTER, self.OUTER)
        painter.setOpacity(self.reveal)
        scale = 0.94 + 0.06 * self.reveal
        painter.translate(center, center)
        painter.scale(scale, scale)
        painter.translate(-center, -center)
        painter.setBrush(QColor(25, 25, 25, 248))
        painter.setPen(QPen(QColor(255, 255, 255, 42), 1))
        painter.drawEllipse(QPointF(center, center), self.OUTER - 1, self.OUTER - 1)
        count = len(self.options)
        outer = self.OUTER - 5
        inner = self.INNER + 6
        for index, fmt in enumerate(self.options):
            start = index * 360 / count
            step = 360 / count
            weight = self.weights.get(index, 0.0)
            if weight > 0.001:
                color = QColor("#606060" if not self.reasons[fmt] else "#555555")
                color.setAlphaF(0.86 * weight)
                painter.fillPath(self._wedge(center, outer, inner, start, step), color)
            if count > 1:
                radians = math.radians(start)
                painter.setPen(QPen(QColor(255, 255, 255, 28), 1))
                painter.drawLine(
                    QPointF(center + inner * math.sin(radians), center - inner * math.cos(radians)),
                    QPointF(center + outer * math.sin(radians), center - outer * math.cos(radians)))
            radians = math.radians(start + step / 2)
            radius = (inner + outer) / 2 + 3 * weight
            x = center + radius * math.sin(radians)
            y = center - radius * math.cos(radians)
            missing = self.reasons[fmt]
            ink = 150 if missing else 242
            painter.setPen(QColor(ink, ink, ink))
            painter.setFont(ui_font(9 if count > 7 else 10, QFont.Medium))
            painter.drawText(QRectF(x - 49, y - (19 if missing else 12), 98, 24), Qt.AlignCenter, fmt.upper())
            if missing:
                painter.setFont(ui_font(6))
                painter.drawText(QRectF(x - 54, y + 4, 108, 20), Qt.AlignCenter,
                                 self.controller.text("needs_tool", tool=missing))
        cancel = self.weights.get(-1, 0.0)
        painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
        shade = 43 + int(28 * cancel)
        painter.setBrush(QColor(shade, shade, shade, 245))
        painter.drawEllipse(QPointF(center, center), self.INNER, self.INNER)
        if len(self.paths) > 1:
            label = self.controller.text("file_count", count=len(self.paths))
        elif self.paths and self.options:
            label = engine.classify(self.paths[0])[1].upper()
        else:
            label = "FlipRing"
        painter.setPen(QColor("#ababab"))
        painter.setFont(ui_font(7))
        painter.drawText(QRectF(center - 49, center - 35, 98, 20), Qt.AlignCenter, label)
        active = 0 <= self.hover < count and not self.reasons[self.options[self.hover]]
        painter.setPen(Qt.white)
        painter.setFont(ui_font(12 if active else 18, QFont.Medium))
        painter.drawText(QRectF(center - 51, center - 14, 102, 28), Qt.AlignCenter,
                         "→ " + self.options[self.hover].upper() if active else "×")
        painter.setPen(QColor("#c7c7c7"))
        painter.setFont(ui_font(7))
        painter.drawText(QRectF(center - 50, center + 17, 100, 21), Qt.AlignCenter,
                         self.controller.text("drop_convert" if active else "cancel"))
        if not self.options:
            painter.drawText(QRectF(28, center + 83, self.width() - 56, 30), Qt.AlignCenter,
                             self.controller.text("drag_inside"))
        painter.end()


class MainWindow(QMainWindow):
    """상주 컨트롤러와 파일·문서 작업 공간. 변환 선택은 원형 메뉴에서 수행한다."""

    def __init__(self):
        super().__init__()
        DATA.mkdir(parents=True, exist_ok=True)
        self.settings = QSettings(str(DATA / f"settings-{VERSION}.ini"), QSettings.IniFormat)
        self.language = "en" if self.settings.value("language", "ko") == "en" else "ko"
        apply_language(self.language)
        self._translated_widgets = []
        self.last_result = None
        self.recorded_key = None
        self.setWindowTitle(self.text("settings_title", app=self.app_name()))
        self.setWindowIcon(icon())
        self.setAcceptDrops(True)
        self.resize(1160, 820)
        self.setFont(ui_font())
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="변환")
        self.bridge = Bridge()
        self.bridge.done.connect(self.finished)
        self.bridge.started.connect(self.job_started)
        self.jobs = []
        self.selection_issue = ""
        self.presets = PresetStore(DATA / "presets.json")
        self.pending = 0
        self.paths = []
        self.start_point = None
        self.drag_fired = False
        self.release_time = None
        self.explorer_drag = False
        self.recording = False
        self.record_until = 0
        self.wheel = Wheel(self)
        self.wheel.chosen.connect(self.enqueue)
        self.history_path = DATA / "history.json"
        try:
            records = json.loads(self.history_path.read_text(encoding="utf-8"))
            if not isinstance(records, list) or any(
                not isinstance(row, dict) or any(not isinstance(row.get(key), str)
                                               for key in ("time", "source", "output", "error"))
                for row in records
            ):
                raise ValueError("기록 형식 오류")
            self.records = records[-200:]
        except FileNotFoundError:
            self.records = []
        except (ValueError, OSError):
            self.records = []
            self.history_error = True

        host = QWidget()
        self.viewport_scroll = scroll_content(host, QSize(960, 740))
        self.viewport_scroll.setObjectName('fixedViewport')
        self.setCentralWidget(self.viewport_scroll)
        shell = QHBoxLayout(host)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(204)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(16, 28, 16, 22)
        sidebar_layout.setSpacing(6)
        self.brand = QLabel()
        self.brand.setObjectName("brand")
        sidebar_layout.addWidget(self.brand)
        side_caption = self.localized(QLabel(), "studio_workspace")
        side_caption.setObjectName("sideCaption")
        sidebar_layout.addWidget(side_caption)
        sidebar_layout.addSpacing(30)
        self.nav_buttons = {}
        for index, symbol in ((0, "convert"), (4, "pdf"), (2, "history"), (1, "tools"), (3, "about")):
            button = NavButton(symbol)
            filename = {"convert": "arrow-left-right", "pdf": "scan-text", "history": "rotate-ccw-clock",
                        "tools": "sliders-horizontal", "about": "info"}[symbol]
            button.set_svg(engine.asset("lucide/" + filename + ".svg"))
            button.clicked.connect(lambda checked=False, target=index: self.tabs.setCurrentIndex(target))
            self.nav_buttons[index] = button
            sidebar_layout.addWidget(button)
        sidebar_layout.addStretch()
        maker = self.localized(QLabel(), "studio_maker")
        maker.setObjectName("sideMaker")
        sidebar_layout.addWidget(maker)
        local = self.localized(QLabel(), "studio_local")
        local.setObjectName("sideCaption")
        sidebar_layout.addWidget(local)
        shell.addWidget(self.sidebar)
        content = QWidget()
        content.setObjectName("workspace")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(30, 28, 30, 20)
        layout.setSpacing(22)
        header = QHBoxLayout()
        headings = QVBoxLayout()
        headings.setSpacing(6)
        self.page_title = QLabel()
        self.page_title.setObjectName("pageTitle")
        headings.addWidget(self.page_title)
        self.page_description = QLabel()
        self.page_description.setObjectName("muted")
        self.page_description.setWordWrap(True)
        headings.addWidget(self.page_description)
        header.addLayout(headings, 1)
        self.key_badge = QLabel()
        self.key_badge.setObjectName("keyBadge")
        header.addWidget(self.key_badge, 0, Qt.AlignTop)
        layout.addLayout(header)
        header_line = QFrame()
        header_line.setObjectName('workspaceDivider')
        header_line.setFrameShape(QFrame.HLine)
        layout.addWidget(header_line)
        shell.addWidget(content, 1)
        self.subtitle = QLabel()
        self.subtitle.setObjectName("muted")
        self.subtitle.setWordWrap(True)
        self.tabs = SoftTabs()
        self.tabs.tabBar().hide()
        layout.addWidget(self.tabs, 1)
        settings_page = QWidget()
        workspace_row = QVBoxLayout(settings_page)
        workspace_row.setContentsMargins(0, 0, 0, 0)
        workspace_row.setSpacing(20)
        workspace_row.setAlignment(Qt.AlignTop)
        self.drop_card = FileDropCard(file_urls, Wheel._accept_copy)
        self.drop_card.orbit.setMinimumHeight(56)
        self.drop_card.orbit.setMaximumHeight(56)
        self.drop_card.orbit.hide()
        self.drop_card.setMaximumHeight(210)
        self.drop_card.clicked.connect(self.pick_files)
        self.drop_card.files_dropped.connect(self.receive_files)
        self.localized(self.drop_card.title, "studio_drop_title")
        self.localized(self.drop_card.caption, "studio_drop_caption")
        workspace_row.addWidget(self.drop_card)
        self.quick_settings = StudioCard()
        self.quick_settings.setMinimumWidth(286)
        settings_layout = QVBoxLayout(self.quick_settings)
        settings_layout.setContentsMargins(20, 22, 20, 22)
        settings_layout.setSpacing(8)
        quick_heading = self.localized(QLabel(), "studio_quick_settings")
        quick_heading.setObjectName("cardTitle")
        settings_layout.addWidget(quick_heading)
        settings_layout.addWidget(self.subtitle)
        settings_layout.addSpacing(6)
        settings_layout.addWidget(self.localized(QLabel(), "language"))
        self.language_combo = QComboBox()
        self.language_combo.addItem("한국어", "ko")
        self.language_combo.addItem("English", "en")
        self.language_combo.setCurrentIndex(self.language_combo.findData(self.language))
        self.language_combo.currentIndexChanged.connect(self.language_changed)
        settings_layout.addWidget(self.language_combo)
        settings_layout.addWidget(self.localized(QLabel(), "trigger_label"))
        self.trigger = QComboBox()
        for label, code in TRIGGER_KEYS:
            self.trigger.addItem(self.text("custom") if code == -1 else label, code)
        try:
            saved = int(self.settings.value("trigger", 0x10))
            self.custom_vk = int(self.settings.value("custom_vk", 0x77))
        except (TypeError, ValueError):
            saved, self.custom_vk = 0x10, 0x77
        index = self.trigger.findData(saved)
        self.trigger.setCurrentIndex(index if index >= 0 else 0)
        self.trigger.currentIndexChanged.connect(self.trigger_changed)
        settings_layout.addWidget(self.trigger)
        self.record_button = self.button(self.text("record"), self.record_key)
        settings_layout.addWidget(self.record_button)
        self.auto = self.localized(Toggle(), "auto")
        self.auto.setChecked(self.autostart_enabled())
        self.auto.toggled.connect(self.autostart)
        settings_layout.addWidget(self.auto)
        self.reveal = self.localized(Toggle(), "reveal")
        self.reveal.setChecked(self.settings.value("reveal", False, type=bool))
        self.reveal.toggled.connect(lambda value: self.settings.setValue("reveal", value))
        settings_layout.addWidget(self.reveal)
        self.notifications = self.localized(Toggle(), "notifications")
        self.notifications.setChecked(self.settings.value("notify", True, type=bool))
        self.notifications.toggled.connect(lambda value: self.settings.setValue("notify", value))
        settings_layout.addWidget(self.notifications)
        settings_layout.addStretch()
        self.reduced_motion_toggle = self.localized(Toggle(), 'reduce_motion')
        self.reduced_motion_toggle.setChecked(self.settings.value('reduced_motion', False, type=bool))
        self.reduced_motion_toggle.toggled.connect(self.motion_changed)
        settings_layout.insertWidget(settings_layout.count() - 1, self.reduced_motion_toggle)
        self.build_workbench(workspace_row)
        row = QHBoxLayout()
        row.setContentsMargins(12, 16, 12, 0)
        choose = self.localized(self.button("", self.pick_files), "pick_files")
        choose.setProperty("primary", True)
        choose.setIcon(svg_icon(engine.asset("lucide/file-up.svg"), "#ffffff"))
        self.choose_button = choose
        row.addWidget(choose)
        self.folder_button = self.localized(self.button("", self.pick_folder), "pick_folder")
        self.folder_button.setIcon(svg_icon(engine.asset("lucide/folder-open.svg")))
        row.addWidget(self.folder_button)
        self.drop_card.body.addLayout(row)
        self.selection_label = self.localized(QLabel(), "studio_no_selection")
        self.selection_label.setAlignment(Qt.AlignCenter)
        self.selection_label.setObjectName("muted")
        self.drop_card.body.addWidget(self.selection_label)
        work_scroll = QScrollArea()
        work_scroll.setFrameShape(QFrame.NoFrame)
        work_scroll.setWidgetResizable(True)
        work_scroll.setWidget(settings_page)
        self.tabs.addTab(work_scroll, self.text("studio_convert"))

        tools_page = QWidget()
        tools_layout = QVBoxLayout(tools_page)
        tools_layout.setContentsMargins(0, 0, 0, 0)
        tools_layout.setSpacing(16)
        self.tool_labels = {}
        for name, (title, package, purpose) in engine.TOOLS.items():
            card = StudioCard()
            row = QHBoxLayout(card)
            row.setContentsMargins(22, 20, 22, 20)
            details = QVBoxLayout()
            title_label = QLabel(title)
            title_label.setObjectName("cardTitle")
            details.addWidget(title_label)
            details.addWidget(self.localized(QLabel(), "purpose_" + name))
            row.addLayout(details, 1)
            row.addWidget(self.localized(self.button("", lambda checked=False, pkg=package:
                                      self.copy_install_command(pkg)), "install_command"))
            tools_layout.addWidget(card)
            status = QLabel()
            status.setObjectName("muted")
            status.setWordWrap(True)
            self.tool_labels[name] = status
            details.addWidget(status)
        note = self.localized(QLabel(), "tools_note")
        note.setWordWrap(True)
        note.setObjectName("muted")
        tools_layout.addWidget(note)
        tools_layout.addWidget(self.localized(self.button("", self.refresh_tools), "refresh_tools"))
        tools_layout.addStretch()
        self.tabs.addTab(scroll_content(tools_page), self.text("tools"))

        history_page = QWidget()
        history_layout = QVBoxLayout(history_page)
        history_layout.setContentsMargins(0, 0, 0, 0)
        self.history = HistoryList()
        self.history.setItemDelegate(HistoryDelegate(self.history))
        self.history.itemDoubleClicked.connect(self.open_history_result)
        history_layout.addWidget(self.history)
        history_layout.addWidget(self.localized(QLabel(), "recent_note"))
        self.tabs.addTab(history_page, self.text("history"))
        about_page = QWidget()
        about_outer = QVBoxLayout(about_page)
        about_outer.setContentsMargins(0, 0, 0, 0)
        about_card = StudioCard()
        about_layout = QVBoxLayout(about_card)
        about_layout.setContentsMargins(30, 30, 30, 30)
        about = self.localized(QLabel(), "about_text")
        about.setWordWrap(True)
        about.setObjectName("aboutBody")
        about_layout.addWidget(about)
        about_layout.addWidget(self.localized(self.button("", self.open_licenses), "licenses"))
        about_outer.addWidget(about_card)
        about_outer.addStretch()
        self.tabs.addTab(scroll_content(about_page), self.text("about"))
        self.pdf_panel = PdfToolsPanel(self.language, self)
        self.pdf_panel.scroll.widget().layout().setContentsMargins(0, 0, 0, 0)
        self.pdf_panel.scroll.widget().layout().setSpacing(20)
        self.pdf_panel.form.setVerticalSpacing(12)
        self.pdf_panel.form.setHorizontalSpacing(14)
        self.pdf_panel.result_ready.connect(self.pdf_finished)
        self.pdf_panel.activity_changed.connect(self.pdf_activity_changed)
        self.tabs.addTab(self.pdf_panel, self.text("pdf_tools"))
        self.pdf_panel.preset_requested.connect(self.save_pdf_preset)
        preferences = QScrollArea()
        preferences.setWidgetResizable(True)
        preferences.setFrameShape(QFrame.NoFrame)
        preferences.setWidget(self.quick_settings)
        self.tabs.addTab(preferences, self.text('settings'))
        settings_nav = NavButton('tools')
        settings_nav.set_svg(engine.asset('lucide/sliders-horizontal.svg'))
        settings_nav.clicked.connect(lambda: self.tabs.setCurrentIndex(5))
        self.nav_buttons[5] = settings_nav
        sidebar_layout.insertWidget(sidebar_layout.count() - 3, settings_nav)
        self.tabs.currentChanged.connect(self.update_navigation)
        footer = QHBoxLayout()
        self.status_mark = StateMark()
        footer.addWidget(self.status_mark)
        self.status = QLabel(self.text("ready"))
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        footer.addWidget(self.status, 1)
        self.original_badge = self.localized(QLabel(), "studio_originals")
        self.original_badge.setObjectName("muted")
        footer.addWidget(self.original_badge)
        layout.addLayout(footer)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.tray = QSystemTrayIcon(icon(), self)
        self.tray_menu = QMenu()
        self.tray_menu.aboutToShow.connect(self.update_tray_menu)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.setToolTip(self.app_name())
        self.tray.activated.connect(self.tray_activated)
        self.update_tray_menu()
        self.tray.show()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(30)
        self.refresh_tools()
        self.refresh_history()
        self.apply_style()
        install_button_motions(self)
        install_surface_motions(self)
        for widget in (self.status, self.selection_label, self.page_title, self.page_description,
                       self.key_badge, self.record_button):
            pulse_widget(widget)
        self.retranslate()
        self.motion_changed(self.reduced_motion_toggle.isChecked())
        # 본문도 같은 논리 크기를 유지하고 작은 화면에서만 바깥으로 스크롤한다.
        host.setFixedSize(1160, 820)
        self.viewport_scroll.setWidgetResizable(False)
        fit_window(self, QSize(1160, 820), fixed=True)

    def section_heading(self, key):
        label = self.localized(QLabel(), key)
        label.setObjectName('sectionHeading')
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return label

    def build_workbench(self, layout):
        self.workbench = QWidget()
        body = QVBoxLayout(self.workbench)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)
        body.addWidget(self.section_heading('section_queue'))
        self.queue_list = QListWidget()
        self.queue_list.setMinimumHeight(80)
        self.queue_list.setMaximumHeight(90)
        self.queue_list.currentRowChanged.connect(self.preview_selection)
        body.addWidget(self.queue_list)
        body.addWidget(self.section_heading('section_execute'))
        row = QHBoxLayout()
        self.output_combo = QComboBox()
        row.addWidget(self.localized(QLabel(), 'output_format'))
        row.addWidget(self.output_combo)
        self.run_button = self.localized(self.button('', self.run_selected), 'run_selected')
        self.run_button.setProperty('primary', True)
        row.addWidget(self.run_button)
        self.cancel_button = self.localized(self.button('', self.cancel_jobs), 'cancel_queue')
        row.addWidget(self.cancel_button)
        self.retry_button = self.localized(self.button('', self.retry_failed), 'retry_failed')
        row.addWidget(self.retry_button)
        body.addLayout(row)
        self.preflight_label = self.localized(QLabel(), 'estimate_note')
        self.preflight_label.setWordWrap(True)
        body.addWidget(self.preflight_label)
        body.addWidget(self.section_heading('section_preview'))
        self.preview_panel = PreviewPanel()
        self.preview_panel.reveal_requested.connect(self.reveal_preview)
        body.addWidget(self.preview_panel, 1)
        layout.addWidget(self.workbench, 1)
        self.workbench.hide()
        preset_row = QHBoxLayout()
        self.preset_combo = QComboBox()
        preset_row.addWidget(self.preset_combo, 1)
        preset_row.addWidget(self.localized(self.button('', self.apply_selected_preset), 'preset_apply'))
        preset_row.addWidget(self.localized(self.button('', self.save_conversion_preset), 'preset_save'))
        preset_row.addWidget(self.localized(self.button('', self.delete_selected_preset), 'preset_delete'))
        layout.insertLayout(1, preset_row)
        self.preset_heading = self.section_heading('section_presets')
        layout.insertWidget(1, self.preset_heading)

    def motion_changed(self, enabled):
        self.settings.setValue('reduced_motion', bool(enabled))
        self.settings.sync()
        set_reduced_motion(self, enabled)
        self.pdf_panel.set_reduced_motion(enabled)

    def run_selected(self):
        fmt = self.output_combo.currentData()
        if fmt: self.enqueue(self.paths, fmt)

    def refresh_queue(self):
        selected = self.queue_list.currentRow()
        with QSignalBlocker(self.queue_list):
            self.queue_list.clear()
            for entry in self.jobs:
                state = self.text('job_' + entry['state'])
                summary = f"{Path(entry['source']).name}  ·  {entry['format'].upper()}  ·  {state}"
                if entry['error']: summary += ' · ' + error_text(self.language, entry['error'])[:100]
                item = QListWidgetItem(summary)
                report = entry.get('check')
                detail = error_text(self.language, entry['error']) if entry['error'] else entry['output']
                if report and report['estimated']:
                    detail += '\n' + self.text('space_estimate', needed=f"{report['estimated'] / 1048576:.1f}", free=f"{report['free'] / 1048576:.1f}")
                item.setToolTip(detail)
                self.queue_list.addItem(item)
            if self.jobs: self.queue_list.setCurrentRow(max(0, min(selected, len(self.jobs) - 1)))
        busy = bool(self.pending)
        self.run_button.setEnabled(not busy and bool(self.output_combo.currentData()))
        self.cancel_button.setEnabled(busy or any(row['state'] == 'waiting' for row in self.jobs))
        self.retry_button.setEnabled(not busy and any(row['state'] == 'failed' and row['format'] for row in self.jobs))
        self.output_combo.setEnabled(not busy)

    def preview_selection(self, *unused):
        index = self.queue_list.currentRow()
        if 0 <= index < len(self.jobs):
            entry = self.jobs[index]
            self.preview_panel.set_paths(entry['source'], entry['output'])
            report = entry.get('check')
            self.preflight_label.setText(self.text('space_estimate', needed=f"{report['estimated'] / 1048576:.1f}", free=f"{report['free'] / 1048576:.1f}") if report and report['estimated'] else self.text(self.selection_issue or 'estimate_note'))

    def cancel_jobs(self):
        for entry in self.jobs:
            if entry['state'] in ('waiting', 'processing'):
                entry['cancel'].set()
                entry['state'] = 'cancelling' if entry['scheduled'] else 'cancelled'
        self.refresh_queue()

    def retry_failed(self):
        if self.pending: return
        failed = [row for row in self.jobs if row['state'] == 'failed' and row['format']]
        if not failed: return
        # 한 번의 실행은 같은 출력 형식으로 생성되므로 실패 항목만 재등록한다.
        self.enqueue([row['source'] for row in failed], failed[0]['format'])

    def reveal_preview(self, path):
        try: select_in_explorer(path)
        except (OSError, ValueError) as exc:
            message_dialog(self, self.text('history_explorer_title'), str(exc)).exec()

    def refresh_presets(self):
        old = self.preset_combo.currentData()
        self.preset_combo.clear()
        for row in BUILTINS:
            self.preset_combo.addItem(self.text(row['name']), row)
        for row in self.presets.items: self.preset_combo.addItem(row['name'], row)
        if old:
            for index in range(self.preset_combo.count()):
                if self.preset_combo.itemData(index) == old: self.preset_combo.setCurrentIndex(index)
        self.preset_combo.setToolTip(self.text('preset_corrupt') if self.presets.error else '')

    def apply_selected_preset(self):
        if self.pending or self.pdf_panel.is_busy(): return
        preset = self.preset_combo.currentData()
        if not preset: return
        if preset['kind'] == 'pdf':
            if self.pdf_panel.apply_preset(preset['options']):
                if self.paths: self.pdf_panel.set_files(self.paths)
                self.tabs.setCurrentIndex(4)
            return
        index = self.output_combo.findData(preset['format'])
        if index < 0:
            message_dialog(self, self.text('preset_apply'), self.text('preset_incompatible')).exec()
            return
        self.output_combo.setCurrentIndex(index)

    def save_conversion_preset(self):
        fmt = self.output_combo.currentData()
        if fmt: self.save_pdf_preset({'kind': 'convert', 'format': fmt, 'options': {}})

    def save_pdf_preset(self, preset):
        name, accepted = QInputDialog.getText(self, self.text('preset_save'), self.text('preset_name'))
        if not accepted: return
        try:
            self.presets.save(dict(preset, name=name))
            self.refresh_presets()
        except (ValueError, OSError) as exc:
            message_dialog(self, self.text('preset_save'), self.text('preset_invalid') + '\n' + error_text(self.language, str(exc))).exec()

    def delete_selected_preset(self):
        value = self.preset_combo.currentData()
        if value and value in self.presets.items:
            try:
                self.presets.delete(value['name'])
                self.refresh_presets()
            except (ValueError, OSError) as exc:
                message_dialog(self, self.text('preset_delete'), str(exc)).exec()

    def update_navigation(self, index):
        for target, button in self.nav_buttons.items():
            button.setChecked(target == index)
        keys = {0: "studio_convert", 1: "studio_helpers", 2: "history", 3: "about", 4: "pdf_tools", 5: "settings"}
        self.page_title.setText(self.text(keys[index]))
        self.page_description.setText(self.text("studio_description_" + str(index)))
        pulse_widget(self.page_title)

    def text(self, message_id, **values):
        return tr(self.language, message_id, **values)

    def app_name(self):
        return self.text("app")

    def localized(self, widget, key, prefix=""):
        self._translated_widgets.append((widget, key, prefix))
        widget.setText(prefix + self.text(key, app=self.app_name()))
        return widget

    def language_changed(self):
        self.set_language(self.language_combo.currentData())

    def set_language(self, language):
        language = "en" if language == "en" else "ko"
        if self.language == language:
            return
        self.language = language
        self.settings.setValue("language", language)
        self.settings.sync()
        self.retranslate()

    def retranslate(self):
        # 표시 문자열만 갱신한다. 항목 재생성·키 데이터 변경·자동 시작 토글은 하지 않는다.
        apply_language(self.language)
        with QSignalBlocker(self.language_combo):
            self.language_combo.setCurrentIndex(self.language_combo.findData(self.language))
        with QSignalBlocker(self.trigger):
            self.trigger.setItemText(self.trigger.findData(-1), self.text("custom"))
        self.setWindowTitle(self.text("settings_title", app=self.app_name()))
        self.brand.setText(self.app_name())
        self.wheel.setWindowTitle(self.text("wheel_title", app=self.app_name()))
        for widget, key, prefix in self._translated_widgets:
            widget.setText(prefix + self.text(key, app=self.app_name()))
        for index, key in enumerate(("studio_convert", "tools", "history", "about", "pdf_tools", "settings")):
            self.tabs.setTabText(index, self.text(key))
        for index, key in ((0, "studio_convert"), (1, "studio_helpers"), (2, "history"), (3, "about"), (4, "pdf_tools"), (5, "settings")):
            self.nav_buttons[index].setText(self.text(key))
        self.update_navigation(self.tabs.currentIndex())
        self.update_selection_label()
        self.pdf_panel.set_language(self.language)
        self.update_record_label()
        self.record_button.setToolTip(self.text("original_note"))
        self.update_trigger_hint()
        self.render_tools()
        self.refresh_history()
        self.update_status()
        self.update_tray_menu(refresh=False)
        self.wheel.update()
        self.preview_panel.set_language(self.language)
        self.refresh_presets()
        self.refresh_queue()
        self.preview_selection()

    def update_record_label(self):
        key = "record_wait" if self.recording else "recorded" if self.recorded_key is not None else "record"
        self.record_button.setText(self.text(key, key=self.recorded_key))
        pulse_widget(self.record_button)

    def update_status(self):
        before = self.status.text()
        if self.pending:
            self.status.setText(self.text("queue", count=self.pending))
            self.tray.setToolTip(self.app_name() + " · " + self.text("converting", count=self.pending))
        elif self.pdf_panel.is_busy() or getattr(self, "_pdf_activity", "ready") in {"cancelling", "cancelled"}:
            self.status.setText(self.pdf_panel.status.text())
            self.tray.setToolTip(self.app_name())
        elif self.last_result is not None:
            output, error = self.last_result
            self.status.setText(self.text("failed_status", error=error_text(self.language, error)[:90]) if error
                                else self.text("done_status", name=Path(output).name))
            self.tray.setToolTip(self.app_name())
        else:
            self.status.setText(self.text("ready"))
            self.tray.setToolTip(self.app_name())
        state = ("working" if self.pending else self.pdf_panel.status_mark.state
                 if self.pdf_panel.is_busy() or getattr(self, "_pdf_activity", "ready") in {"cancelling", "cancelled"}
                 else "error" if self.last_result and self.last_result[1] else "complete" if self.last_result else "ready")
        if before != self.status.text() or self.status_mark.state != state:
            self.status_mark.respond(state)
            pulse_widget(self.status)

    @staticmethod
    def button(text, action):
        button = QPushButton(text)
        button.setMinimumHeight(35)
        button.clicked.connect(action)
        return button

    @staticmethod
    def install_command(package):
        return f"winget install --id {package} -e --source winget --accept-package-agreements --accept-source-agreements"

    def copy_install_command(self, package):
        QApplication.clipboard().setText(self.install_command(package))
        self.status.setText(self.text("command_copied"))
        self.status_mark.respond("complete")
        pulse_widget(self.status)

    def apply_style(self):
        style = """
        QWidget {font-family:'SUIT','Segoe UI','Malgun Gothic';font-size:13px;font-weight:400;color:#242424;}
        QMainWindow {background:#f6f6f6;}
        QMenu {background:#fafafa;}
        QFrame#sidebar {background:#191919;border:0;border-right:1px solid #424242;}
        QFrame#workspaceDivider {color:#d7d7d7;background:#d7d7d7;max-height:1px;border:0;}
        QLabel#sectionHeading {font-size:12px;font-weight:600;color:#505050;padding:7px 0 5px 0;border-bottom:1px solid #dedede;}
        QLabel#brand {font-size:24px;font-weight:600;color:#f5f5f5;padding:0 10px 3px 10px;}
        QLabel#sideCaption {color:#969696;font-size:11px;padding:0 10px;}
        QLabel#sideMaker {color:#dedede;font-size:12px;padding:0 10px;}
        QLabel#pageTitle {font-size:29px;font-weight:600;color:#202020;}
        QLabel#muted {color:#707070;font-size:12px;}
        QLabel#keyBadge {background:#eeeeee;border-radius:9px;padding:9px 13px;color:#5e5e5e;font-size:11px;}
        QFrame#studioCard,QFrame#dropCard {background:#ffffff;border:1px solid #e7e7e7;border-radius:18px;}
        QLabel#cardTitle {font-size:16px;font-weight:600;color:#242424;}
        QLabel#dropTitle {font-size:21px;font-weight:500;color:#242424;}
        QLabel#aboutBody {font-size:15px;color:#404040;}
        QTabWidget::pane {border:0;background:transparent;}
        QTabBar::tab {background:transparent;padding:12px 12px;color:#626262;font-weight:500;}
        QTabBar::tab:selected {color:#242424;border-bottom:1px solid #4a4a4a;}
        QPushButton {background:#ffffff;border:1px solid #e2e2e2;border-radius:8px;padding:8px 12px;font-weight:500;min-height:18px;}
        QPushButton[primary="true"] {background:#202020;border-color:#202020;color:#ffffff;}
        QPushButton:disabled {color:#8a8a8a;}
        QComboBox:focus,QLineEdit:focus,QSpinBox:focus {border-color:#888888;}
        QListWidget,QComboBox,QLineEdit,QSpinBox {background:#ffffff;border:1px solid #e2e2e2;border-radius:8px;padding:8px;}
        QComboBox {padding-right:30px;}
        QComboBox:disabled {color:#8a8a8a;background:#fafafa;}
        QComboBox::drop-down {subcontrol-origin:padding;subcontrol-position:top right;width:24px;border:0;background:transparent;}
        QSpinBox#pdfNumeric {padding-right:28px;min-height:20px;}
        QSpinBox#pdfNumeric::up-button {subcontrol-origin:padding;subcontrol-position:top right;width:22px;height:18px;border:0;background:transparent;}
        QSpinBox#pdfNumeric::down-button {subcontrol-origin:padding;subcontrol-position:bottom right;width:22px;height:18px;border:0;background:transparent;}
        QSpinBox#pdfNumeric::up-arrow,QSpinBox#pdfNumeric::down-arrow {image:none;}
        QListWidget::item {padding:10px;border-bottom:1px solid #f0f0f0;}
        QListWidget::item:selected {background:#efefef;color:#242424;}
        QComboBox QAbstractItemView {background:#ffffff;color:#242424;selection-background-color:#ededed;selection-color:#242424;}
        QScrollArea {border:0;background:transparent;}
        QScrollBar:vertical {background:#f7f7f7;width:7px;margin:3px 0;}
        QScrollBar::handle:vertical {background:#c5c5c5;min-height:24px;border-radius:3px;}
        QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0;}
        QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {background:none;}
        QCheckBox {spacing:9px;padding:4px 0;}
        QCheckBox::indicator {width:14px;height:14px;border:1px solid #aaaaaa;border-radius:4px;background:#ffffff;}
        QCheckBox::indicator:checked {background:#383838;border-color:#383838;}
        QCheckBox::indicator:hover {border-color:#626262;}
        QMenu {border:1px solid #e2e2e2;padding:6px;}
        QMenu::item {padding:9px 18px;}
        QMenu::item:selected {background:#ededed;border-radius:6px;}
        QMenu::item:disabled {color:#888888;}
        QProgressBar {max-height:3px;border:0;border-radius:1px;background:#e9e9e9;}
        QProgressBar::chunk {background:#4a4a4a;}
        QToolTip {background:#242424;color:#ffffff;border:0;padding:7px;}
        """
        # 따옴표로 감싼 절대 경로는 한글·공백이 있는 소스/배포 경로에서도 유지된다.
        arrow = engine.asset("combo-chevron.svg").as_posix()
        style += '\nQComboBox::down-arrow {image:url("' + arrow + '");width:12px;height:8px;}'
        self.setStyleSheet(style)
        self.tray_menu.setStyleSheet(style)
        self.tray_menu.setStyleSheet(self.tray_menu.styleSheet() + SURFACE_STYLE)

    def update_tray_menu(self, refresh=True):
        if refresh or not hasattr(self, "_tool_paths"):
            self._tool_paths = {name: engine.tool(name) for name in engine.TOOLS}
            self.render_tools()
        menu = self.tray_menu
        previous_menus = [action.menu() for action in menu.actions() if action.menu() is not None]
        menu.clear()
        # QAction 제거만으로는 부모가 소유한 하위 메뉴가 소멸하지 않는다.
        for previous in previous_menus:
            previous.deleteLater()
        title = menu.addAction(self.app_name())
        title.setEnabled(False)
        label = self.trigger.currentText()
        if self.trigger.currentData() == -1:
            label += f" ({self.custom_vk})"
        hint = menu.addAction(self.text("tray_hint", key=label))
        hint.setEnabled(False)
        if self.pending:
            status = menu.addAction(self.text("converting", count=self.pending))
            status.setEnabled(False)
        menu.addSeparator()
        menu.addAction(self.text("pick_files_menu"), self.pick_files)
        menu.addAction(self.text("pick_folder_menu"), self.pick_folder)
        trigger_menu = menu.addMenu(self.text("drag_key"))
        group = QActionGroup(trigger_menu)
        group.setExclusive(True)
        for index, (text, code) in enumerate(TRIGGER_KEYS):
            action = trigger_menu.addAction(self.text("custom") if code == -1 else text)
            action.setCheckable(True)
            action.setChecked(code == self.trigger.currentData())
            group.addAction(action)
            if code == -1:
                action.triggered.connect(lambda: (self.open_page(5), self.record_key()))
            else:
                action.triggered.connect(lambda checked=False, value=index: self.trigger.setCurrentIndex(value))
        # 메뉴가 살아 있는 동안 배타적 선택 그룹도 유지한다.
        trigger_menu._action_group = group
        for key, checkbox in [("auto_menu", self.auto),
                              ("reveal_menu", self.reveal), ("notify_menu", self.notifications)]:
            action = menu.addAction(self.text(key))
            action.setCheckable(True)
            action.setChecked(checkbox.isChecked())
            action.triggered.connect(checkbox.setChecked)
        tools_menu = menu.addMenu(self.text("helpers"))
        for name, (title, package, purpose) in engine.TOOLS.items():
            installed = bool(self._tool_paths[name])
            action = tools_menu.addAction(("✓ " if installed else "✗ ") + title + " · " + self.text("purpose_" + name))
            action.setEnabled(False)
            if not installed:
                tools_menu.addAction(self.text("copy_install", tool=title), lambda checked=False, pkg=package:
                                     self.copy_install_command(pkg))
        tools_menu.addAction(self.text("details"), lambda: self.open_page(1))
        menu.addSeparator()
        menu.addAction(self.text("history"), lambda: self.open_page(2))
        menu.addAction(self.text("pdf_tools"), lambda: self.open_page(4))
        menu.addAction(self.text("settings"), lambda: self.open_page(5))
        menu.addAction(self.text("about"), lambda: self.open_page(3))
        menu.addSeparator()
        menu.addAction(self.text("quit"), self.quit)
        install_surface_motions(menu)

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.open_page(0)

    def trigger_changed(self):
        self.settings.setValue("trigger", self.trigger.currentData())
        self.update_trigger_hint()

    def update_trigger_hint(self):
        label = self.trigger.currentText()
        if self.trigger.currentData() == -1:
            label = self.text("custom_hint", key=self.custom_vk)
        self.subtitle.setText(self.text("drag_hint", key=label))
        self.key_badge.setText(self.text("studio_key_badge", key=label))

    def open_page(self, index):
        self.tabs.setCurrentIndex(index)
        if index == 1:
            self.refresh_tools()
        self.open_window()

    def open_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def quit(self):
        if self.pending or self.pdf_panel.is_busy():
            message_dialog(self, self.text("busy_title"), self.text("busy_message")).exec()
            return
        self.timer.stop()
        self.wheel.hide()
        self.pool.shutdown(wait=False)
        self.tray.hide()
        QApplication.quit()

    def open_licenses(self):
        folder = Path(sys.executable).parent / "licenses" if getattr(sys, "frozen", False) else Path(__file__).parent / "licenses"
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def refresh_tools(self):
        self._tool_paths = {name: engine.tool(name) for name in engine.TOOLS}
        self.render_tools()
        self.update_tray_menu(refresh=False)

    def render_tools(self):
        """언어 변경은 관측을 다시 그린다. 명시 새로고침·트레이 열기는 실제 도구를 다시 찾는다."""
        for name, label in self.tool_labels.items():
            path = self._tool_paths.get(name)
            label.setText(self.text("available" if path else "not_installed"))
            label.setToolTip(path or "")
            pulse_widget(label)

    def pick_files(self):
        dialog = self.file_dialog(False)
        try:
            if dialog.exec() == QFileDialog.Accepted:
                self.set_files(dialog.selectedFiles())
                self.preview()
        finally:
            dialog.deleteLater()

    def pick_folder(self):
        dialog = self.file_dialog(True)
        try:
            if dialog.exec() == QFileDialog.Accepted:
                self.set_files(dialog.selectedFiles())
                self.preview()
        finally:
            dialog.deleteLater()

    def file_dialog(self, folder):
        dialog = make_file_dialog(self, self.text("pick_folder_title" if folder else "pick_files_title"), folder=folder)
        install_button_motions(dialog)
        return dialog

    def set_files(self, paths):
        if self.pending: return
        self.paths = list(dict.fromkeys(str(Path(path)) for path in paths))
        self.jobs = [dict(source=path, format='', state='waiting', output='', error='', cancel=threading.Event(), scheduled=False) for path in self.paths]
        self.update_selection_label()
        self.selection_issue = ''
        for entry in self.jobs:
            try:
                if not Path(entry['source']).exists(): raise ValueError('입력이 없거나 이동되었습니다.')
                engine.classify(entry['source'])
            except (ValueError, OSError) as exc:
                entry.update(state='failed', error=str(exc))
        options = engine.targets(self.paths)
        if self.paths and not options:
            self.selection_issue = 'selection_no_common'
            for entry in self.jobs:
                if not entry['error']:
                    entry.update(state='failed', error='선택한 파일들에 공통으로 사용할 수 있는 출력 형식이 없습니다.')
        self.output_combo.clear()
        for value in options: self.output_combo.addItem(value.upper(), value)
        self.workbench.setVisible(bool(self.paths))
        self.drop_card.title.setVisible(not self.paths)
        self.drop_card.caption.setVisible(not self.paths)
        self.selection_label.setVisible(not self.paths)
        self.drop_card.body.setContentsMargins(12, 4, 12, 8) if self.paths else self.drop_card.body.setContentsMargins(26, 20, 26, 24)
        self.drop_card.setMaximumHeight(80 if self.paths else 210)
        self.refresh_queue()
        if self.jobs: self.queue_list.setCurrentRow(0)
        self.preview_selection()
        self.drop_card.orbit.respond(options if self.paths else None)

    def update_selection_label(self):
        self.selection_label.setText(self.text("file_count", count=len(self.paths)) if self.paths
                                     else self.text("studio_no_selection"))
        pulse_widget(self.selection_label)

    def receive_files(self, paths):
        self.set_files(paths)
        self.preview()

    def dragEnterEvent(self, event):
        if event.possibleActions() & Qt.CopyAction and file_urls(event.mimeData()):
            Wheel._accept_copy(event)
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        paths = file_urls(event.mimeData())
        if not paths or not (event.possibleActions() & Qt.CopyAction):
            event.ignore()
            return
        Wheel._accept_copy(event)
        self.set_files(paths)
        self.preview()

    def preview(self):
        if not self.paths or not engine.targets(self.paths):
            self.notify(self.text("unsupported_title"), self.text("unsupported_message"))
            return
        self.wheel.display(QCursor.pos(), self.paths, preview=True)

    def enqueue(self, paths, fmt):
        if self.pending or self.pdf_panel.is_busy():
            message_dialog(self, self.text('busy_title'), self.text('busy_message')).exec()
            return
        self._pdf_activity = 'ready'
        selected = []
        for path in dict.fromkeys(str(Path(p)) for p in paths):
            entry = next((row for row in self.jobs if row['source'] == path), None)
            if entry is None:
                entry = dict(source=path, format=fmt, state='waiting', output='', error='', cancel=threading.Event(), scheduled=False)
                self.jobs.append(entry)
            if entry['state'] == 'complete': continue
            entry.update(format=fmt, error='', output='', scheduled=False)
            entry['cancel'] = threading.Event()
            report = preflight(path, fmt)
            entry['check'] = report
            if not report['ok']:
                entry.update(state='failed', error=report['error'])
                self.append_record(path, '', report['error'])
                continue
            entry.update(state='waiting', scheduled=True)
            selected.append(entry)
        self.pending = len(selected)
        self.workbench.setVisible(bool(self.jobs))
        self.refresh_queue()
        if not selected:
            self.update_status()
            return
        self.drop_card.orbit.respond(state='working')
        for entry in selected:
            def job(row=entry):
                try:
                    if row['cancel'].is_set(): raise engine.Cancelled('작업이 취소되었습니다.')
                    self.bridge.started.emit(row['source'])
                    result = engine.convert(row['source'], row['format'], cancel=row['cancel'])
                    self.bridge.done.emit(row['source'], result, '')
                except Exception as exc:
                    self.bridge.done.emit(row['source'], '', str(exc))
            self.pool.submit(job)
        self.progress.show()
        self.update_status()
        self.tray.setIcon(icon(busy=True))

    def job_started(self, source):
        entry = next((row for row in self.jobs if row['source'] == source and row['scheduled']), None)
        if entry:
            entry['state'] = 'cancelling' if entry['cancel'].is_set() else 'processing'
            self.refresh_queue()

    def finished(self, source, output, error):
        entry = next((row for row in self.jobs if row['source'] == source and row['scheduled']), None)
        if entry:
            entry.update(state='complete' if output else 'cancelled' if entry['cancel'].is_set() else 'failed',
                         output=output, error=error, scheduled=False)
        self.pending = max(0, self.pending - 1)
        self.append_record(source, output, error)
        self.update_status()
        self.refresh_queue()
        self.preview_selection()
        self.drop_card.orbit.respond(state='working' if self.pending else 'error' if error else 'complete')
        if not self.pending:
            self.progress.hide()
            self.tray.setToolTip(self.app_name())
            self.tray.setIcon(icon())

    def pdf_finished(self, source, output, error):
        # PDF 패널의 자체 작업 큐는 기존 파일 변환 pending에 합산하지 않는다.
        self.append_record(source, output, error)
        self.update_status()
        self.drop_card.orbit.respond(state=self.pdf_panel.status_mark.state if self.pdf_panel.is_busy()
                                     else "error" if error else "complete")

    def pdf_activity_changed(self, state):
        self._pdf_activity = state
        self.update_status()
        if not self.pending:
            self.drop_card.orbit.respond(state=state if state != "ready" else "file")

    def append_record(self, source, output, error):
        """두 변환 경로의 결과를 기존 기록 스키마로 저장한다."""
        record = {"time": datetime.now().isoformat(timespec="seconds"),
                  "source": source, "output": output, "error": error}
        self.records.append(record)
        self.records = self.records[-200:]
        try:
            if not hasattr(self, "history_error"):
                temp = self.history_path.with_suffix(".tmp")
                temp.write_text(json.dumps(self.records, ensure_ascii=False, indent=2), encoding="utf-8")
                temp.replace(self.history_path)
        except OSError as exc:
            self.notify(self.text("save_history_title"), error_text(self.language, str(exc)))
        self.refresh_history()
        self.last_result = (output, error)
        if error:
            self.notify(self.text("failed_title"), f"{Path(source).name}\n{error_text(self.language, error)}")
        else:
            self.notify(self.text("done_title"), Path(output).name)
            if self.reveal.isChecked():
                try:
                    select_in_explorer(output)
                except (OSError, ValueError) as exc:
                    message_dialog(self, self.text("history_explorer_title"),
                                   self.text("history_explorer_error", detail=str(exc))).exec()

    def refresh_history(self):
        self.history.clear()
        for row in reversed(self.records):
            self.history.addItem(row["time"].replace("T", "  ") + "   " + Path(row["source"]).name +
                                 "\n" + (self.text("history_failed", error=error_text(self.language, row["error"]))
                                         if row["error"] else "→ " + row["output"]))
            item = self.history.item(self.history.count() - 1)
            item.setData(Qt.UserRole, row["output"])
            item.setData(Qt.UserRole + 1, row["error"])
            item.setData(Qt.UserRole + 2, True)
            item.setData(Qt.UserRole + 3, {
                "source": Path(row["source"]).name, "format": Path(row["output"] or row["source"]).suffix[1:].upper(),
                "time": row["time"].replace("T", "  "),
                "detail": self.text("history_failed", error=error_text(self.language, row["error"]))
                if row["error"] else Path(row["output"]).name,
            })
            item.setToolTip(row["source"] + "\n" + (error_text(self.language, row["error"]) if row["error"] else row["output"]))
        if hasattr(self, "history_error"):
            self.history.addItem(self.text("history_error"))
        pulse_widget(self.history)

    def open_history_result(self, item):
        if item is None or item.data(Qt.UserRole + 2) is not True:
            return
        output = item.data(Qt.UserRole)
        error = item.data(Qt.UserRole + 1)
        if error:
            message_dialog(self, self.text("history_no_result_title"),
                           self.text("history_no_result")).exec()
            return
        try:
            result = Path(output) if isinstance(output, str) and output else None
            if result is None or not result.is_file():
                message_dialog(self, self.text("history_missing_title"),
                               self.text("history_missing_result")).exec()
                return
            select_in_explorer(result)
        except (OSError, ValueError) as exc:
            message_dialog(self, self.text("history_explorer_title"),
                           self.text("history_explorer_error", detail=str(exc))).exec()

    def notify(self, title, message):
        if self.notifications.isChecked():
            self.tray.showMessage(title, message, QSystemTrayIcon.Information, 5000)

    def autostart_enabled(self):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                return bool(winreg.QueryValueEx(key, AUTOSTART_NAME)[0])
        except FileNotFoundError:
            return False

    def autostart(self, value):
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                if value:
                    command = subprocess.list2cmdline([sys.executable] +
                              ([] if getattr(sys, "frozen", False) else [str(Path(__file__).resolve())]) + ["--tray"])
                    winreg.SetValueEx(key, AUTOSTART_NAME, 0, winreg.REG_SZ, command)
                else:
                    try:
                        winreg.DeleteValue(key, AUTOSTART_NAME)
                    except FileNotFoundError:
                        pass
        except OSError as exc:
            self.auto.blockSignals(True)
            self.auto.setChecked(not value)
            self.auto.blockSignals(False)
            message_dialog(self, self.text("autostart_failed"), error_text(self.language, str(exc))).exec()

    def record_key(self):
        self.recording = True
        self.record_until = time.monotonic() + 10
        self.update_record_label()

    def poll(self):
        now = time.monotonic()
        if self.recording:
            if now > self.record_until or down(0x1B):
                self.recording = False
                self.update_record_label()
                return
            for vk in range(8, 255):
                if vk != 0x1B and down(vk):
                    self.custom_vk = vk
                    self.settings.setValue("custom_vk", vk)
                    self.trigger.setCurrentIndex(self.trigger.findData(-1))
                    self.recording = False
                    self.recorded_key = vk
                    self.update_record_label()
                    break
            return
        # 미리보기에서도 Esc가 닫히도록 마우스 버튼 분기 전에 검사한다.
        if down(0x1B):
            self.wheel.dismiss()
            self.drag_fired = True
        held = down(1)
        pos = QCursor.pos()
        if not held:
            if self.start_point is not None:
                self.release_time = now
            self.start_point = None
            self.drag_fired = False
            self.explorer_drag = False
            if (self.wheel.isVisible() and not self.wheel.preview and
                    self.release_time is not None and now - self.release_time >= 0.35):
                self.wheel.dismiss()
            return
        if self.start_point is None:
            self.start_point = pos
            self.release_time = None
            hwnd = USER32.GetForegroundWindow()
            name = ctypes.create_unicode_buffer(256)
            USER32.GetClassNameW(hwnd, name, 256)
            self.explorer_drag = name.value in EXPLORER_CLASSES
        key = self.trigger.currentData()
        key = self.custom_vk if key == -1 else key
        if (self.explorer_drag and not self.drag_fired and not down(0x1B) and
                down(key) and (pos - self.start_point).manhattanLength() > 10):
            self.drag_fired = True
            self.wheel.display(pos)


def main():
    application = QApplication(sys.argv)
    application.setQuitOnLastWindowClosed(False)
    application.setApplicationName(APPNAME)
    application.setOrganizationName("PUVKID")
    apply_application_style(application)
    application.setWindowIcon(icon())
    DATA.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(DATA / "running.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        settings = QSettings(str(DATA / f"settings-{VERSION}.ini"), QSettings.IniFormat)
        language = "en" if settings.value("language", "ko") == "en" else "ko"
        apply_language(language)
        message_dialog(None, tr(language, "app"), tr(language, "already_running")).exec()
        return 0
    window = MainWindow()
    if "--settings" in sys.argv:
        window.open_window()
    elif not window.settings.value("welcomed", False, type=bool):
        window.settings.setValue("welcomed", True)
        window.notify(window.text("running_title"), window.text("running_message"))
    return application.exec()


if __name__ == "__main__":
    sys.exit(main())
