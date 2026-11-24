"""고정 공식 휠의 SHA를 확인해 이 도구 폴더에만 생성 의존성을 준비한다."""
from pathlib import Path
import hashlib,json,subprocess,sys,urllib.request
root=Path(__file__).resolve().parent
metadata=json.loads((root/'공식휠_출처와해시.json').read_text(encoding='utf-8'))
downloads=root/'공식휠';downloads.mkdir(exist_ok=True)
paths=[]
for package in metadata['records']:
    path=downloads/package['filename']
    assert path.parent==downloads and package['url'].startswith('https://files.pythonhosted.org/')
    if not path.exists():
        part=path.with_suffix(path.suffix+'.part')
        assert not part.exists(), '미완료 다운로드 원문을 먼저 확인해 주세요.'
        with urllib.request.urlopen(package['url'],timeout=30) as response,part.open('wb') as output:
            while chunk:=response.read(1024*1024):output.write(chunk)
        assert part.stat().st_size==package['bytes']
        assert hashlib.sha256(part.read_bytes()).hexdigest()==package['sha256']
        part.rename(path)
    assert path.stat().st_size==package['bytes']
    assert hashlib.sha256(path.read_bytes()).hexdigest()==package['sha256']
    paths.append(str(path))
target=root/'생성전용환경'
if target.exists():
    raise SystemExit('생성전용환경이 이미 있습니다. 기존 환경을 덮어쓰지 않았습니다.')
subprocess.run([sys.executable,'-I','-B','-X','utf8','-m','pip','install','--disable-pip-version-check',
    '--no-cache-dir','--no-index','--no-deps','--no-compile','--target',str(target),*paths],check=True,timeout=120)
