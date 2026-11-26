"""소스와 실행 묶음에 동봉된 도우미의 경로를 반환합니다."""
from pathlib import Path
import sys


def vendor_path(component):
    if component not in ('7zip', 'java', 'h2orestart', 'tesseract'):
        raise ValueError('지원하지 않는 도우미입니다: ' + component)
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    local = base / 'vendor' / component
    return local
