"""새 릴리스의 동결 준비 도구를 별도 파일로 생성한다."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
text = (ROOT/'work/enhancement-20261030/prepare_validation.py').read_text(encoding='utf-8')
text = text.replace('1.7-새기능안내.md','1.8-화면안내.md').replace("'release': '1.7.0'", "'release': '1.8.0'").replace('evidence/1.7-소스동결','evidence/1.8-소스동결')
(Path(__file__).parent/'prepare_validation18.py').write_text(text,encoding='utf-8')
print('1.8 동결 준비 도구 저장. 실제 동결은 구현 완료 뒤 실행합니다.')
