"""앱 팔레트·표면·직접 그리기에 사용하는 공통 테마."""
from __future__ import annotations

import re
from PySide6.QtCore import QObject, QEvent, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget


def is_dark():
    app = QApplication.instance()
    return bool(app and app.property('flipringDarkTheme'))


def theme_color(*args):
    """기존 밝은 화면의 회색을 어두운 화면의 대응 명도로 바꾼다."""
    color = QColor(*args)
    if is_dark() and color.isValid() and color.red() == color.green() == color.blue():
        value = round(32 + (255 - color.red()) * 0.85)
        color.setRgb(value, value, value, color.alpha())
    return color


def ring_color(*args):
    """기존 어두운 휠·탐색은 밝은 선택에서만 반전한다."""
    color = QColor(*args)
    if not is_dark() and color.isValid() and color.red() == color.green() == color.blue():
        value = 255 - color.red()
        color.setRgb(value, value, value, color.alpha())
    return color


def themed_style(source):
    if not is_dark():
        return source
    def replace(match):
        return theme_color(match.group()).name()
    result = re.sub(r'#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b', replace, source)
    return re.sub(r'(?<=:)\s*(white|black)\b', lambda m: theme_color(m[1]).name(), result)


class ThemeManager(QObject):
    changed = Signal(str)

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.mode = 'system'
        self._changing = False
        self._base_palette = QPalette(app.palette())
        app.installEventFilter(self)
        app.styleHints().colorSchemeChanged.connect(self._system_changed)

    def _system_changed(self, scheme):
        if self.mode == 'system':
            self.apply('system')

    def apply(self, mode):
        self.mode = mode if mode in ('light', 'dark', 'system') else 'system'
        dark = self.mode == 'dark' or (self.mode == 'system' and
                 self.app.styleHints().colorScheme() == Qt.ColorScheme.Dark)
        self.app.setProperty('flipringDarkTheme', dark)
        self._changing = True
        try:
            palette = QPalette(self._base_palette)
            colors = {
                QPalette.Window: '#fafafa', QPalette.WindowText: '#171717',
                QPalette.Base: '#ffffff', QPalette.AlternateBase: '#f0f0f0',
                QPalette.Text: '#171717', QPalette.Button: '#ffffff',
                QPalette.ButtonText: '#171717', QPalette.Highlight: '#242424',
                QPalette.HighlightedText: '#ffffff', QPalette.ToolTipBase: '#242424',
                QPalette.ToolTipText: '#ffffff', QPalette.PlaceholderText: '#777777',
                QPalette.Link: '#404040', QPalette.LinkVisited: '#606060',
                QPalette.Light: '#ffffff', QPalette.Midlight: '#eeeeee',
                QPalette.Mid: '#bbbbbb', QPalette.Dark: '#888888',
                QPalette.Shadow: '#333333', QPalette.Accent: '#242424',
            }
            for role, value in colors.items():
                palette.setColor(role, theme_color(value))
            for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
                palette.setColor(QPalette.Disabled, role, theme_color('#999999'))
            self.app.setPalette(palette)
            for widget in self.app.allWidgets():
                self._style(widget)
                widget.update()
        finally:
            self._changing = False
        self.changed.emit(self.mode)

    def _style(self, widget):
        current = widget.styleSheet()
        rendered = getattr(widget, '_flipring_theme_rendered', None)
        if current != rendered:
            original = getattr(widget, '_flipring_theme_source', '')
            widget._flipring_theme_source = (original + current[len(rendered):]
                                             if rendered and current.startswith(rendered) else current)
        source = getattr(widget, '_flipring_theme_source', current)
        target = themed_style(source)
        widget._flipring_theme_rendered = target
        if target != current:
            widget.setStyleSheet(target)

    def eventFilter(self, obj, event):
        # 생성이 늦은 선택창·메뉴와 열린 표면의 새 스타일도 같은 선택을 따른다.
        if not self._changing and isinstance(obj, QWidget) and event.type() in (
                QEvent.Polish, QEvent.Show, QEvent.StyleChange):
            self._changing = True
            try:
                self._style(obj)
            finally:
                self._changing = False
        return False


def manager(app=None):
    app = app or QApplication.instance()
    if not hasattr(app, '_flipring_theme_manager'):
        app._flipring_theme_manager = ThemeManager(app)
    return app._flipring_theme_manager
