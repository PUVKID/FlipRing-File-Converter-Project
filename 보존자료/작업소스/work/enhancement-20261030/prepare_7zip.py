"""공식 고정 릴리스의 원문·해시를 보존하고 설치 없이 자료만 준비한다."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent / '7zip-preparation'
WORK.mkdir(exist_ok=True)
manifest = json.loads((WORK.parent / '7zip-release-assets.json').read_text(encoding='utf-8'))
records = []
for entry in manifest['assets']:
    path = WORK / entry['name']
    assert not path.exists(), '기존 준비 자료는 덮어쓰지 않습니다.'
    original = Path('C:/Users/PUVKID/AppData/Local/Temp/WinGet/7zip.7zip.26.05') / entry['name']
    if original.is_file():
        shutil.copyfile(original, path)
    else:
        with urllib.request.urlopen(entry['url'], timeout=60) as response, path.open('xb') as stream:
            shutil.copyfileobj(response, stream)
    actual = hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()
    assert path.stat().st_size == entry['size'] and actual == entry['sha256'], entry['name']
    records.append({**entry, 'actual_sha256': actual})
    print('공식 자료 크기·해시 확인:', entry['name'], flush=True)
(WORK / '다운로드검증.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
output = WORK / 'payload'
assert not output.exists()
command = [str(WORK / '7zr.exe'), 'x', str(WORK / '7z2605-x64.exe'), '-o' + str(output), '-y']
completed = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
(WORK / 'extract.stdout.bin').write_bytes(completed.stdout)
(WORK / 'extract.stderr.bin').write_bytes(completed.stderr)
(WORK / 'extract.json').write_text(json.dumps({'argv': command, 'exit_code': completed.returncode,
                                              'cwd': str(ROOT), 'files': sorted(path.relative_to(output).as_posix() for path in output.rglob('*') if path.is_file())}, ensure_ascii=False, indent=2), encoding='utf-8')
print('공식 배포 자료 추출 종료:', completed.returncode)
raise SystemExit(completed.returncode)
