"""준비 → 전체 소스 동결 → 불변 입력 컴파일의 배포 진입점과 공통 검사."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import zipfile

SOURCE_ZIP_NAME = "플립링-1.13.0-전체소스.zip"
RELEASE_URL = "https://github.com/PUVKID/FlipRing-File-Converter-Project/releases/tag/v1.13.0"
SOURCE_URL = "https://github.com/PUVKID/FlipRing-File-Converter-Project/releases/download/v1.13.0/" + "FlipRing-1.13.0-Source.zip"


class DeliveryError(RuntimeError):
    """누락·변조·안전 경계 실패는 다음 배포 단계를 차단한다."""


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def record(path, name):
    return {"path": name, "bytes": path.stat().st_size, "sha256": digest(path)}


def relative_name(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or "\x00" in value:
        raise DeliveryError("잘못된 상대 경로: " + repr(value))
    parts = value.split("/")
    if any(part in ("", ".", "..") or part.endswith((" ", ".")) for part in parts):
        raise DeliveryError("상대 경로 탈출 또는 모호한 이름: " + value)
    reserved = {"CON", "PRN", "AUX", "NUL", *("COM" + str(i) for i in range(1, 10)), *("LPT" + str(i) for i in range(1, 10))}
    if any(part.split(".")[0].upper() in reserved or any(c in part for c in '<>"|?*') for part in parts):
        raise DeliveryError("Windows에서 모호하거나 금지된 ZIP 경로: " + value)
    return value


def reject_links(path):
    path = Path(path).absolute()
    for parent in (path, *path.parents):
        if parent.exists() or parent.is_symlink():
            info = parent.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise DeliveryError("연결·재분석 지점은 허용하지 않습니다: " + str(parent))
    return path


def external_path(root, target):
    root = reject_links(root).resolve(strict=True)
    target = reject_links(target).resolve()
    if target == root or target.is_relative_to(root) or root.is_relative_to(target):
        raise DeliveryError("작업·출력은 입력 트리와 겹칠 수 없습니다: " + str(target))
    return target


def snapshot(root):
    root = reject_links(root).resolve(strict=True)
    result, seen = [], set()
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            reject_links(Path(directory) / name)
        for name in files:
            path = Path(directory) / name
            relative = relative_name(path.relative_to(root).as_posix())
            if relative.casefold() in seen:
                raise DeliveryError("대소문자 충돌: " + relative)
            seen.add(relative.casefold())
            result.append(record(path, relative))
    return sorted(result, key=lambda entry: entry["path"])


def assert_tree(root, expected):
    if snapshot(root) != expected:
        raise DeliveryError("동결 소스의 파일 추가·삭제·내용 변경을 발견했습니다.")


def save_new(path, data):
    path = reject_links(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def load(path):
    reject_links(path)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def classified_entries(root, config):
    if config.get("held_inputs"):
        raise DeliveryError("권한·필수 입력 보류 해소 전 동결 금지: " + repr(config["held_inputs"]))
    entries = snapshot(root)
    files = config["excluded_files"]
    dirs = config["excluded_dirs"]
    for mapping in (files, dirs):
        for name, reason in mapping.items():
            relative_name(name)
            if not isinstance(reason, str) or not reason.strip():
                raise DeliveryError("공개 제외 이유가 없습니다: " + name)
    included, excluded = [], {}
    for entry in entries:
        name = entry["path"]
        if config.get("source_roots") and name.split("/")[0] not in config["source_roots"] and name not in files:
            raise DeliveryError("분류되지 않은 입력 경로: " + name)
        reason = files.get(name)
        excluded_name = name
        if name.startswith("docs/") and name not in config.get("reviewed_public_docs", []) and name not in files:
            raise DeliveryError("개별 공개 분류가 없는 상위 문서: " + name)
        for directory, why in dirs.items():
            if name.startswith(directory + "/"):
                reason = why
                excluded_name = directory + "/"
        if reason:
            caches = {"__pycache__", ".venv", "venv", "build-cache"}
            product_code = name.startswith("소스/") and name.endswith(".py") and not caches.intersection(PurePosixPath(name).parts)
            product_data = name.startswith(("소스/assets/", "소스/vendor/", "소스/licenses/", "소스/test-fixtures/"))
            if name in config["required"] or product_code or product_data:
                raise DeliveryError("필수 입력·제품·빌드·검사 코드는 제외할 수 없습니다: " + name)
            excluded[excluded_name] = {"path": excluded_name, "reason": reason}
        else:
            included.append(entry)
    names = {entry["path"] for entry in included}
    for name in config["required"]:
        if name not in names:
            raise DeliveryError("필수 전체 소스 입력 누락: " + name)
    for entry in config["runtime_source_archive_allowlist"]:
        if entry not in included:
            raise DeliveryError("정확 원본 archive의 경로·크기·SHA 불일치: " + entry["path"])
    for entry in config.get("required_exact", []):
        if entry not in included:
            raise DeliveryError("공개 가능한 필수 입력의 정확 경로·크기·SHA 미확인: " + entry["path"])
    return included, [excluded[name] for name in sorted(excluded)]


def verify_zip(path, expected):
    expected_map = {relative_name(e["path"]): e for e in expected}
    if len(expected_map) != len(expected):
        raise DeliveryError("기대 ZIP 목록에 중복 경로가 있습니다.")
    seen = set()
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            name = relative_name(info.filename)
            if info.is_dir() or stat.S_ISLNK(info.external_attr >> 16):
                raise DeliveryError("ZIP 디렉터리·연결 항목은 허용하지 않습니다: " + name)
            if name.casefold() in seen or name not in expected_map:
                raise DeliveryError("ZIP 중복·대소문자 충돌·불명 추가: " + name)
            seen.add(name.casefold())
            entry = expected_map[name]
            with archive.open(info) as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if info.file_size != entry["bytes"] or actual != entry["sha256"]:
                raise DeliveryError("ZIP 파일 크기·SHA 불일치: " + name)
        if seen != {name.casefold() for name in expected_map}:
            raise DeliveryError("ZIP 필수 entry가 누락됐습니다.")


def freeze_source(root, prepared, target):
    root = Path(root)
    target = external_path(root, target)
    if target.name != SOURCE_ZIP_NAME:
        raise DeliveryError("고정 전체 소스 ZIP 파일명을 유지해 주세요.")
    assert_tree(root, prepared["source_tree"])
    entries, excluded = classified_entries(root, prepared["config"])
    partial = target.with_suffix(target.suffix + ".partial")
    if target.exists() or partial.exists():
        raise DeliveryError("기존 ZIP·중단 산출물을 재사용하지 않습니다.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(partial, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        for entry in entries:
            archive.write(root / entry["path"], entry["path"])
    verify_zip(partial, entries)
    assert_tree(root, prepared["source_tree"])
    partial.rename(target)
    return {"schema": 1, "version": prepared["config"]["version"], "file": target.name,
            "bytes": target.stat().st_size, "sha256": digest(target), "entries": entries,
            "excluded": excluded, "release_url": RELEASE_URL, "source_url": SOURCE_URL,
            "url_verified": False}


def verify_source_manifest(root, prepared, manifest, archive):
    assert_tree(root, prepared["source_tree"])
    if prepared.get("config_path") and load(Path(root) / relative_name(prepared["config_path"])) != prepared["config"]:
        raise DeliveryError("외부 준비 manifest의 배포 구성이 동결 구성과 다릅니다.")
    entries, excluded = classified_entries(root, prepared["config"])
    if manifest.get("entries") != entries or manifest.get("excluded") != excluded:
        raise DeliveryError("전체 소스 분류와 외부 manifest가 다릅니다.")
    if (manifest.get("file") != SOURCE_ZIP_NAME or manifest.get("version") != "1.13.0"
            or manifest.get("release_url") != RELEASE_URL or manifest.get("source_url") != SOURCE_URL):
        raise DeliveryError("전체 소스의 버전·파일명·예정 URL이 다릅니다.")
    archive = reject_links(archive)
    if archive.stat().st_size != manifest["bytes"] or digest(archive) != manifest["sha256"]:
        raise DeliveryError("전체 소스 ZIP 크기·SHA 불일치")
    verify_zip(archive, entries)


class ZipFileValue:
    def __init__(self, archive, entry):
        self.archive, self.entry = archive, entry

    def is_file(self):
        return True

    def stat(self):
        from types import SimpleNamespace
        return SimpleNamespace(st_size=self.entry["bytes"])

    @contextmanager
    def open(self, mode="rb"):
        if mode != "rb":
            raise DeliveryError("ZIP 소스는 읽기만 허용합니다.")
        # 큰 상응 소스를 메모리 전체에 올리지 않고 ZIP과 entry 수명을 함께 닫는다.
        with zipfile.ZipFile(self.archive) as archive:
            with archive.open(self.entry["path"]) as stream:
                yield stream

    def read_bytes(self):
        with zipfile.ZipFile(self.archive) as archive:
            return archive.read(self.entry["path"])


class ArchiveResolver:
    def __init__(self, runtime, archive, manifest, config):
        self.runtime = reject_links(runtime).resolve(strict=True)
        self.archive = reject_links(archive)
        if digest(self.archive) != manifest["sha256"] or self.archive.stat().st_size != manifest["bytes"]:
            raise DeliveryError("해석할 전체 소스 ZIP 변조")
        verify_zip(self.archive, manifest["entries"])
        self.allowed = {}
        for entry in config["runtime_source_archive_allowlist"]:
            if entry not in manifest["entries"] or not entry["path"].startswith("소스/licenses/"):
                raise DeliveryError("허용 archive가 정확 전체 소스에 없습니다.")
            relative = entry["path"].removeprefix("소스/")
            if (self.runtime / relative).exists():
                raise DeliveryError("실행 폴더에 분리 대상 archive가 잔존합니다: " + relative)
            self.allowed[relative] = entry

    def resolve(self, path):
        path = reject_links(path).resolve()
        if not path.is_relative_to(self.runtime):
            raise DeliveryError("실행 자료 경로 탈출")
        if path.is_file():
            return path
        entry = self.allowed.get(path.relative_to(self.runtime).as_posix())
        if entry is None:
            raise DeliveryError("허용 목록 밖 실행 자료 누락: " + str(path))
        return ZipFileValue(self.archive, entry)


def runtime_notice(manifest):
    return ("플립링 1.13.0 전체 상응 소스\n파일: " + manifest["file"] + "\nSHA-256: " + manifest["sha256"]
            + "\n동일 Release: " + manifest["release_url"] + "\n정확 소스 자산: " + manifest["source_url"]
            + "\n고객 배포 폴더의 같은 전체 소스 ZIP과 원문 고지·패치·빌드 방법을 보존해 주세요.\n"
            "온라인 재배포자는 같은 장소에서 무료로 동등한 상응 소스 접근을 제공할 수 있습니다.\n"
            "원 개발자의 URL만 남겨 자신의 소스 제공 의무가 자동 면제되는 것은 아닙니다.\n"
            "호환 Qt/PySide 동적 라이브러리 교체와 수정 디버깅을 위한 역공학을 제한하지 않습니다.\n")


def stage_legal(source, program, manifest, config):
    import shutil
    target = program / "licenses"
    if target.exists():
        raise DeliveryError("오래된 고지 overlay를 막기 위해 새 고지 폴더가 필요합니다.")
    allowed = {entry["path"].removeprefix("소스/") for entry in config["runtime_source_archive_allowlist"]}
    expected = []
    for entry in snapshot(source / "licenses"):
        relative = "licenses/" + entry["path"]
        if relative in allowed:
            continue
        destination = program / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, destination)
        expected.append(entry)
    if snapshot(target) != expected:
        raise DeliveryError("실행 고지 목록·내용이 원문과 다릅니다.")
    (target / "전체소스_안내.txt").write_text(runtime_notice(manifest), encoding="utf-8", newline="\n")
    save_new(target / "상응소스_배치.json", {"source": {key: manifest[key] for key in ("file", "bytes", "sha256", "source_url", "release_url")},
              "runtime_excluded": config["runtime_source_archive_allowlist"]})


def verify_runtime_legal(source, program, manifest, config):
    expected = {entry["path"]: entry for entry in snapshot(source / "licenses")}
    for entry in config["runtime_source_archive_allowlist"]:
        expected.pop(entry["path"].removeprefix("소스/licenses/"))
    actual = {entry["path"]: entry for entry in snapshot(program / "licenses")}
    for name in ("전체소스_안내.txt", "상응소스_배치.json"):
        if name not in actual:
            raise DeliveryError("동결 소스 고지·배치 안내 누락: " + name)
        actual.pop(name)
    if actual != expected:
        raise DeliveryError("실행 원 고지·패치·recipe의 누락·추가·변조")
    if (program / "licenses/전체소스_안내.txt").read_text(encoding="utf-8") != runtime_notice(manifest):
        raise DeliveryError("동결 전체 소스 고지 URL·SHA·안내 불일치")
    placement = load(program / "licenses/상응소스_배치.json")
    if placement != {"source": {key: manifest[key] for key in ("file", "bytes", "sha256", "source_url", "release_url")},
                     "runtime_excluded": config["runtime_source_archive_allowlist"]}:
        raise DeliveryError("상응 소스 배치 manifest 불일치")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--iscc", type=Path, required=True)
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    root = source.parent
    output = external_path(root, args.output_root)
    work = external_path(root, args.work_root)
    for path in (output, work):
        if path.exists():
            raise DeliveryError("새 작업·출력 폴더를 지정해 주세요: " + str(path))
    import build
    prepared = build.prepare(source, output, work, args.iscc)
    prepared_path = work / "준비_manifest.json"
    save_new(prepared_path, prepared)
    manifest = freeze_source(root, prepared, output / SOURCE_ZIP_NAME)
    manifest_path = output / "전체소스_manifest.json"
    save_new(manifest_path, manifest)
    build.compile_prepared(source, prepared, manifest, output, work, args.iscc)
    subprocess.run([sys.executable, "-B", "-X", "utf8", str(source / "package.py"), "--release-root", str(output),
                    "--source-manifest", str(manifest_path), "--prepared", str(prepared_path)], check=True, cwd=source, timeout=600)


if __name__ == "__main__":
    try:
        main()
    except (DeliveryError, OSError, subprocess.SubprocessError, ValueError) as error:
        raise SystemExit("배포 중단: " + str(error)) from error
