"""독립 검토한 문서 묶음의 원격 Git 개체를 로컬 원문과 대조한다."""
from pathlib import Path
from datetime import datetime
import hashlib
import json
import subprocess
ROOT = Path(__file__).resolve().parents[2]
checkout = ROOT/'work/enhancement-20261030/remote-baseline'
git = r'C:\Users\PUVKID\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe'
commit='de8d71beef115c6cf88a123ac29304628dbe1c8f'
remote=subprocess.run([git,'-C',str(checkout),'ls-remote','origin','refs/heads/main'],capture_output=True,check=True).stdout.decode('utf-8').split()[0]
expected={'docs/changes/2026-10-30_1.7_실제조작확인.md':('b5aaefece92dab4f299b43f1bf09d742baadc3c6',2458),'docs/versions/1.7.0.md':('152a2a46e7008260dbd254bac889a71008f9e43f',9096)}
items=[]
for name,(blob,size) in expected.items():
    raw=(checkout/name).read_bytes()
    public=(ROOT/'work/enhancement-20261030/public'/name).read_bytes()
    actual=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    assert actual==blob and len(raw)==size and public==raw
    items.append({'path':name,'size':size,'git_blob_sha1':blob,'sha256':hashlib.sha256(raw).hexdigest(),'remote_tree_match':True,'public_copy_match':True})
assert remote==commit
result={'time_kst':datetime.now().astimezone().isoformat(),'commit':commit,'branch':'main','repository':'https://github.com/PUVKID/FlipRing-File-Converter-Project','remote_head_match':True,'remote_tree_source':'GitHub connector git/trees GET','files':items,'scope':'문서 두 파일의 커밋·원격 개체·원문 대조. GitHub 브라우저 렌더 직접 확인은 도구 제한으로 미수행.'}
path=ROOT/'work/enhancement-20261030/publications/de8d71b-원격반영영수증.json'
path.parent.mkdir(exist_ok=True)
assert not path.exists()
path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
