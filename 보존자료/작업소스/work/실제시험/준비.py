from pathlib import Path
import hashlib
import json
from PIL import Image, ImageDraw

# 새 설치본의 실제 탐색기 시험용 파일만 만든다.
root = Path(__file__).resolve().parent
target = root / "부드러운디자인-시험.jpg"
if target.exists():
    raise SystemExit("기존 시험 파일을 보존합니다.")
image = Image.new("RGB", (640, 480), "#f0f0f0")
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((90, 50, 550, 430), radius=55, fill="#242424")
draw.ellipse((200, 120, 440, 360), fill="#ffffff")
image.save(target, quality=95)
(root / "원본해시.json").write_text(json.dumps({"file": target.name, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}, ensure_ascii=False, indent=2), encoding="utf-8")
print(target)
