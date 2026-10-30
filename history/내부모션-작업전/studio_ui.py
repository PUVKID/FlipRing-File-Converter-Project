"""작업 공간의 내비게이션과 파일 상태를 그리는 Qt 전용 구성 요소."""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, Signal, QVariantAnimation, QEasingCurve, QRectF, QPointF, QSignalBlocker, QSize
from PySide6.QtGui import QColor, QPainter, QPen, QPainterPath, QFont, QPixmap, QIcon
from PySide6.QtWidgets import QWidget, QAbstractButton, QFrame, QVBoxLayout, QLabel, QSizePolicy, QCheckBox, QStyledItemDelegate, QStyle


def svg_icon(path, color="#5a5a5a"):
    """공식 SVG 원문은 보존하고 표시 색상만 메모리에서 바꾼다."""
    pixmap = QPixmap()
    if not pixmap.loadFromData(path.read_bytes().replace(b"currentColor", color.encode("ascii"))):
        raise RuntimeError(f"UI icon could not be loaded: {path}")
    return QIcon(pixmap)


class StudioCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("studioCard")
        self.setAttribute(Qt.WA_StyledBackground, True)


class HistoryDelegate(QStyledItemDelegate):
    """저장 데이터는 그대로 두고 파일·결과·시각을 구분해 표시한다."""

    def sizeHint(self, option, index):
        return QSize(280, 86)

    def paint(self, painter, option, index):
        row = index.data(Qt.UserRole + 3)
        if not isinstance(row, dict):
            return super().paint(painter, option, index)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rectangle = QRectF(option.rect).adjusted(4, 3, -4, -3)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#eeeeee" if option.state & QStyle.State_Selected else "#ffffff"))
        painter.drawRoundedRect(rectangle, 10, 10)
        icon = QRectF(rectangle.left() + 16, rectangle.top() + 17, 42, 44)
        painter.setBrush(QColor("#f1f1f1"))
        painter.drawRoundedRect(icon, 9, 9)
        font = option.font
        font.setPixelSize(9)
        font.setWeight(QFont.Medium)
        painter.setFont(font)
        painter.setPen(QColor("#666666"))
        painter.drawText(icon, Qt.AlignCenter, row["format"])
        left = rectangle.left() + 74
        width = max(20, rectangle.width() - 94)
        font.setPixelSize(13)
        font.setWeight(QFont.Medium)
        painter.setFont(font)
        painter.setPen(QColor("#303030"))
        painter.drawText(QRectF(left, rectangle.top() + 15, width, 22), Qt.AlignLeft | Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(row["source"], Qt.ElideMiddle, int(width)))
        font.setPixelSize(11)
        font.setWeight(QFont.Normal)
        painter.setFont(font)
        painter.setPen(QColor("#737373"))
        detail = row["time"] + "   ·   " + row["detail"]
        painter.drawText(QRectF(left, rectangle.top() + 40, width, 20), Qt.AlignLeft | Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(detail, Qt.ElideMiddle, int(width)))
        painter.restore()


