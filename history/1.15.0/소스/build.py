"""Windows 배포 입력 준비와 소스 불변 컴파일을 분리한다."""
import argparse
import importlib.metadata as metadata
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import platform
import re
from datetime import datetime, timezone, timedelta
import 배포빌드 as delivery

ROOT = Path(__file__).resolve().parent

SPEC = "from pathlib import Path\nimport os\nsource = Path(os.environ['FLIPRING_SOURCE'])\n# Windows 배포에 필요한 Qt 기본 모듈만 포함한다.\nfrom PyInstaller.utils.hooks import collect_data_files\na = Analysis([str(source / 'app.py')], pathex=[str(source)], binaries=[], datas=[(str(source / 'assets'), 'assets'), (str(source / 'vendor'), 'vendor'), (str(source / 'document_bridge.py'), '.'), (str(source / 'document_formats.py'), '.'), (str(source / 'document_xlsb.py'), '.')] + collect_data_files('pypdfium2_raw') + collect_data_files('hwpx'), hiddenimports=['PIL.AvifImagePlugin', 'PIL.WebPImagePlugin'], excludes=['tkinter', 'PySide6.QtWebEngineCore', 'PySide6.QtQml', 'PySide6.QtQuick', 'olefile'])\nblocked = ('Qt6Pdf', 'Qt6Qml', 'Qt6Quick', 'Qt6VirtualKeyboard')\ndef required(entry):\n    path = entry[0].replace('\\\\', '/')\n    if any(part in path for part in blocked): return False\n    if '/plugins/platforminputcontexts/' in path or '/plugins/qmltooling/' in path: return False\n    if path.endswith('/qpdf.dll'): return False\n    return True\na.binaries = [entry for entry in a.binaries if required(entry)]\npyz = PYZ(a.pure)\nexe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='FlipRing', debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False, icon=str(source / 'assets/app.ico'), version=str(source / 'version-info.txt'))\ncoll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='FlipRing')\n"
ISS = '; PUVKID 무료 배포판 설치 구성\n[Setup]\nAppId=PUVKID.FlipRing19\nAppName=FlipRing\nAppVersion=1.15.0\nAppPublisher=PUVKID\nDefaultDirName={localappdata}\\Programs\\FlipRing19\nDefaultGroupName=FlipRing\nUsePreviousAppDir=no\nPrivilegesRequired=lowest\nArchitecturesAllowed=x64compatible\nArchitecturesInstallIn64BitMode=x64compatible\nMinVersion=10.0\nOutputDir={#GetEnv(\'FLIPRING_INSTALLER\')}\nOutputBaseFilename=FlipRing-Setup\nSetupIconFile={#GetEnv(\'FLIPRING_SOURCE\')}\\assets\\app.ico\nUninstallDisplayIcon={app}\\FlipRing.exe\nCompression=lzma2\nSolidCompression=yes\nWizardStyle=modern\nCloseApplications=yes\nRestartApplications=no\nLicenseFile={#GetEnv(\'FLIPRING_SOURCE\')}\\LICENSE.txt\nInfoAfterFile={#GetEnv(\'FLIPRING_PROGRAM\')}\\사용안내.txt\n[Languages]\nName: "english"; MessagesFile: "compiler:Default.isl"\nName: "korean"; MessagesFile: "compiler:Languages\\Korean.isl"\n[Files]\nSource: "{#GetEnv(\'FLIPRING_PROGRAM\')}\\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs\n[Registry]\nRoot: HKCU; Subkey: "Software\\Microsoft\\Windows\\CurrentVersion\\Run"; ValueName: "FlipRing19"; Flags: uninsdeletevalue\n[Run]\nFilename: "{app}\\FlipRing.exe"; Description: "FlipRing"; Flags: nowait postinstall skipifsilent\n'
VERSION = "VSVersionInfo(\n  ffi=FixedFileInfo(filevers=(1,15,0,0), prodvers=(1,15,0,0), mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0,0)),\n  kids=[StringFileInfo([StringTable('040904B0', [\n    StringStruct('CompanyName','PUVKID'), StringStruct('FileDescription','FlipRing'),\n    StringStruct('FileVersion','1.15.0'), StringStruct('ProductVersion','1.15.0'),\n    StringStruct('ProductName','FlipRing'), StringStruct('OriginalFilename','FlipRing.exe')\n  ])]), VarFileInfo([VarStruct('Translation',[1033,1200])])]\n)\n"

