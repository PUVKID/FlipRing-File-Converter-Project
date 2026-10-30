"""고정 창 릴리스의 빌드·포장 자료를 준비한다."""
from pathlib import Path
import hashlib
import json
from datetime import datetime

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / '소스'

def replace_bytes(path, old, new):
    raw = path.read_bytes()
    assert raw.count(old) == 1, str(path)
    path.write_bytes(raw.replace(old, new))

replace_bytes(SOURCE / 'build.py', b'release_version = "1.7.0"', b'release_version = "1.8.0"')
replace_bytes(SOURCE / 'package.py', b'"build.py", "package.py", "test_gui.py",', b'"fixed_viewport.py", "test_fixed_layout.py", "build.py", "package.py", "test_gui.py",')
replace_bytes(SOURCE / 'package.py', '"1.7-새기능안내.md", "LICENSE.txt"'.encode(), '"1.7-새기능안내.md", "1.8-화면안내.md", "LICENSE.txt"'.encode())
replace_bytes(SOURCE / '빌드방법.md', '현재 빌드 대상 릴리스는 1.7.0입니다.'.encode(), '현재 빌드 대상 릴리스는 1.8.0입니다.'.encode())
guide = '''# 플립링 1.8 화면 안내

기본 창은 1160×820 논리 픽셀의 고정 크기입니다. Windows 배율에 따라 실제 픽셀 수가 달라집니다. 사용 가능한 화면이 작으면 그 영역 안으로 고정 크기를 맞추고 필요한 내용은 스크롤로 확인합니다.

메뉴의 현재 위치와 본문 경계, 프리셋·작업 목록·실행·원본과 결과 비교의 구분을 보강합니다. 흑백·회색과 SUIT 글꼴을 사용합니다. 한국어와 영어는 설정에서 선택합니다.

창 맞춤과 고배율 이미지 처리는 `fixed_viewport.py`에 있으며 전체 소스와 함께 복사해야 합니다. 해당 모듈은 PyInstaller가 자동으로 포함합니다. `test_fixed_layout.py`는 이 릴리스의 화면 크기·배율 검사를 담당합니다. 기존 변환 엔진과 설정 데이터 형식은 유지합니다.

개발용 Qt 오프스크린 렌더 검사는 실제 Windows의 디스플레이 배율 변경이나 탐색기 Shift 드래그 검사와 구분합니다. 세부 검증 결과는 프로젝트의 릴리스 기록에 보관합니다.
'''
(SOURCE / '1.8-화면안내.md').write_text(guide, encoding='utf-8')
verify = (ROOT / 'work/enhancement-20261030/verify_compiled.py').read_text(encoding='utf-8')
verify = verify.replace("'studio_ui', 'ui_motion'):", "'studio_ui', 'ui_motion', 'fixed_viewport'):").replace('len(items) == 11', 'len(items) == 12')
(ROOT / 'work/responsive-layout-20261030/verify_compiled18.py').write_text(verify, encoding='utf-8')
record = {'time_kst': datetime.now().astimezone().isoformat(), 'scope': '현재 요청의 부모 소유 빌드·포장 준비. 제품 구현 및 최종 검증은 진행 중.', 'files': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in [SOURCE/'build.py', SOURCE/'package.py', SOURCE/'빌드방법.md', SOURCE/'1.8-화면안내.md']}}
(ROOT / 'work/responsive-layout-20261030/포장준비.json').write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps(record, ensure_ascii=False))
