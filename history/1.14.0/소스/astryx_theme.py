from pathlib import Path
from functools import lru_cache
import subprocess
import os
import sys

# 소스와 PyInstaller 실행 묶음 모두 같은 동봉 엔진을 사용합니다.
ENGINE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'vendor/astryx/astryx-theme.exe'

@lru_cache(maxsize=24)
def compile_qss(mode, accent, background, surface, text, muted, border):
    """Rust에서 현재 팔레트의 실제 Qt 테마를 생성하며 실패를 숨기지 않습니다."""
    argv = [str(ENGINE), '--format', 'qss', '--mode', mode]
    for name, value in (('accent', accent), ('background', background), ('surface', surface),
                        ('text', text), ('muted', muted), ('border', border)):
        argv.extend(['--' + name, value])
    try:
        result = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8',
                                errors='strict', timeout=10, check=False,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as error:
        raise RuntimeError('Astryx 테마 엔진 실행을 확인해 주세요: ' + str(ENGINE)) from error
    if result.returncode:
        raise RuntimeError('Astryx 테마 생성 실패: ' + result.stderr.strip())
    if not result.stdout.strip():
        raise RuntimeError('Astryx 테마 생성 결과가 비어 있습니다.')
    return result.stdout
