"""실제 Qt 위젯의 유한 모션 프레임을 미리보기로 보관한다."""
from pathlib import Path
import io

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice

root = Path(__file__).resolve().parents[1]
setup = (root / "work" / "studio-preview.py").read_text(encoding="utf-8")
exec(compile(setup.split("window.drop_card.orbit.intro.setCurrentTime(220)")[0], str(root / "work" / "studio-preview.py"), "exec"))
orbit = window.drop_card.orbit
frames = []
orbit.respond()
for milliseconds in range(0, 721, 40):
    orbit.intro.setCurrentTime(milliseconds)
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    assert orbit.grab().save(buffer, "PNG")
    frames.append(Image.open(io.BytesIO(bytes(buffer.data()))).convert("RGB"))
durations = [40] * len(frames)
durations[-1] = 900
destination = out / "Studio-motion.gif"
frames[0].save(destination, save_all=True, append_images=frames[1:], duration=durations, loop=0)
print(destination)
window.hide()
window.tray.hide()
window.pool.shutdown(wait=True)
window.pdf_panel.shutdown()