COMPILER_PROBE = "[Setup]\nAppName=FlipRingCompilerProbe\nAppVersion=1\nDefaultDirName={tmp}\\FlipRingCompilerProbe\nUninstallable=no\nOutput=no\nOutputDir=\nOutputManifestFile=\n"


def capture_compiler_probe(check):
    """설치 파일 없는 진단도 기존 Windows Job·유한 출력·시간 제한으로 실행한다."""
    path = ROOT.parent / "검사도구/release_capture.py"
    spec = importlib.util.spec_from_file_location("flipring_compiler_probe_capture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    previous = {name: os.environ.get(name) for name in ("TEMP", "TMP")}
    try:
        os.environ.update(TEMP=str(Path(check["cwd"]) / "임시"), TMP=str(Path(check["cwd"]) / "임시"))
        return module.run_check(check)
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def probe_compiler(compiler, probe_root):
    """PE 속성 대신 실제 엔진의 성공한 무출력 컴파일로 정확 버전과 두 파일을 확인한다."""
    probe = delivery.external_path(ROOT, probe_root)
    if probe.is_relative_to((ROOT.parent / "검사도구").resolve()) or probe.exists():
        raise delivery.DeliveryError("진단은 제품 입력·검사도구 밖의 새 작업 폴더만 허용합니다.")
    compiler = delivery.reject_links(compiler).resolve()
    engine = delivery.reject_links(compiler.with_name("ISCmplr.dll"))
    if not compiler.is_file() or not engine.is_file():
        raise delivery.DeliveryError("실제 ISCC 실행기와 ISCmplr.dll이 모두 필요합니다.")
    before = {"compiler_sha256": delivery.digest(compiler), "compiler_bytes": compiler.stat().st_size,
              "compiler_engine_sha256": delivery.digest(engine), "compiler_engine_bytes": engine.stat().st_size}
    probe.mkdir(parents=True)
    (probe / "임시").mkdir()
    script = probe / "진단.iss"
    script.write_text(COMPILER_PROBE, encoding="utf-8-sig", newline="\n")
    check = {"id": "inno-engine-probe", "argv": [str(compiler), "/O-", str(script)], "cwd": str(probe), "timeout_seconds": 15}
    delivery.save_new(probe / "실행요청.json", {"kst": datetime.now(timezone(timedelta(hours=9))).isoformat(), "check": check})
    result = capture_compiler_probe(check)
    delivery.save_new(probe / "실행결과.json", result)
    (probe / "실행원문.log").write_bytes(result.get("output", "").encode("utf-8"))
    names = {entry["path"] for entry in delivery.snapshot(probe)}
    if names - {"진단.iss", "실행요청.json", "실행결과.json", "실행원문.log"}:
        raise delivery.DeliveryError("무출력 엔진 진단에서 예상하지 않은 산출물이 생겼습니다.")
    if (result.get("status") != "passed" or result.get("exit_code") != 0 or not result.get("output_complete")
            or not result.get("output_bytes_complete") or result.get("output_truncated") or result.get("output_invalid_utf8")
            or result.get("capture_error") or result.get("cleanup_errors")):
        raise delivery.DeliveryError("엔진 진단의 실패·시간 초과·출력 미완료를 발견했습니다. 외부 진단 원문을 확인하세요.")
    text = result["output"]
    if result.get("output_bytes") != result.get("captured_bytes") or len(text.encode("utf-8")) != result.get("output_bytes"):
        raise delivery.DeliveryError("엔진 진단 출력의 실제 바이트 수가 일치하지 않습니다.")
    versions = re.findall(r"^Compiler engine version: Inno Setup (\d+\.\d+\.\d+(?:\.\d+)?)\r?$", text, re.MULTILINE)
    if len(versions) != 1 or not versions[0].startswith("6.") or re.search(r"^\s*Error(?:\s|:)", text, re.MULTILINE | re.IGNORECASE):
        raise delivery.DeliveryError("성공한 실제 Inno Setup 6 엔진 버전을 하나로 확인할 수 없습니다.")
    after = {"compiler_sha256": delivery.digest(compiler), "compiler_bytes": compiler.stat().st_size,
             "compiler_engine_sha256": delivery.digest(engine), "compiler_engine_bytes": engine.stat().st_size}
    if after != before or script.read_text(encoding="utf-8-sig") != COMPILER_PROBE:
        raise delivery.DeliveryError("엔진 진단 중 실행기·엔진 DLL·진단 입력이 바뀌었습니다.")
    return {"compiler_version": versions[0], **before}


def environment(compiler, probe_root):
    """고정 의존성과 실제 엔진 버전·ISCC/엔진 DLL 해시를 준비/빌드 양쪽에서 대조한다."""
    import struct
    if os.name != "nt" or sys.version_info[:2] != (3, 12) or struct.calcsize("P") != 8:
        raise delivery.DeliveryError("Windows·Python 3.12 x64 환경이 필요합니다.")
    compiler = delivery.reject_links(compiler).resolve(strict=True)
    packages = {}
    for line in (ROOT / "requirements-lock.txt").read_text(encoding="utf-8").splitlines():
        if "==" not in line:
            continue
        package, expected = line.split("==", 1)
        actual = metadata.version(package)
        if actual != expected:
            raise delivery.DeliveryError("고정 의존 버전 불일치: " + package + ": " + actual + " != " + expected)
        packages[package] = actual
    return {"python": platform.python_version(), "python_sha256": delivery.digest(sys.executable),
            "packages": packages, **probe_compiler(compiler, probe_root)}


PYPDFIUM_SUPPLEMENT = "licenses/data/windows_x64/BUILD_LICENSES/README.ijg"


def supplemental_pdfium_notice(source):
    """기존 공개 원문으로 고정된 추가 고지만 허용합니다."""
    path = delivery.reject_links(source / "licenses/pypdfium2" / PYPDFIUM_SUPPLEMENT)
    if (not path.is_file() or path.stat().st_size != 13059
            or delivery.digest(path) != "db16a04128171879c60708d171b88d97345a2dd20f9bfc173680a4497c73f704"):
        raise delivery.DeliveryError("추가 PDFium 고지 원문의 누락·변조: " + str(path))
    return path


def collect_legal_notices(source, packages):
    """패키지별 원문 목록을 먼저 확정하고 오래된 overlay 파일은 거부한다."""
    licenses = source / "licenses"
    inventory = []
    generated = []
    for package in packages:
        dist = metadata.distribution(package)
        target = licenses / package
        planned = {}
        inventory.append({"name": dist.metadata["Name"], "version": dist.version,
                          "homepage": dist.metadata.get("Home-page", ""),
                          "license": dist.metadata.get("License-Expression", dist.metadata.get("License", ""))})
        for file in dist.files or []:
            value = str(file).replace("\\", "/")
            if ".dist-info/" in value and (any(x in value.lower() for x in ("license", "copying", "notice")) or value.endswith("METADATA")):
                original = Path(dist.locate_file(file))
                if original.is_file():
                    planned[value.split(".dist-info/", 1)[1]] = original
        if package == "pypdfium2":
            import pypdfium2_raw
            for original in Path(pypdfium2_raw.__file__).parent.rglob("*"):
                if original.is_file() and any(x in original.name.lower() for x in ("license", "notice", "copyright")):
                    planned[original.name] = original
        if package == "pypdfium2":
            planned[PYPDFIUM_SUPPLEMENT] = supplemental_pdfium_notice(source)
        if package == "python-hwpx":
            # 정확 출하 원문과 출처는 고지 overlay에도 같은 항목으로 포함한다.
            for relative in ("sources/python_hwpx-6.12.0.tar.gz", "원본출처.json"):
                planned[relative] = source / "licenses/python-hwpx" / relative
        if not planned:
            raise delivery.DeliveryError("패키지 원문 고지·메타데이터를 찾을 수 없습니다: " + package)
        existing = {entry["path"] for entry in delivery.snapshot(target)} if target.exists() else set()
        if existing - set(planned):
            raise delivery.DeliveryError("오래된 패키지 고지 overlay 발견: " + package + ": " + repr(sorted(existing - set(planned))))
        for relative, original in planned.items():
            destination = target / delivery.relative_name(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if ((package == "python-hwpx" and relative in ("sources/python_hwpx-6.12.0.tar.gz", "원본출처.json"))
                    or (package == "pypdfium2" and relative == PYPDFIUM_SUPPLEMENT)):
                if not original.is_file():
                    raise delivery.DeliveryError("상응 소스·출처 원문이 없습니다: " + str(original))
            else:
                shutil.copy2(original, destination)
            generated.append(destination.relative_to(source.parent).as_posix())
    (licenses / "구성요소.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copy2(source / "assets/NanumGothic-OFL.txt", licenses / "NanumGothic-OFL.txt")
    shutil.copy2(Path(sys.base_prefix) / "LICENSE.txt", licenses / "Python-LICENSE.txt")
    generated.extend(["소스/licenses/구성요소.json", "소스/licenses/NanumGothic-OFL.txt", "소스/licenses/Python-LICENSE.txt"])
    return generated


def generate_build_inputs(source):
    from PIL import Image, ImageDraw
    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, 248, 248), fill="#202020", outline="#eeeeee", width=14)
    draw.ellipse((88, 88, 168, 168), outline="#eeeeee", width=14)
    image.save(source / "assets/app.ico", sizes=[(16, 16), (32, 32), (48, 48), (128, 128), (256, 256)])
    for filename, text in (("FlipRing.spec", SPEC), ("version-info.txt", VERSION), ("installer.iss", ISS)):
        (source / filename).write_text(text, encoding="utf-8-sig" if filename.endswith(".iss") else "utf-8", newline="\n")


def prepare(source, output, work, compiler):
    source = source.resolve(strict=True)
    root = source.parent
    output = delivery.external_path(root, output)
    work = delivery.external_path(root, work)
    if output == work or output.is_relative_to(work) or work.is_relative_to(output):
        raise delivery.DeliveryError("작업 폴더와 배포 폴더는 서로 분리해야 합니다.")
    if output.exists() or work.exists():
        raise delivery.DeliveryError("중단·이전 결과를 재사용하지 않습니다. 없는 새 폴더를 지정하세요.")
    config = delivery.load(source / "배포구성.json")
    # 고지 생성 전에 권한 보류 시험 입력과 정확 상응 소스 누락부터 거부한다.
    delivery.classified_entries(root, config)
    work.mkdir(parents=True)
    tools = environment(compiler, work / "컴파일러준비확인")
    legal_generated = collect_legal_notices(source, tools["packages"])
    generate_build_inputs(source)
    output.mkdir(parents=True)
    return {"schema": 1, "config": config, "config_path": "소스/배포구성.json", "source_root": str(root), "source_tree": delivery.snapshot(root),
            "environment": tools, "generated_files": sorted(set((legal_generated or []) + ["소스/FlipRing.spec", "소스/version-info.txt", "소스/installer.iss", "소스/assets/app.ico"]))}


def run_owned(source, argv, env, work, identity, timeout):
    """기존 Windows Job 수집기로 유한 출력·시간·소유 후손 종료를 유지한다."""
    path = source.parent / "검사도구/release_capture.py"
    spec = importlib.util.spec_from_file_location("flipring_release_capture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Inno 경고와 정상 로그를 보존하며 이 실행의 독립 수집 인스턴스만 한정한다.
    if identity == "inno":
        module.MAX_CAPTURE_BYTES = 256 * 1024
    previous = os.environ.copy()
    try:
        os.environ.update(env)
        result = module.run_check({"id": identity, "argv": argv, "cwd": str(source), "timeout_seconds": timeout})
    finally:
        os.environ.clear()
        os.environ.update(previous)
    delivery.save_new(work / (identity + ".json"), result)
    # 종료0과 출력 수집 성공을 구분하며 실패 원JSON은 위에서 먼저 보존한다.
    text = result.get("output")
    counts = (result.get("output_bytes"), result.get("captured_bytes"))
    valid_bytes = (isinstance(text, str) and all(type(value) is int and value >= 0 for value in counts)
                   and counts[0] == counts[1] == len(text.encode("utf-8")))
    if (result.get("status") != "passed" or type(result.get("exit_code")) is not int or result["exit_code"] != 0
            or result.get("output_complete") is not True or result.get("output_bytes_complete") is not True
            or result.get("output_truncated") is not False or result.get("output_invalid_utf8") is not False
            or result.get("output_display_truncated", False) is not False
            or result.get("capture_boundary_omitted_bytes", 0) != 0 or not valid_bytes
            or result.get("capture_error") or result.get("cleanup_errors") or result.get("error")):
        raise delivery.DeliveryError("컴파일 실패 또는 UTF-8 출력 수집 실패. 실행 원문을 보존했습니다: " + identity)


def compile_prepared(source, prepared, manifest, output, work, compiler):
    source = source.resolve(strict=True)
    root = source.parent
    output = delivery.external_path(root, output)
    work = delivery.external_path(root, work)
    delivery.verify_source_manifest(root, prepared, manifest, output / delivery.SOURCE_ZIP_NAME)
    if environment(compiler, work / "컴파일러재확인") != prepared["environment"]:
        raise delivery.DeliveryError("준비 이후 Python·고정 의존성·컴파일러가 변경됐습니다.")
    if (output / "프로그램").exists() or (output / "설치파일").exists() or (work / "pyinstaller.json").exists():
        raise delivery.DeliveryError("기존·중단 컴파일 산출물 재사용을 거부합니다.")
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PYINSTALLER_CONFIG_DIR=str(work / "pyinstaller-config"),
               FLIPRING_SOURCE=str(source), FLIPRING_PROGRAM=str(output / "프로그램/FlipRing"),
               FLIPRING_INSTALLER=str(output / "설치파일"), TEMP=str(work / "temp"), TMP=str(work / "temp"))
    (work / "temp").mkdir()
    env["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), sys.base_prefix,
                                    str(Path(os.environ["WINDIR"]) / "System32"), os.environ["WINDIR"]])
    try:
        run_owned(source, [sys.executable, "-B", "-X", "utf8", "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(output / "프로그램"),
                          "--workpath", str(work / "build-cache"), str(source / "FlipRing.spec")], env, work, "pyinstaller", 600)
    finally:
        delivery.assert_tree(root, prepared["source_tree"])
    program = output / "프로그램/FlipRing"
    delivery.stage_legal(source, program, manifest, prepared["config"])
    shutil.copy2(source / "LICENSE.txt", program / "LICENSE.txt")
    notice = (source / "사용안내.txt").read_text(encoding="utf-8") + "\n" + delivery.runtime_notice(manifest)
    (program / "사용안내.txt").write_text(notice, encoding="utf-8", newline="\n")
    try:
        run_owned(source, [str(compiler), str(source / "installer.iss")], env, work, "inno", 600)
    finally:
        delivery.assert_tree(root, prepared["source_tree"])
    print("컴파일 종료. 별도 package 검증·실제 실행·설치·독립 검토·원격 검증이 필요합니다.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--prepared", type=Path)
    parser.add_argument("--source-manifest", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--iscc", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    if args.prepare_only:
        if args.prepared or args.source_manifest or not args.manifest:
            parser.error("prepare-only에는 새 외부 --manifest만 지정하세요.")
        delivery.external_path(ROOT.parent, args.manifest)
        result = prepare(ROOT, args.output_root, args.work_root, args.iscc)
        delivery.save_new(args.manifest, result)
    else:
        if not args.prepared or not args.source_manifest:
            parser.error("컴파일에는 --prepared와 --source-manifest가 필요합니다.")
        compile_prepared(ROOT, delivery.load(args.prepared), delivery.load(args.source_manifest), args.output_root, args.work_root, args.iscc)


if __name__ == "__main__":
    try:
        main()
    except (delivery.DeliveryError, OSError, ValueError) as error:
        raise SystemExit("빌드 중단: " + str(error)) from error
