"""한 폴더의 프로그램·설치 파일·전체 소스에 대한 SHA-256 목록을 생성한다."""
import hashlib
import json
from pathlib import Path
import re

root = Path(__file__).resolve().parent
name = "FlipRing"
release = root.parent
program = release / "프로그램" / name
installer = release / "설치파일" / (name + "-Setup.exe")
required = [program / (name + ".exe"), installer]
required += [program / "_internal/vendor/tesseract" / filename for filename in (
    "tesseract.exe", "tessdata/eng.traineddata", "tessdata/kor.traineddata", "tessdata/osd.traineddata",
)]
required += [root / filename for filename in (
    "app.py", "i18n.py", "engine.py", "pdf_tools.py", "pdf_panel.py", "test_pdf_tools.py",
    "build.py", "package.py", "test_gui.py", "test_engine.py",
    "requirements-lock.txt", "빌드방법.md", "사용안내.txt", "검토기록.md", "LICENSE.txt",
    "assets/NanumGothicBold.ttf", "assets/NanumGothic-OFL.txt", "test-fixtures/sample.heic",
    "vendor/tesseract/tesseract.exe", "vendor/tesseract/tessdata/eng.traineddata",
    "vendor/tesseract/tessdata/kor.traineddata", "vendor/tesseract/tessdata/osd.traineddata",
    "licenses/OCR/MSYS2-구성요소.json", "licenses/OCR/읽어주세요.md",
    "licenses/OCR/GPL-3.0.txt", "licenses/OCR/sources/tesseract-5.5.3.tar.gz",
    "licenses/OCR/ubuntu-gcc/출하목록.json",
)]
missing = [str(path.relative_to(release)) for path in required if not path.is_file()]
if missing:
    raise SystemExit("배포에 필요한 파일이 없습니다: " + ", ".join(missing))
if not (root / "licenses").is_dir() or not any((root / "licenses").iterdir()):
    raise SystemExit("소스의 licenses 폴더와 구성요소 자료를 확인해 주세요.")


def shipping_path(directory, value):
    """출하 목록의 상대 경로가 해당 자료 폴더 내부인지 확인한다."""
    if not isinstance(value, str) or not value or ":" in value:
        raise SystemExit("GCC 출하 목록의 파일 경로가 올바르지 않습니다.")
    relative = Path(value)
    if relative.anchor or ".." in relative.parts:
        raise SystemExit("GCC 출하 목록은 폴더 내부 상대 경로만 허용합니다: " + value)
    target = (directory / relative).resolve()
    if not target.is_relative_to(directory.resolve()) or target == directory.resolve():
        raise SystemExit("GCC 출하 목록의 경로가 자료 폴더를 벗어납니다: " + value)
    return target


def verify_gcc_sources(directory):
    """동봉한 GCC 원문 고지와 상응 소스의 크기·해시·누락을 검사한다."""
    manifest = directory / "출하목록.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SystemExit("GCC 출하 목록을 읽을 수 없습니다: " + str(manifest)) from error
    if not isinstance(data, dict) or data.get("actual_origin") != "Debian":
        raise SystemExit("GCC 출하 목록의 실제 Debian 출처를 확인해 주세요.")
    entries = data.get("files")
    metadata = data.get("include_metadata")
    if not isinstance(entries, list) or not entries or not isinstance(metadata, list) or not metadata:
        raise SystemExit("GCC 출하 목록의 파일과 메타데이터 목록이 비어 있거나 올바르지 않습니다.")
    checked = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise SystemExit("GCC 출하 목록의 파일 항목이 올바르지 않습니다.")
        target = shipping_path(directory, entry.get("path"))
        size, digest = entry.get("size"), entry.get("sha256")
        if type(size) is not int or size < 0 or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise SystemExit("GCC 출하 목록의 크기 또는 SHA-256이 올바르지 않습니다.")
        identity = str(target).casefold()
        if identity in checked:
            raise SystemExit("GCC 출하 목록에 중복 파일이 있습니다: " + str(target))
        checked.add(identity)
        if not target.is_file() or target.stat().st_size != size:
            raise SystemExit("GCC 상응 소스가 없거나 크기가 다릅니다: " + str(target))
        with target.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                raise SystemExit("GCC 상응 소스의 SHA-256이 다릅니다: " + str(target))
    for value in metadata:
        target = shipping_path(directory, value)
        if not target.is_file():
            raise SystemExit("GCC 출하 메타데이터가 없습니다: " + str(target))
    return manifest


# 소스 보관본과 고객 실행 폴더에 같은 고지·소스를 동봉했는지 각각 검증한다.
gcc_relative = Path("licenses/OCR/ubuntu-gcc")
source_manifest = verify_gcc_sources(root / gcc_relative)
program_manifest = verify_gcc_sources(program / gcc_relative)
if source_manifest.read_bytes() != program_manifest.read_bytes():
    raise SystemExit("소스와 프로그램의 GCC 출하 목록이 다릅니다.")

# 개발 환경과 빌드 캐시를 제외한 실제 소스 및 동봉 라이브러리 자료를 모두 기록한다.
excluded = {"build-cache", "__pycache__", ".venv", "venv"}
files = [path for path in program.rglob("*") if path.is_file()]
files.append(installer)
files.extend(path for path in root.rglob("*")
             if path.is_file() and not excluded.intersection(path.relative_to(root).parts))
entries = []
for path in sorted(files, key=lambda value: value.relative_to(release).as_posix()):
    with path.open("rb") as f: value = hashlib.file_digest(f, "sha256").hexdigest()
    entries.append(value + "  " + path.relative_to(release).as_posix())
(release / "SHA256SUMS.txt").write_text("\n".join(entries) + "\n", encoding="utf-8")
print("SHA-256 목록 생성:", release / "SHA256SUMS.txt", "파일", len(entries))
