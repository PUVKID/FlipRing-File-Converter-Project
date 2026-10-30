"""재배포 가능한 실행부와 해당 버전의 원문·상응 소스만 동봉한다."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent / '7zip-preparation'
vendor = ROOT / '소스/vendor/7zip'
licenses = ROOT / '소스/licenses/7Zip'
vendor.mkdir(parents=True, exist_ok=True)
(licenses / 'sources').mkdir(parents=True, exist_ok=True)


def sha(path):
    return hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()


# 이미 복사된 부분 자료는 공식 내려받기 및 압축 원문과 일치할 때만 마무리한다.
for item in json.loads((WORK / '다운로드검증.json').read_text(encoding='utf-8')):
    original = WORK / item['name']
    assert original.stat().st_size == item['size'] and sha(original) == item['sha256']
for name in ('7z.exe', '7z.dll'):
    if (vendor / name).exists(): assert sha(vendor / name) == sha(WORK / 'payload' / name)
archive = WORK / '7z2605-src.tar.xz'
if (licenses / 'sources' / archive.name).exists():
    assert sha(licenses / 'sources' / archive.name) == sha(archive)
with tarfile.open(archive, 'r:xz') as source:
    source_notice = source.extractfile('DOC/License.txt').read()
    for member, name in [('DOC/copying.txt', 'LGPL-2.1.txt'), ('DOC/unRarLicense.txt', 'unRarLicense.txt')]:
        if (licenses / name).exists(): assert (licenses / name).read_bytes() == source.extractfile(member).read()
    if (licenses / 'License.txt').exists():
        assert (licenses / 'License.txt').read_bytes() in (source_notice, (WORK / 'payload/License.txt').read_bytes())
    if (licenses / 'Source-License.txt').exists(): assert (licenses / 'Source-License.txt').read_bytes() == source_notice
entries = []
for name in ('7z.exe', '7z.dll'):
    shutil.copyfile(WORK / 'payload' / name, vendor / name)
    entries.append({'path': 'vendor/7zip/' + name, 'size': (vendor / name).stat().st_size, 'sha256': sha(vendor / name)})
archive = WORK / '7z2605-src.tar.xz'
shutil.copyfile(archive, licenses / 'sources' / archive.name)
entries.append({'path': 'licenses/7Zip/sources/' + archive.name, 'size': archive.stat().st_size, 'sha256': sha(archive)})
with tarfile.open(archive, 'r:xz') as source:
    for member, name in [('DOC/License.txt', 'Source-License.txt'), ('DOC/copying.txt', 'LGPL-2.1.txt'), ('DOC/unRarLicense.txt', 'unRarLicense.txt')]:
        data = source.extractfile(member).read()
        (licenses / name).write_bytes(data)
        entries.append({'path': 'licenses/7Zip/' + name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
shutil.copyfile(WORK / 'payload/License.txt', licenses / 'License.txt')
entries.append({'path': 'licenses/7Zip/License.txt', 'size': (licenses / 'License.txt').stat().st_size, 'sha256': sha(licenses / 'License.txt')})
manifest = {'version': '26.05', 'time_kst': datetime.now(timezone(timedelta(hours=9))).isoformat(),
            'origin': 'https://github.com/ip7z/7zip/releases/tag/26.05',
            'release_assets': json.loads((WORK.parent / '7zip-release-assets.json').read_text(encoding='utf-8')),
            'files': entries, 'source': '배포한 동일 버전의 전체 원문 소스 아카이브를 sources에 포함합니다.',
            'use': 'RAR 해제와 기존 ZIP/TAR 계열 출력용 입력에 사용합니다. RAR 압축 알고리즘을 재구현하거나 RAR을 생성하지 않습니다.',
            'not_shipped': ['설치 프로그램', '7zr 부트스트랩', '파일 관리자', '셸 확장']}
(licenses / '출하목록.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'version': manifest['version'], 'files': len(entries), 'vendor': str(vendor), 'licenses': str(licenses)}, ensure_ascii=False))
