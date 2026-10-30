"""새 설치본의 모든 출하 파일을 스테이지 원문과 대조한다."""
from pathlib import Path
from datetime import datetime
import hashlib
import json
import os

ROOT=Path(__file__).resolve().parents[2]
STAGE=Path(__file__).resolve().parent/'release-stage1/프로그램/FlipRing'
INSTALLED=Path(os.environ['LOCALAPPDATA'])/'Programs/FlipRing'
def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()
items=[]
for path in sorted(STAGE.rglob('*')):
    if not path.is_file():
        continue
    relative=path.relative_to(STAGE)
    other=INSTALLED/relative
    digest=sha(path)
    items.append({'path':relative.as_posix(),'size':path.stat().st_size,'sha256':digest,
                  'installed_matches':other.is_file() and other.stat().st_size==path.stat().st_size and sha(other)==digest})
report={'time_kst':datetime.now().astimezone().isoformat(),'release':'1.8.0','files':items,'passed':bool(items) and all(item['installed_matches'] for item in items),
        'scope':'실제설치폴더와새스테이지의모든출하파일크기/SHA256. 설치프로그램이추가한제거파일은출하비교대상외.'}
target=ROOT/'evidence/1.8-설치파일전체대조.json'
assert not target.exists()
target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'installed_files':len(items),'passed':report['passed']},ensure_ascii=False))
assert report['passed']
