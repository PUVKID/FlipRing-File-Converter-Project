"""별도 staging의 전체 소스 ZIP·실행부·설치·법적 고지를 검증한다."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile
import 배포빌드 as delivery


def verify_verification_tools(source, archive, source_data):
    """필수 검사도구 여섯 원본을 전체 소스 ZIP의 정확 항목과 대조한다."""
    filenames = ("regression19.py", "new_suites19.py", "run_new_suite19.py", "release_capture.py",
                 "documents_suites110.py", "run_documents_suite110.py")
    checked = []
    with zipfile.ZipFile(delivery.reject_links(archive)) as bundle:
        infos = bundle.infolist()
        for filename in filenames:
            name = "검사도구/" + filename
            original = delivery.reject_links(source.parent / "검사도구" / filename)
            if not original.is_file():
                raise delivery.DeliveryError("원본 필수 검사도구가 없습니다: " + name)
            expected = delivery.record(original, name)
            recorded = [entry for entry in source_data["entries"] if entry.get("path") == name]
            matches = [info for info in infos if info.filename == name]
            if recorded != [expected] or len(matches) != 1 or matches[0].file_size != expected["bytes"]:
                raise delivery.DeliveryError("전체 소스 ZIP의 필수 검사도구 누락·중복·크기·목록 불일치: " + name)
            with bundle.open(matches[0]) as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != expected["sha256"]:
                raise delivery.DeliveryError("전체 소스 ZIP의 필수 검사도구 SHA 불일치: " + name)
            checked.append(expected)
    return checked


def main():
    root = Path(__file__).resolve().parent
    name = "FlipRing"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--prepared", type=Path, required=True)
    args = parser.parse_args()
    release = delivery.external_path(root.parent, args.release_root)
    prepared = delivery.load(args.prepared)
    source_data = delivery.load(args.source_manifest)
    archive = release / delivery.SOURCE_ZIP_NAME
    delivery.verify_source_manifest(root.parent, prepared, source_data, archive)
    resolver = delivery.ArchiveResolver(release / "프로그램/FlipRing", archive, source_data, prepared["config"])
    def resolved_file(path):
        if path.is_relative_to(release / "프로그램/FlipRing"):
            return resolver.resolve(path)
        delivery.reject_links(path)
        return path
    program = release / "프로그램" / name
    delivery.snapshot(program)
    installer = release / "설치파일" / (name + "-Setup.exe")
    required = [program / (name + ".exe"), installer]
    required.append(program / "_internal/assets/combo-chevron.svg")
    lucide_icons = (
        "arrow-left-right", "scan-text", "rotate-ccw-clock", "sliders-horizontal", "info", "folder-open",
        "file-up", "check", "x", "arrow-up-right", "plus", "file",
    )
    for icon in lucide_icons:
        required += [root / "assets/lucide" / (icon + ".svg"),
                     program / "_internal/assets/lucide" / (icon + ".svg")]
    for filename in ("LICENSE", "원본출처.json"):
        required += [root / "licenses/Lucide" / filename, program / "licenses/Lucide" / filename]
    required += [program / "_internal/vendor/tesseract" / filename for filename in (
        "tesseract.exe", "tessdata/eng.traineddata", "tessdata/kor.traineddata", "tessdata/osd.traineddata",
    )]
    required += [program / "_internal/assets/fonts" / filename for filename in (
        "SUIT-Regular.ttf", "SUIT-Medium.ttf", "SUIT-SemiBold.ttf",
    )]
    required += [program / "licenses/SUIT" / filename for filename in ("OFL.txt", "원본출처.json")]
    required += [directory / filename for directory in (root / "vendor/7zip", program / "_internal/vendor/7zip")
                 for filename in ("7z.exe", "7z.dll")]
    required += [directory / filename for directory in (root / "licenses/7Zip", program / "licenses/7Zip")
                 for filename in ("License.txt", "Source-License.txt", "LGPL-2.1.txt", "unRarLicense.txt", "출하목록.json", "sources/7z2605-src.tar.xz")]
    required += [root / filename for filename in (
        "document_hwp.py", "hwp_worker.py", "test_document_hwp.py", "test_hwp_worker.py",
        "app.py", "i18n.py", "studio_ui.py", "ui_motion.py", "engine.py",
        "document_formats.py", "document_bridge.py", "document_process.py", "document_xlsb.py", "test_document_xlsb.py", "test_document_external.py", "test_document_security.py", "test_document_shutdown.py", "restore_document_runtime.py", "test_document_formats.py", "test_documents_integration.py", "test_documents_ui110.py", "1.10-문서지원안내.md", "pdf_tools.py", "pdf_panel.py", "test_pdf_tools.py",
        "flipring_workflow.py", "preview_panel.py", "pdf_pages.py", "pdf_lock.py", "test_workbench.py", "test_pdf_workspace.py",
        "fixed_viewport.py", "test_fixed_layout.py", "build.py", "package.py", "test_gui.py", "test_engine.py", "test_conversion_matrix.py",
        "workspace_core.py", "workspace_ui.py", "inspection_tools.py", "inspection_ui.py",
        "test_workspace_core.py", "test_workspace_ui.py", "test_inspection_tools.py", "test_ocr_process.py", "1.9-확장안내.md",
        "requirements-documents-test.txt", "licenses/test-dependencies/olefile-0.47-LICENSE.txt",
        "offscreen-monitor.json", "requirements-lock.txt", "빌드방법.md", "사용안내.txt", "1.7-새기능안내.md", "1.8-화면안내.md", "LICENSE.txt",
        "assets/NanumGothicBold.ttf", "assets/NanumGothic-OFL.txt", "test-fixtures/sample.heic",
        "assets/combo-chevron.svg",
        "assets/fonts/SUIT-Regular.ttf", "assets/fonts/SUIT-Medium.ttf", "assets/fonts/SUIT-SemiBold.ttf",
        "licenses/SUIT/OFL.txt", "licenses/SUIT/원본출처.json",
        "vendor/tesseract/tesseract.exe", "vendor/tesseract/tessdata/eng.traineddata",
        "vendor/tesseract/tessdata/kor.traineddata", "vendor/tesseract/tessdata/osd.traineddata",
        "licenses/OCR/MSYS2-구성요소.json", "licenses/OCR/읽어주세요.md",
        "licenses/OCR/GPL-3.0.txt", "licenses/OCR/sources/tesseract-5.5.3.tar.gz",
        "licenses/OCR/ubuntu-gcc/출하목록.json",
    )]
    verify_verification_tools(root, archive, source_data)
    required += [program / "_internal" / name for name in ("document_bridge.py", "document_formats.py", "document_xlsb.py")]
    required += [program / "_internal/hwpx" / name for name in (
        "data/Skeleton.hwpx", "form_fit/_glyph_table.json.gz", "tools/_schemas/header.xsd",
        "tools/_schemas/owpml-body.xsd", "tools/_schemas/owpml-core.xsd", "tools/_schemas/owpml-header.xsd",
        "tools/_schemas/owpml-paralist.xsd", "tools/_schemas/owpml-xml.xsd", "tools/_schemas/section.xsd")]
    required += [directory / "licenses/python-hwpx" / name for directory in (root, program)
                 for name in ("METADATA", "licenses/LICENSE", "licenses/NOTICE", "원본출처.json", "sources/python_hwpx-6.12.0.tar.gz")]
    required += [directory / "vendor/h2orestart/H2Orestart.oxt" for directory in (root, program / "_internal")]
    required += [directory / "licenses/H2Orestart" / name for directory in (root, program)
                 for name in ("COPYING", "H2Orestart-v0.8.0-source.tar.gz", "원본출처.json")]
    required += [directory / "vendor/java/bin/java.exe" for directory in (root, program / "_internal")]
    required += [directory / "licenses/Temurin17" / name for directory in (root, program)
                 for name in ("출하목록.json", "OpenJDK17U-jdk-sources_17.0.21_9.tar.gz")]
    # Rust 실행부와 재빌드 원문을 소스·실행 묶음 양쪽에서 확인합니다.
    required += [root / name for name in (
        'astryx_theme.py', 'runtime_paths.py', 'rust/astryx-theme/Cargo.toml',
        'rust/astryx-theme/Cargo.lock', 'rust/astryx-theme/src/main.rs',
    )]
    required += [directory / 'vendor/astryx/astryx-theme.exe' for directory in (root, program / '_internal')]
    required += [directory / 'licenses/Astryx' / name for directory in (root, program)
                 for name in ('Astryx-MIT-LICENSE.txt', '읽어주세요.md', '출하목록.json')]
    missing = [str(path) for path in required if not resolved_file(path).is_file()]
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
            target = resolved_file(shipping_path(directory, entry.get("path")))
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


    def verify_7zip(vendor, notices):
        """동일 버전의 실행부·두 원문 고지·전체 상응 소스를 누락 없이 대조한다."""
        manifest = notices / "출하목록.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if data.get("version") != "26.05":
            raise SystemExit("7-Zip 고정 버전이 일치하지 않습니다.")
        expected = {"vendor/7zip/" + name: vendor / name for name in ("7z.exe", "7z.dll")}
        expected.update({"licenses/7Zip/" + name: notices / name for name in (
            "License.txt", "Source-License.txt", "LGPL-2.1.txt", "unRarLicense.txt", "sources/7z2605-src.tar.xz")})
        files = data.get("files")
        if not isinstance(files, list) or len(files) != len(expected) or any(not isinstance(entry, dict) for entry in files):
            raise SystemExit("7-Zip 출하 목록의 항목 수와 형식이 올바르지 않습니다.")
        paths = [entry.get("path") for entry in files]
        if any(not isinstance(path, str) for path in paths) or len(set(paths)) != len(paths) or set(paths) != set(expected):
            raise SystemExit("7-Zip 출하 목록의 경로가 누락·중복되거나 범위를 벗어납니다.")
        for entry in files:
            path = resolved_file(expected[entry["path"]])
            size, digest = entry.get("size"), entry.get("sha256")
            if type(size) is not int or size < 0 or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise SystemExit("7-Zip 출하 목록의 크기·해시 형식이 올바르지 않습니다.")
            if not path.is_file() or path.stat().st_size != size:
                raise SystemExit("7-Zip 실행부·원문·소스가 누락되거나 크기가 다릅니다: " + str(path))
            with path.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                    raise SystemExit("7-Zip 자료의 SHA-256이 다릅니다: " + str(path))
        return manifest


    # 소스 보관본과 고객 실행 폴더에 같은 고지·소스를 동봉했는지 각각 검증한다.
    gcc_relative = Path("licenses/OCR/ubuntu-gcc")
    source_manifest = verify_gcc_sources(root / gcc_relative)
    program_manifest = verify_gcc_sources(program / gcc_relative)
    if source_manifest.read_bytes() != program_manifest.read_bytes():
        raise SystemExit("소스와 프로그램의 GCC 출하 목록이 다릅니다.")
    source_7zip = verify_7zip(root / "vendor/7zip", root / "licenses/7Zip")
    program_7zip = verify_7zip(program / "_internal/vendor/7zip", program / "licenses/7Zip")
    if source_7zip.read_bytes() != program_7zip.read_bytes():
        raise SystemExit("소스와 프로그램의 7-Zip 출하 목록이 다릅니다.")

    # 별도 Office Python이 읽는 브리지 원문과 Java의 실행부·상응 소스도 대조한다.
    for name in ("document_bridge.py", "document_formats.py", "document_xlsb.py"):
        if (root / name).read_bytes() != (program / "_internal" / name).read_bytes():
            raise SystemExit("문서 브리지 원문이 실행 폴더와 다릅니다: " + name)
    h2o_origin = json.loads((root / "licenses/H2Orestart/원본출처.json").read_text(encoding="utf-8"))
    for base in (root, program):
        for entry, relative in ((h2o_origin["binary"], "vendor/h2orestart/H2Orestart.oxt"),
                                (h2o_origin["source"], "licenses/H2Orestart/" + h2o_origin["source"]["file"])):
            target = resolved_file((base / "_internal" if base == program and relative.startswith("vendor/") else base) / relative)
            if target.stat().st_size != entry["bytes"]:
                raise SystemExit("H2Orestart 원문의 크기가 다릅니다: " + str(target))
            with target.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != entry["sha256"]:
                    raise SystemExit("H2Orestart 원문의 SHA-256이 다릅니다: " + str(target))
    for name in ("COPYING", "원본출처.json"):
        if (root / "licenses/H2Orestart" / name).read_bytes() != (program / "licenses/H2Orestart" / name).read_bytes():
            raise SystemExit("H2Orestart 고지 원문이 실행 폴더와 다릅니다: " + name)
    java_manifest = json.loads((root / "licenses/Temurin17/출하목록.json").read_text(encoding="utf-8"))
    for entry in java_manifest["files"]:
        relative = Path(entry["path"])
        for base in (root, program):
            target = resolved_file(shipping_path(base / "_internal" if relative.parts[0] == "vendor" and base == program else base, entry["path"]))
            if not target.is_file() or target.stat().st_size != entry["bytes"]:
                raise SystemExit("Java 배포 파일이 누락되거나 크기가 다릅니다: " + str(target))
            with target.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != entry["sha256"]:
                    raise SystemExit("Java 배포 파일 해시가 다릅니다: " + str(target))
    if (root / "licenses/Temurin17/출하목록.json").read_bytes() != (program / "licenses/Temurin17/출하목록.json").read_bytes():
        raise SystemExit("Java 출하 목록이 실행 폴더와 다릅니다.")

    # 개발 환경과 빌드 캐시를 제외한 실제 소스 및 동봉 라이브러리 자료를 모두 기록한다.
    excluded = {"build-cache", "__pycache__", ".venv", "venv"}
    files = [path for path in program.rglob("*") if path.is_file()]
    files.append(installer)
    # 전체 소스의 정확 공개 목록은 ZIP 전체 검증으로 확인했고 운영 기록은 포함하지 않는다.
    files.append(archive)
    source_manifest_path = delivery.reject_links(args.source_manifest).resolve(strict=True)
    if source_manifest_path.is_relative_to(release):
        files.append(source_manifest_path)
    delivery.verify_runtime_legal(root, program, source_data, prepared["config"])
    for item in delivery.snapshot(root / "vendor"):
        runtime = program / "_internal/vendor" / item["path"]
        if not runtime.is_file() or runtime.stat().st_size != item["bytes"] or delivery.digest(runtime) != item["sha256"]:
            raise SystemExit("실행 vendor 원본과 소스 불일치: " + item["path"])
    delivery.assert_tree(root.parent, prepared["source_tree"])
    entries = []
    for path in sorted(files, key=lambda value: value.relative_to(release).as_posix()):
        with path.open("rb") as f: value = hashlib.file_digest(f, "sha256").hexdigest()
        entries.append(value + "  " + path.relative_to(release).as_posix())
    (release / "SHA256SUMS.txt").write_text("\n".join(entries) + "\n", encoding="utf-8")
    print("SHA-256 목록 생성:", release / "SHA256SUMS.txt", "파일", len(entries))


if __name__ == "__main__":
    try:
        main()
    except (delivery.DeliveryError, OSError, ValueError) as error:
        raise SystemExit("포장 중단: " + str(error)) from error
