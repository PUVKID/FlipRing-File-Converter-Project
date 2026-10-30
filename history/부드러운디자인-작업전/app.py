"""플립링: 트레이와 원형 메뉴 중심의 무료 Windows 인터페이스."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import winreg

from PySide6.QtCore import (
    Qt, QTimer, Signal, QObject, QPointF, QRectF, QSettings, QLockFile,
    QUrl, QVariantAnimation, QEasingCurve, QSignalBlocker, QTranslator,
)
from PySide6.QtGui import (
    QColor, QPainter, QPen, QPainterPath, QFont, QFontDatabase,
    QIcon, QPixmap, QCursor, QDesktopServices, QActionGroup, QPalette,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QComboBox, QListWidget, QTabWidget, QCheckBox,
    QSystemTrayIcon, QMenu, QMessageBox, QProgressBar,
)
import engine
from i18n import tr, error_text, QT_KOREAN
from pdf_panel import PdfToolsPanel

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
    # 운영체제 글꼴을 사용하며 글꼴 파일을 복제하거나 배포하지 않는다.
    font = QFont()
    font.setFamilies(["Segoe UI Variable", "Segoe UI", "Malgun Gothic", "맑은 고딕"])
    font.setPointSize(size)
    font.setWeight(weight)
    return font


def apply_application_style(application):
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
    dialog = QMessageBox(parent)
    dialog.setWindowTitle(title)
    dialog.setWindowIcon(icon())
    dialog.setText(message)
    dialog.setIcon(QMessageBox.NoIcon)
    dialog.setStandardButtons(QMessageBox.Ok)
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


class HistoryList(QListWidget):
    """결과 선택은 왼쪽 더블클릭으로만 실행한다."""

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            super().mouseDoubleClickEvent(event)
        else:
            event.ignore()


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
        self.motion.setEasingCurve(QEasingCurve.OutCubic)
        self.motion.valueChanged.connect(self._motion_frame)
        self.motion.finished.connect(self._motion_finished)
        self.highlight = QVariantAnimation(self)
        self.highlight.setDuration(100)
        self.highlight.setStartValue(0.0)
        self.highlight.setEndValue(1.0)
        self.highlight.setEasingCurve(QEasingCurve.OutCubic)
        self.highlight.valueChanged.connect(self._highlight_frame)

    def _motion_frame(self, value):
        self.reveal = float(value)
        self.update()

    def _motion_finished(self):
        if self._closing and self.reveal <= 0.001:
            self.hide()

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
        self.highlight.start()
        self.update()

    def display(self, pos, paths=None, preview=False):
        self.motion.stop()
        self.highlight.stop()
        self._closing = False
        self._drop_consumed = False
        self.preview = preview
        self.reveal = 0.0
        self.hover = -1
        self.weights = {-1: 1.0}
        self.set_paths(paths or [])
        self.setAcceptDrops(True)
        screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
        bounds = screen.availableGeometry()
        x = max(bounds.left(), min(pos.x() - self.width() // 2, bounds.right() + 1 - self.width()))
        y = max(bounds.top(), min(pos.y() - self.height() // 2, bounds.bottom() + 1 - self.height()))
        self.move(x, y)
        self.show()
        self.raise_()
        self.motion.setDuration(150)
        self.motion.setStartValue(0.0)
        self.motion.setEndValue(1.0)
        self.motion.start()

    def dismiss(self):
        if not self.isVisible() or self._closing:
            return
        self._closing = True
        # 드롭을 확정한 뒤에는 퇴장 중인 그림이 새 드롭을 받아서는 안 된다.
        self.setAcceptDrops(False)
        self.motion.stop()
        self.motion.setDuration(120)
        self.motion.setStartValue(self.reveal)
        self.motion.setEndValue(0.0)
        self.motion.start()

    def hideEvent(self, event):
        self.motion.stop()
        self.highlight.stop()
        super().hideEvent(event)

    def set_paths(self, paths):
        self.paths = list(dict.fromkeys(str(Path(path)) for path in paths))
        self.options = engine.targets(self.paths)
        self.reasons = {}
        for target in self.options:
            self.reasons[target] = next(
                (missing for path in self.paths if (missing := engine.requirement(path, target))), None)
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
                color = QColor("#ededed" if not self.reasons[fmt] else "#555555")
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
            ink = 150 if missing else 242 - int(210 * weight)
            painter.setPen(QColor(ink, ink, ink))
            painter.setFont(ui_font(9 if count > 7 else 10, QFont.DemiBold))
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
    """상주 컨트롤러와 작은 설정창. 변환 선택은 원형 메뉴에서 수행한다."""

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
        self.resize(460, 600)
        self.setMinimumSize(460, 570)
        self.setFont(ui_font())
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="변환")
        self.bridge = Bridge()
        self.bridge.done.connect(self.finished)
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
        self.setCentralWidget(host)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(20, 20, 20, 15)
        self.brand = QLabel()
        self.brand.setObjectName("brand")
        layout.addWidget(self.brand)
        self.subtitle = QLabel()
        self.subtitle.setObjectName("muted")
        self.subtitle.setWordWrap(True)
        layout.addWidget(self.subtitle)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        settings_page = QWidget()
        settings_layout = QVBoxLayout(settings_page)
        settings_layout.setContentsMargins(14, 16, 14, 12)
        settings_layout.setSpacing(12)
        language_row = QHBoxLayout()
        language_row.addWidget(self.localized(QLabel(), "language"))
        self.language_combo = QComboBox()
        self.language_combo.addItem("한국어", "ko")
        self.language_combo.addItem("English", "en")
        self.language_combo.setCurrentIndex(self.language_combo.findData(self.language))
        self.language_combo.currentIndexChanged.connect(self.language_changed)
        language_row.addWidget(self.language_combo, 1)
        settings_layout.addLayout(language_row)
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
        self.auto = self.localized(QCheckBox(), "auto")
        self.auto.setChecked(self.autostart_enabled())
        self.auto.toggled.connect(self.autostart)
        settings_layout.addWidget(self.auto)
        self.reveal = self.localized(QCheckBox(), "reveal")
        self.reveal.setChecked(self.settings.value("reveal", False, type=bool))
        self.reveal.toggled.connect(lambda value: self.settings.setValue("reveal", value))
        settings_layout.addWidget(self.reveal)
        self.notifications = self.localized(QCheckBox(), "notifications")
        self.notifications.setChecked(self.settings.value("notify", True, type=bool))
        self.notifications.toggled.connect(lambda value: self.settings.setValue("notify", value))
        settings_layout.addWidget(self.notifications)
        note = self.localized(QLabel(), "original_note")
        note.setObjectName("muted")
        note.setWordWrap(True)
        settings_layout.addWidget(note)
        settings_layout.addStretch()
        row = QHBoxLayout()
        row.addWidget(self.localized(self.button("", self.pick_files), "pick_files"))
        row.addWidget(self.localized(self.button("", self.pick_folder), "pick_folder"))
        settings_layout.addLayout(row)
        self.tabs.addTab(settings_page, self.text("settings"))

        tools_page = QWidget()
        tools_layout = QVBoxLayout(tools_page)
        tools_layout.setSpacing(10)
        self.tool_labels = {}
        for name, (title, package, purpose) in engine.TOOLS.items():
            row = QHBoxLayout()
            row.addWidget(self.localized(QLabel(), "purpose_" + name, prefix=title + " · "), 1)
            row.addWidget(self.localized(self.button("", lambda checked=False, pkg=package:
                                      QApplication.clipboard().setText(self.install_command(pkg))), "install_command"))
            tools_layout.addLayout(row)
            status = QLabel()
            status.setObjectName("muted")
            status.setWordWrap(True)
            self.tool_labels[name] = status
            tools_layout.addWidget(status)
        note = self.localized(QLabel(), "tools_note")
        note.setWordWrap(True)
        note.setObjectName("muted")
        tools_layout.addWidget(note)
        tools_layout.addWidget(self.localized(self.button("", self.refresh_tools), "refresh_tools"))
        tools_layout.addStretch()
        self.tabs.addTab(tools_page, self.text("tools"))

        history_page = QWidget()
        history_layout = QVBoxLayout(history_page)
        self.history = HistoryList()
        self.history.itemDoubleClicked.connect(self.open_history_result)
        history_layout.addWidget(self.history)
        history_layout.addWidget(self.localized(QLabel(), "recent_note"))
        self.tabs.addTab(history_page, self.text("history"))
        about_page = QWidget()
        about_layout = QVBoxLayout(about_page)
        about = self.localized(QLabel(), "about_text")
        about.setWordWrap(True)
        about_layout.addWidget(about)
        about_layout.addWidget(self.localized(self.button("", self.open_licenses), "licenses"))
        about_layout.addStretch()
        self.tabs.addTab(about_page, self.text("about"))
        self.pdf_panel = PdfToolsPanel(self.language, self)
        self.pdf_panel.result_ready.connect(self.pdf_finished)
        self.tabs.addTab(self.pdf_panel, self.text("pdf_tools"))
        self.status = QLabel(self.text("ready"))
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
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
        self.retranslate()

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
        for index, key in enumerate(("settings", "tools", "history", "about", "pdf_tools")):
            self.tabs.setTabText(index, self.text(key))
        self.pdf_panel.set_language(self.language)
        self.update_record_label()
        self.update_trigger_hint()
        self.refresh_tools()
        self.refresh_history()
        self.update_status()
        self.update_tray_menu()
        self.wheel.update()

    def update_record_label(self):
        key = "record_wait" if self.recording else "recorded" if self.recorded_key is not None else "record"
        self.record_button.setText(self.text(key, key=self.recorded_key))

    def update_status(self):
        if self.pending:
            self.status.setText(self.text("queue", count=self.pending))
            self.tray.setToolTip(self.app_name() + " · " + self.text("converting", count=self.pending))
        elif self.last_result is not None:
            output, error = self.last_result
            self.status.setText(self.text("failed_status", error=error_text(self.language, error)[:90]) if error
                                else self.text("done_status", name=Path(output).name))
            self.tray.setToolTip(self.app_name())
        else:
            self.status.setText(self.text("ready"))
            self.tray.setToolTip(self.app_name())

    @staticmethod
    def button(text, action):
        button = QPushButton(text)
        button.setMinimumHeight(32)
        button.clicked.connect(action)
        return button

    @staticmethod
    def install_command(package):
        return f"winget install --id {package} -e --source winget --accept-package-agreements --accept-source-agreements"

    def apply_style(self):
        style = """
        QWidget {font-family:'Segoe UI Variable','Segoe UI','Malgun Gothic';font-size:12px;font-weight:400;color:#171717;}
        QMainWindow,QMenu {background:#fafafa;}
        QLabel#brand {font-size:25px;font-weight:600;color:#111111;padding-bottom:2px;}
        QLabel#muted {color:#777777;font-size:11px;}
        QTabWidget::pane {border:1px solid #e0e0e0;border-radius:10px;background:#ffffff;}
        QTabBar::tab {background:transparent;padding:11px 14px;color:#777777;}
        QTabBar::tab:selected {color:#111111;font-weight:600;border-bottom:2px solid #171717;}
        QPushButton {background:#ffffff;border:1px solid #d4d4d4;border-radius:7px;padding:6px 11px;}
        QPushButton:hover {background:#eeeeee;border-color:#777777;}
        QPushButton:pressed {background:#dedede;}
        QPushButton:focus,QComboBox:focus {border-color:#171717;}
        QListWidget,QComboBox {background:#ffffff;border:1px solid #d4d4d4;border-radius:7px;padding:7px;}
        QListWidget::item {padding:8px;border-bottom:1px solid #eeeeee;}
        QListWidget::item:selected {background:#eeeeee;color:#111111;}
        QComboBox QAbstractItemView {background:#ffffff;color:#171717;selection-background-color:#242424;selection-color:#ffffff;}
        QCheckBox {spacing:8px;padding:3px 0;}
        QCheckBox::indicator {width:14px;height:14px;border:1px solid #aaaaaa;border-radius:3px;background:#ffffff;}
        QCheckBox::indicator:checked {background:#242424;border-color:#242424;}
        QCheckBox::indicator:hover {border-color:#171717;}
        QMenu {border:1px solid #d4d4d4;padding:6px;}
        QMenu::item {padding:8px 18px;}
        QMenu::item:selected {background:#e8e8e8;border-radius:5px;}
        QMenu::item:disabled {color:#888888;}
        QProgressBar {max-height:3px;border:0;background:#e6e6e6;}
        QProgressBar::chunk {background:#242424;}
        QToolTip {background:#171717;color:#ffffff;border:0;padding:6px;}
        """
        self.setStyleSheet(style)
        self.tray_menu.setStyleSheet(style)

    def update_tray_menu(self):
        menu = self.tray_menu
        menu.clear()
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
                action.triggered.connect(lambda: (self.open_page(0), self.record_key()))
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
            installed = bool(engine.tool(name))
            action = tools_menu.addAction(("✓ " if installed else "✗ ") + title + " · " + self.text("purpose_" + name))
            action.setEnabled(False)
            if not installed:
                tools_menu.addAction(self.text("copy_install", tool=title), lambda checked=False, pkg=package:
                                     QApplication.clipboard().setText(self.install_command(pkg)))
        tools_menu.addAction(self.text("details"), lambda: self.open_page(1))
        menu.addSeparator()
        menu.addAction(self.text("history"), lambda: self.open_page(2))
        menu.addAction(self.text("pdf_tools"), lambda: self.open_page(4))
        menu.addAction(self.text("settings"), lambda: self.open_page(0))
        menu.addAction(self.text("about"), lambda: self.open_page(3))
        menu.addSeparator()
        menu.addAction(self.text("quit"), self.quit)

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
        for name, label in self.tool_labels.items():
            path = engine.tool(name)
            label.setText(self.text("available" if path else "not_installed"))
            label.setToolTip(path or "")

    def pick_files(self):
        dialog = self.file_dialog(False)
        if dialog.exec() == QFileDialog.Accepted:
            self.set_files(dialog.selectedFiles())
            self.preview()

    def pick_folder(self):
        dialog = self.file_dialog(True)
        if dialog.exec() == QFileDialog.Accepted:
            self.set_files(dialog.selectedFiles())
            self.preview()

    def file_dialog(self, folder):
        dialog = QFileDialog(self, self.text("pick_folder_title" if folder else "pick_files_title"))
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        dialog.setFileMode(QFileDialog.Directory if folder else QFileDialog.ExistingFiles)
        if folder:
            dialog.setOption(QFileDialog.ShowDirsOnly, True)
        for role, key in ((QFileDialog.LookIn, "dialog_location"), (QFileDialog.FileName, "dialog_filename"),
                          (QFileDialog.FileType, "dialog_filter"), (QFileDialog.Reject, "cancel"),
                          (QFileDialog.Accept, "dialog_choose" if folder else "dialog_open")):
            dialog.setLabelText(role, self.text(key))
        return dialog

    def set_files(self, paths):
        self.paths = list(dict.fromkeys(str(Path(path)) for path in paths))

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
        if self.pdf_panel.is_busy():
            # PDFium을 쓰는 두 작업 큐를 동시에 실행하지 않는다.
            message_dialog(self, self.text("busy_title"), self.text("busy_message")).exec()
            return
        for path in paths:
            self.pending += 1

            def job(source=path, target=fmt):
                try:
                    self.bridge.done.emit(source, engine.convert(source, target), "")
                except Exception as exc:
                    self.bridge.done.emit(source, "", str(exc))

            self.pool.submit(job)
        self.progress.show()
        self.update_status()
        self.tray.setIcon(icon(busy=True))

    def finished(self, source, output, error):
        self.pending -= 1
        self.append_record(source, output, error)
        self.update_status()
        if not self.pending:
            self.progress.hide()
            self.tray.setToolTip(self.app_name())
            self.tray.setIcon(icon())

    def pdf_finished(self, source, output, error):
        # PDF 패널의 자체 작업 큐는 기존 파일 변환 pending에 합산하지 않는다.
        self.append_record(source, output, error)
        self.update_status()

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
        if hasattr(self, "history_error"):
            self.history.addItem(self.text("history_error"))

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
