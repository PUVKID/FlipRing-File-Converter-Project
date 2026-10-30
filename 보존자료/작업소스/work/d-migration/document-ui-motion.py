from datetime import datetime
import hashlib
import json
from pathlib import Path
root=Path(r'D:\2026\FilpRing Project')
path=root/'소스/빌드방법.md'
original=path.read_bytes()
needle='현재 빌드 대상 릴리스는 1.6.0입니다. 설정·기록 데이터의 기존 스키마와 저장 위치는 변경하지 않습니다.'.encode('utf-8')
addition='\r\n공통 파일·폴더 선택창과 내부 조작 피드백을 담당하는 `ui_motion.py`도 전체 소스 복사 시 반드시 포함하세요. 앱에서 직접 가져오는 모듈이므로 위 기본 `build.py` 명령의 PyInstaller Analysis에 자동으로 포함되며 별도 빌드 명령은 필요하지 않습니다.'.encode('utf-8')
assert original.count(needle)==1
assert b'ui_motion.py' not in original
updated=original.replace(needle,needle+addition,1)
assert updated.replace(needle+addition,needle,1)==original
assert b'\r\r\n' not in updated
assert updated.count(b'\r\n')==original.count(b'\r\n')+1
assert '\ufffd' not in updated.decode('utf-8')
out=root/'work/d-migration/package-preparation'
backup=out/'빌드방법-ui_motion추가전.md'
assert not backup.exists()
backup.write_bytes(original)
path.write_bytes(updated)
assert path.read_bytes()==updated
record={'time_kst':datetime.now().astimezone().isoformat(),'session':'01a15519-c86d-7880-a2e6-c9070f59067d','task':'studio-redesign-20261021','role':'build','requested_model':'gpt-6.1-sol','requested_effort':'medium','repair_used':14,'input_fix_used':9,'global_sha256':hashlib.sha256(Path(r'C:\Users\PUVKID\.codex\AGENTS.md').read_bytes()).hexdigest(),'before_sha256':hashlib.sha256(original).hexdigest(),'after_sha256':hashlib.sha256(updated).hexdigest(),'bytes':len(updated),'original_bytes_preserved_except_single_insertion':True,'strict_utf8':True,'double_cr_absent':True,'build_executed':False,'package_executed':False,'shipping_changed':False}
(out/'빌드문서-ui_motion-추가.json').write_bytes((json.dumps(record,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
print(json.dumps(record,ensure_ascii=False))
