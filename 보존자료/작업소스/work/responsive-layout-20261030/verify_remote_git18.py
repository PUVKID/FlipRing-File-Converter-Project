"""체크아웃 줄끝 변환 없이 커밋 원본 개체를 직접 검증한다."""
from pathlib import Path
from datetime import datetime
import hashlib
import json
import subprocess
ROOT=Path(__file__).resolve().parents[2]
REPO=ROOT/'work/enhancement-20261030/remote-baseline'
GIT=r'C:\Users\PUVKID\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe'
COMMIT='b8e7839c7df327a98def7348a9626856599fc1f9'
def git(*args,input=None):
    return subprocess.run([GIT,'-C',str(REPO),*args],input=input,capture_output=True,check=True).stdout
records=[]
for line in git('ls-tree','-r','-l','-z',COMMIT).split(b'\0'):
    if not line:
        continue
    header,name=line.split(b'\t',1)
    mode,kind,digest,size=header.split()
    assert kind==b'blob'
    records.append({'path':name.decode('utf-8'),'sha':digest.decode(),'size':int(size)})
payload=git('cat-file','--batch',input=''.join(item['sha']+'\n' for item in records).encode())
offset=0
for item in records:
    end=payload.index(b'\n',offset)
    digest,kind,size=payload[offset:end].split()
    size=int(size)
    raw=payload[end+1:end+1+size]
    assert payload[end+1+size:end+2+size]==b'\n'
    assert kind==b'blob' and digest.decode()==item['sha'] and size==item['size']
    assert hashlib.sha1(b'blob '+str(size).encode()+b'\0'+raw).hexdigest()==item['sha']
    offset=end+2+size
assert offset==len(payload)
head=git('ls-remote','origin','refs/heads/main').decode().split()[0]
assert head==COMMIT
assert not git('status','--porcelain')
print(json.dumps({'verified_at_kst':datetime.now().astimezone().isoformat(),'commit':COMMIT,'remote_head_match':True,'clean':True,'files':records},ensure_ascii=False))
