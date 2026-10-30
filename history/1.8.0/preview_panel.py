"""실제 원본과 결과를 읽는 작은 미리보기. PDFium 사용 중에는 UI를 기다리게 하지 않는다."""
from pathlib import Path
from PIL import Image, ImageOps
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton
import pypdfium2 as pdfium
from pdf_lock import PDFIUM_LOCK

class PreviewPanel(QWidget):
    reveal_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.language = 'ko'
        self.paths = ('', '')
        self.images = [QImage(), QImage()]
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.panels = []
        for index in range(2):
            column = QVBoxLayout()
            column.setAlignment(Qt.AlignTop)
            column.setSpacing(4)
            title, picture, info, button = QLabel(), QLabel(), QLabel(), QPushButton()
            title.setStyleSheet('font-weight:600;border-bottom:1px solid #dedede;padding-bottom:5px;')
            picture.setAlignment(Qt.AlignCenter)
            picture.setMinimumSize(100, 95)
            picture.setFixedHeight(140)
            picture.setStyleSheet('background:#f1f1f1;border-radius:8px;')
            info.setWordWrap(True)
            info.setMinimumHeight(48)
            info.setTextInteractionFlags(Qt.TextSelectableByMouse)
            button.clicked.connect(lambda checked=False, i=index: self.reveal_requested.emit(self.paths[i]))
            for item in (title, picture, info, button): column.addWidget(item)
            row.addLayout(column, 1)
            self.panels.append((title, picture, info, button))
        self.set_paths('', '')

    def set_language(self, language):
        self.language = language
        self.set_paths(*self.paths)

    def set_paths(self, source, result=''):
        self.paths = (str(source) if source else '', str(result) if result else '')
        en = self.language == 'en'
        for index, (title, picture, info, button) in enumerate(self.panels):
            title.setText(('Original' if index == 0 else 'Result') if en else ('원본' if index == 0 else '결과'))
            button.setText('Select in Explorer' if en else '탐색기에서 선택')
            picture.clear()
            self.images[index] = QImage()
            path = Path(self.paths[index]) if self.paths[index] else None
            button.setEnabled(bool(path and path.exists()))
            if path is None:
                info.setText(('Select a file' if index == 0 else 'Run to preview the result') if en else ('파일을 선택하세요' if index == 0 else '실행 후 결과를 확인하세요'))
                continue
            metadata = path.name
            try:
                size = path.stat().st_size
                metadata = f'{path.name}\n{size:,} bytes'
                image = None
                if path.is_dir():
                    raise ValueError('Folder preview is not supported.' if en else '폴더 미리보기는 지원하지 않습니다.')
                if path.suffix.lower() == '.pdf':
                    if not PDFIUM_LOCK.acquire(blocking=False):
                        raise ValueError('PDF is busy. Select again after completion.' if en else 'PDF 처리 중입니다. 완료 후 다시 선택하세요.')
                    try:
                        doc = pdfium.PdfDocument(str(path))
                        try:
                            metadata += f' · {len(doc)} ' + ('pages' if en else '페이지')
                            if not len(doc): raise ValueError('Empty PDF' if en else '페이지가 없는 PDF입니다.')
                            page = doc[0]
                            try:
                                width, height = page.get_size()
                                bitmap = page.render(scale=min(1.0, 500 / max(width, height)))
                                try: image = bitmap.to_pil().convert('RGB').copy()
                                finally: bitmap.close()
                            finally: page.close()
                        finally: doc.close()
                    finally: PDFIUM_LOCK.release()
                else:
                    with Image.open(path) as opened:
                        metadata += f' · {opened.width} × {opened.height} px'
                        image = ImageOps.exif_transpose(opened)
                        image.thumbnail((500, 300))
                        image = image.convert('RGBA').copy()
                image = image.convert('RGBA')
                qimage = QImage(image.tobytes(), image.width, image.height, image.width * 4, QImage.Format_RGBA8888).copy()
                self.images[index] = qimage
                self._fit_picture(index)
                info.setText(metadata)
            except Exception as exc:
                picture.setText('Preview unavailable' if en else '미리보기 불가')
                detail = str(exc) if isinstance(exc, (ValueError, FileNotFoundError)) else ('Unsupported or unreadable format' if en else '지원하지 않거나 읽을 수 없는 형식입니다')
                info.setText(f'{metadata}\n{detail}')

    def _fit_picture(self, index):
        image = self.images[index]
        if image.isNull():
            return
        picture = self.panels[index][1]
        ratio = picture.devicePixelRatioF()
        size = picture.contentsRect().size()
        scaled = image.scaled(max(1, round((size.width() - 8) * ratio)),
                              max(1, round((size.height() - 8) * ratio)),
                              Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pixmap = QPixmap.fromImage(scaled)
        pixmap.setDevicePixelRatio(ratio)
        picture.setPixmap(pixmap)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 렌더한 이미지 캐시만 사용하며 파일이나 PDF를 다시 열지 않는다.
        if hasattr(self, 'panels'):
            for index in range(len(self.panels)):
                self._fit_picture(index)