class Toggle(QCheckBox):
    """QCheckBox의 상태·키보드·시그널을 유지하는 작은 전환 스위치."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.amount = 0.0
        self.setFixedHeight(38)
        self.setCursor(Qt.PointingHandCursor)
        self.motion = QVariantAnimation(self)
        self.motion.setDuration(180)
        self.motion.setEasingCurve(QEasingCurve.InOutSine)
        self.motion.valueChanged.connect(self._frame)
        self.toggled.connect(self._transition)

    def sizeHint(self):
        return QSize(200, 38)

    def minimumSizeHint(self):
        return QSize(140, 38)

    def hitButton(self, position):
        return self.rect().contains(position)

    def _frame(self, value):
        self.amount = float(value)
        self.update()

    def _transition(self, checked):
        self.motion.stop()
        if not self.isVisible():
            self.amount = float(checked)
            self.update()
            return
        with QSignalBlocker(self.motion):
            self.motion.setStartValue(self.amount)
            self.motion.setEndValue(float(checked))
            self.motion.setCurrentTime(0)
        self.motion.start()

    def hideEvent(self, event):
        self.motion.stop()
        self.amount = float(self.isChecked())
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor("#424242" if self.isEnabled() else "#999999"))
        painter.drawText(QRectF(0, 0, self.width() - 52, self.height()),
                         Qt.AlignVCenter | Qt.AlignLeft | Qt.TextWordWrap, self.text())
        shade = round(220 - 166 * self.amount)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(shade, shade, shade))
        x, y = self.width() - 39, (self.height() - 22) / 2
        painter.drawRoundedRect(QRectF(x, y, 38, 22), 11, 11)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(x + 3 + 16 * self.amount, y + 3, 16, 16))
        if self.hasFocus():
            painter.setPen(QPen(QColor("#888888"), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        painter.end()


class NavButton(QAbstractButton):
    """입력 영역을 고정하고 명암만 바꾸는 사이드 내비게이션."""

    def __init__(self, symbol, parent=None):
        super().__init__(parent)
        self.symbol = symbol
        self.svg_icons = None
        self.hovered = False
        self.amount = 0.0
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(46)
        self.motion = QVariantAnimation(self)
        self.motion.setDuration(170)
        self.motion.setEasingCurve(QEasingCurve.InOutSine)
        self.motion.valueChanged.connect(self._frame)
        self.toggled.connect(self.transition)

    def set_svg(self, path):
        self.svg_icons = {selected: svg_icon(path, color).pixmap(20, 20)
                          for selected, color in ((False, "#b8b8b8"), (True, "#f3f3f3"))}

    def _frame(self, value):
        self.amount = float(value)
        self.update()

    def transition(self):
        target = 1.0 if self.hovered or self.isChecked() else 0.0
        self.motion.stop()
        if abs(target - self.amount) < 0.001:
            self.update()
            return
        with QSignalBlocker(self.motion):
            self.motion.setStartValue(self.amount)
            self.motion.setEndValue(target)
            self.motion.setCurrentTime(0)
        self.motion.start()

    def enterEvent(self, event):
        self.hovered = True
        self.transition()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered = False
        self.transition()
        super().leaveEvent(event)

    def hideEvent(self, event):
        self.motion.stop()
        self.amount = 1.0 if self.isChecked() else 0.0
        self.hovered = False
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, round(20 * self.amount)))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0, 1, 0, -1), 10, 10)
        color = QColor("#f3f3f3" if self.isChecked() else "#b8b8b8")
        painter.setPen(QPen(color, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        if self.svg_icons is not None:
            painter.drawPixmap(16, round(self.height() / 2 - 10), self.svg_icons[self.isChecked()])
        font = self.font()
        font.setWeight(QFont.Medium if self.isChecked() else QFont.Normal)
        painter.setFont(font)
        painter.drawText(QRectF(46, 0, self.width() - 58, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text())
        if self.hasFocus():
            painter.setPen(QPen(QColor("#909090"), 1))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 2, -1, -2), 9, 9)
        painter.end()


class OrbitVisual(QWidget):
    """파일 상태에 반응하는 중심 링. 유한 애니메이션 외에는 다시 그리지 않는다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(240, 220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.phase = 0.0
        self.approach = 0.0
        self.state = "file"
        self.formats = ["PNG", "JPG", "PDF", "WEBP"]
        self.intro = QVariantAnimation(self)
        self.intro.setDuration(720)
        self.intro.setEasingCurve(QEasingCurve.OutCubic)
        self.intro.setStartValue(0.0)
        self.intro.setEndValue(1.0)
        self.intro.valueChanged.connect(self._intro_frame)
        self.motion = QVariantAnimation(self)
        self.motion.setDuration(230)
        self.motion.setEasingCurve(QEasingCurve.InOutSine)
        self.motion.valueChanged.connect(self._approach_frame)

    def _intro_frame(self, value):
        self.phase = float(value)
        self.update()

    def _approach_frame(self, value):
        self.approach = float(value)
        self.update()

    def set_approach(self, active):
        target = 1.0 if active else 0.0
        self.motion.stop()
        if abs(target - self.approach) < 0.001:
            return
        with QSignalBlocker(self.motion):
            self.motion.setStartValue(self.approach)
            self.motion.setEndValue(target)
            self.motion.setCurrentTime(0)
        self.motion.start()

    def respond(self, formats=None, state="file"):
        self.state = state
        if formats:
            self.formats = [value.upper() for value in formats[:4]]
        self.intro.stop()
        self.intro.setCurrentTime(0)
        # 같은 0시각에서는 신호가 생략되므로 숨김 때 바뀐 그리기값도 직접 맞춘다.
        self._intro_frame(float(self.intro.currentValue()))
        self.intro.start()

    def showEvent(self, event):
        super().showEvent(event)
        self.respond(state=self.state)

    def hideEvent(self, event):
        self.intro.stop()
        self.motion.stop()
        self.phase = 1.0
        self.approach = 0.0
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        center = QPointF(self.width() / 2, self.height() / 2)
        radius = min(self.width() * 0.32, self.height() * 0.38, 116)
        radius *= 0.86 + 0.14 * self.phase + 0.055 * self.approach
        painter.translate(center)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor("#eeeeee"), 1))
        painter.drawEllipse(QPointF(), radius + 29, radius + 29)
        painter.drawEllipse(QPointF(), radius + 15, radius + 15)
        for index in range(3):
            painter.save()
            painter.rotate(index * 60 + (1 - self.phase) * 35 + self.approach * 12)
            painter.setPen(QPen(QColor(120 + index * 35, 120 + index * 35, 120 + index * 35), 1.2))
            painter.drawEllipse(QRectF(-radius, -radius * 0.46, radius * 2, radius * 0.92))
            painter.restore()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#202020"))
        painter.drawEllipse(QPointF(), 35 + self.approach * 3, 35 + self.approach * 3)
        painter.setPen(QPen(QColor("#ffffff"), 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        if self.state == "complete":
            path = QPainterPath(QPointF(-12, 0))
            path.lineTo(-3, 9)
            path.lineTo(14, -10)
            painter.drawPath(path)
        elif self.state == "error":
            painter.drawLine(-9, -9, 9, 9)
            painter.drawLine(9, -9, -9, 9)
        elif self.state == "working":
            painter.drawArc(QRectF(-13, -13, 26, 26), round(self.phase * 120 * 16), 260 * 16)
        else:
            painter.drawRoundedRect(QRectF(-10, -14, 21, 28), 3, 3)
            painter.drawLine(-5, -4, 6, -4)
            painter.drawLine(-5, 2, 6, 2)
            painter.drawLine(-5, 8, 2, 8)
        font = self.font()
        font.setPixelSize(10)
        font.setWeight(QFont.Medium)
        painter.setFont(font)
        for index, label in enumerate(self.formats):
            progress = min(1.0, max(0.0, (self.phase - index * 0.12) / 0.64))
            if progress <= 0:
                continue
            angle = math.radians(-60 + index * 90 + self.approach * 4)
            distance = (radius + 18) * (0.5 + 0.5 * progress)
            point = QPointF(math.cos(angle) * distance, math.sin(angle) * distance)
            rectangle = QRectF(point.x() - 27, point.y() - 12, 54, 24)
            painter.setPen(QPen(QColor("#e6e6e6"), 1))
            painter.setBrush(QColor("#ffffff"))
            painter.drawRoundedRect(rectangle, 12, 12)
            painter.setPen(QColor("#5a5a5a"))
            painter.drawText(rectangle, Qt.AlignCenter, label)
        painter.end()


class FileDropCard(StudioCard):
    clicked = Signal()
    files_dropped = Signal(list)

    def __init__(self, validator, accept_copy, parent=None):
        super().__init__(parent)
        self.validator = validator
        self.accept_copy = accept_copy
        self.setObjectName("dropCard")
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(26, 20, 26, 24)
        self.body.setSpacing(8)
        self.orbit = OrbitVisual()
        self.body.addWidget(self.orbit, 1)
        self.title = QLabel()
        self.title.setObjectName("dropTitle")
        self.title.setAlignment(Qt.AlignCenter)
        self.body.addWidget(self.title)
        self.caption = QLabel()
        self.caption.setObjectName("muted")
        self.caption.setAlignment(Qt.AlignCenter)
        self.caption.setWordWrap(True)
        self.body.addWidget(self.caption)

    def enterEvent(self, event):
        self.orbit.set_approach(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.orbit.set_approach(False)
        super().leaveEvent(event)

    def dragEnterEvent(self, event):
        if event.possibleActions() & Qt.CopyAction and self.validator(event.mimeData()):
            self.accept_copy(event)
            self.orbit.set_approach(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dragLeaveEvent(self, event):
        self.orbit.set_approach(False)
        event.accept()

    def dropEvent(self, event):
        paths = self.validator(event.mimeData())
        if not paths or not event.possibleActions() & Qt.CopyAction:
            event.ignore()
            return
        self.accept_copy(event)
        self.orbit.set_approach(False)
        self.files_dropped.emit(paths)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
            event.accept()
        else:
            super().keyPressEvent(event)
