"""운영체제 배율을 바꾸지 않고 앱 창을 현재 화면 안에 맞춘다."""
from PySide6.QtCore import QObject, QEvent, QSize, QPoint, QTimer, Qt
from PySide6.QtWidgets import QScrollArea, QFrame, QSizePolicy


def scroll_content(widget, minimum=QSize()):
    """작은 사용 가능 화면에서도 기존 콘텐츠까지 스크롤로 도달한다."""
    widget.setMinimumSize(minimum)
    scroll = QScrollArea()
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setWidgetResizable(True)
    scroll.setMinimumSize(0, 0)
    scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    scroll.setWidget(widget)
    return scroll


class ScreenFit(QObject):
    """창 프레임을 포함해 맞추며 화면 이동 때도 고정 크기를 갱신한다."""
    def __init__(self, window, preferred, fixed=False):
        super().__init__(window)
        self.window = window
        self.preferred = preferred
        self.fixed = fixed
        self.pending = QTimer(self)
        self.pending.setSingleShot(True)
        self.pending.timeout.connect(self.fit)
        window.installEventFilter(self)
        if fixed:
            window.setWindowFlag(Qt.WindowMaximizeButtonHint, False)
        self.fit()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Show, QEvent.ScreenChangeInternal):
            self.pending.start(0)
        return False

    def fit(self):
        window = self.window
        screen = window.screen()
        if screen is None:
            return
        bounds = screen.availableGeometry()
        frame = window.frameGeometry().size() - window.size()
        width = max(1, min(self.preferred.width(), bounds.width() - max(0, frame.width())))
        height = max(1, min(self.preferred.height(), bounds.height() - max(0, frame.height())))
        if self.fixed:
            window.setFixedSize(width, height)
        else:
            window.setMinimumSize(0, 0)
            window.resize(width, height)
        rectangle = window.frameGeometry()
        x = max(bounds.left(), min(rectangle.left(), bounds.right() + 1 - rectangle.width()))
        y = max(bounds.top(), min(rectangle.top(), bounds.bottom() + 1 - rectangle.height()))
        window.move(window.pos() + QPoint(x - rectangle.left(), y - rectangle.top()))


def fit_window(window, preferred, *, fixed=False):
    window._flipring_screen_fit = ScreenFit(window, preferred, fixed)
    return window._flipring_screen_fit
