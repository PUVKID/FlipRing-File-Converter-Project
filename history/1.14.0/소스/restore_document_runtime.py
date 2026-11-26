"""공식 고정 버전의 문서 런타임과 상응 소스를 해시 검증 후 복원합니다."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def checked_download(url, target, size, sha256):
    """기존 파일을 덮어쓰지 않으며 새 다운로드의 길이와 원문 해시를 확인합니다."""
    if target.exists():
        if target.stat().st_size != size or digest(target) != sha256:
            raise RuntimeError("기존 파일의 크기나 해시가 다릅니다. 보존 후 확인해 주세요: " + str(target))
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="document-download-", dir=target.parent) as folder:
        incoming = Path(folder) / "download.bin"
        request = urllib.request.Request(url, headers={"User-Agent": "FlipRing-build"})
        with urllib.request.urlopen(request, timeout=60) as response, incoming.open("xb") as output:
            received = 0
            while chunk := response.read(1024 * 1024):
                received += len(chunk)
                if received > size:
                    raise RuntimeError("다운로드가 고정 크기를 초과했습니다.")
                output.write(chunk)
        if incoming.stat().st_size != size or digest(incoming) != sha256:
            raise RuntimeError("공식 다운로드의 크기 또는 SHA-256이 일치하지 않습니다.")
        with target.open("xb") as output, incoming.open("rb") as source:
            shutil.copyfileobj(source, output)


def verify_java(manifest):
    entries = [item for item in manifest["files"] if item["path"].startswith("vendor/java/")]
    expected = {item["path"][len("vendor/java/"):] for item in entries}
    actual = {p.relative_to(ROOT / "vendor/java").as_posix() for p in (ROOT / "vendor/java").rglob("*") if p.is_file()}
    if expected != actual:
        raise RuntimeError("Java 파일 목록이 고정 배포 원문과 다릅니다.")
    for item in entries:
        path = ROOT / item["path"]
        if path.stat().st_size != item["bytes"] or digest(path) != item["sha256"]:
            raise RuntimeError("Java 원문 해시가 다릅니다: " + item["path"])


def main():
    notices = ROOT / "licenses/Temurin17"
    manifest = json.loads((notices / "출하목록.json").read_text(encoding="utf-8"))
    package = manifest["runtime_archive"]
    target = ROOT / "vendor/java"
    if not target.exists():
        work = ROOT.parent / "work/document-runtime-restore"
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="restore-", dir=work) as folder:
            stage = Path(folder)
            archive = stage / package["name"]
            checked_download(package["link"], archive, package["size"], package["checksum"])
            with zipfile.ZipFile(archive) as zipped:
                for item in zipped.infolist():
                    name = PurePosixPath(item.filename)
                    if name.is_absolute() or ".." in name.parts or ":" in item.filename or "\\" in item.filename:
                        raise RuntimeError("Java 압축 경로가 올바르지 않습니다.")
                    if (item.external_attr >> 16) & 0o170000 == 0o120000:
                        raise RuntimeError("Java 압축에 링크가 포함되어 있습니다.")
                zipped.extractall(stage / "expanded")
            roots = [p for p in (stage / "expanded").iterdir() if p.is_dir()]
            if len(roots) != 1 or not (roots[0] / "bin/java.exe").is_file():
                raise RuntimeError("Java 압축 구조가 고정 버전과 다릅니다.")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(roots[0], target)
    verify_java(manifest)
    source = manifest["source_archive"]
    checked_download(source["browser_download_url"], notices / source["name"], source["size"], source["digest"].split(":", 1)[1])
    for name in ("NOTICE", "release"):
        checked = target / name
        destination = notices / name
        if checked.is_file() and not destination.exists():
            with checked.open("rb") as origin, destination.open("xb") as output:
                shutil.copyfileobj(origin, output)
    if not (notices / "legal").exists():
        shutil.copytree(target / "legal", notices / "legal")
    h2o = json.loads((ROOT / "licenses/H2Orestart/원본출처.json").read_text(encoding="utf-8"))
    for entry, path in ((h2o["binary"], ROOT / h2o["binary"]["file"]),
                        (h2o["source"], ROOT / "licenses/H2Orestart" / h2o["source"]["file"])):
        checked_download(entry["url"], path, entry["bytes"], entry["sha256"])
    print("문서 런타임의 고정 버전·해시와 전체 상응 소스를 확인했습니다.")


if __name__ == "__main__":
    main()
