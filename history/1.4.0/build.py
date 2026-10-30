"""Windows 실행 파일과 설치 파일을 재현하는 빌드 스크립트."""
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
match = re.search(r"^VERSION = (\d+)$", (ROOT / "app.py").read_text(encoding="utf-8"), re.MULTILINE)
if not match: raise SystemExit("app.py의 VERSION 상수를 확인해 주세요.")
version = int(match.group(1))
name = "FlipRing"
output = ROOT.parent / "프로그램"
if (output / name).exists() or (ROOT.parent / "설치파일" / (name + "-Setup.exe")).exists():
    raise SystemExit("기존 프로그램을 보존하기 위해 빌드를 중단합니다. 새 작업 폴더에서 빌드하세요.")
licenses = ROOT / "licenses"
licenses.mkdir(exist_ok=True)
# 실제 실행 구성요소와 소스 빌드에 사용하는 도구의 원문 고지를 함께 보존한다.
packages = [line.split("==", 1)[0] for line in (ROOT / "requirements-lock.txt").read_text(encoding="utf-8").splitlines() if "==" in line]
inventory = []
for package in packages:
    dist = metadata.distribution(package)
    target = licenses / package; target.mkdir(exist_ok=True)
    inventory.append({"name": dist.metadata["Name"], "version": dist.version, "homepage": dist.metadata.get("Home-page", ""), "license": dist.metadata.get("License-Expression", dist.metadata.get("License", ""))})
    for file in dist.files or []:
        value = str(file).replace("\\", "/")
        if ".dist-info/" in value and (any(x in value.lower() for x in ("license", "copying", "notice")) or value.endswith("METADATA")):
            source = Path(dist.locate_file(file))
            if source.is_file():
                destination = target / value.split(".dist-info/", 1)[1]
                destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, destination)
    if package == "pypdfium2":
        import pypdfium2_raw
        for source in Path(pypdfium2_raw.__file__).parent.rglob("*"):
            if source.is_file() and any(x in source.name.lower() for x in ("license", "notice", "copyright")):
                shutil.copy2(source, target / source.name)
(licenses / "구성요소.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
shutil.copy2(ROOT / "assets/NanumGothic-OFL.txt", licenses)
shutil.copy2(Path(sys.base_prefix) / "LICENSE.txt", licenses / "Python-LICENSE.txt")
image = Image.new("RGBA", (256, 256), (0, 0, 0, 0)); d = ImageDraw.Draw(image)
d.ellipse((8, 8, 248, 248), fill="#202020", outline="#eeeeee", width=14); d.ellipse((88, 88, 168, 168), outline="#eeeeee", width=14)
image.save(ROOT / "assets/app.ico", sizes=[(16, 16), (32, 32), (48, 48), (128, 128), (256, 256)])
spec = ROOT / (name + ".spec")
spec.write_text(f'''# Windows 배포에 필요한 Qt 기본 모듈만 포함한다.
from PyInstaller.utils.hooks import collect_data_files
a = Analysis([{str(ROOT / 'app.py')!r}], pathex=[{str(ROOT)!r}], binaries=[], datas=[({str(ROOT / 'assets')!r}, 'assets'), ({str(ROOT / 'vendor')!r}, 'vendor')] + collect_data_files('pypdfium2_raw'), hiddenimports=['PIL.AvifImagePlugin', 'PIL.WebPImagePlugin'], excludes=['tkinter', 'PySide6.QtWebEngineCore', 'PySide6.QtQml', 'PySide6.QtQuick'])
blocked = ('Qt6Pdf', 'Qt6Qml', 'Qt6Quick', 'Qt6VirtualKeyboard')
def required(entry):
    path = entry[0].replace('\\\\', '/')
    if any(part in path for part in blocked): return False
    if '/plugins/platforminputcontexts/' in path or '/plugins/qmltooling/' in path: return False
    if path.endswith('/qpdf.dll'): return False
    return True
a.binaries = [entry for entry in a.binaries if required(entry)]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name={name!r}, debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False, icon={str(ROOT / 'assets/app.ico')!r})
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name={name!r})
''', encoding="utf-8")
build_env = os.environ.copy()
# 개발 환경의 Poppler·Conda DLL이 Windows 시스템 ICU보다 먼저 수집되지 않게 한다.
build_env["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), sys.base_prefix, str(Path(os.environ["WINDIR"]) / "System32"), os.environ["WINDIR"]])
subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(output), "--workpath", str(ROOT / "build-cache"), str(spec)], check=True, cwd=ROOT, env=build_env)
shutil.copytree(licenses, output / name / "licenses", dirs_exist_ok=True)
shutil.copy2(ROOT / "LICENSE.txt", output / name / "LICENSE.txt")
shutil.copy2(ROOT / "사용안내.txt", output / name / "사용안내.txt")
iss = ROOT / "installer.iss"
iss.write_text(f'''; PUVKID 무료 배포판 설치 구성
[Setup]
AppId=PUVKID.FlipRing
AppName=FlipRing
AppVersion=1.4.0
AppPublisher=PUVKID
DefaultDirName={{localappdata}}\\Programs\\FlipRing
DefaultGroupName=FlipRing
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\\설치파일
OutputBaseFilename={name}-Setup
SetupIconFile=assets\\app.ico
UninstallDisplayIcon={{app}}\\{name}.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
LicenseFile=LICENSE.txt
InfoAfterFile=사용안내.txt
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "korean"; MessagesFile: "compiler:Languages\\Korean.isl"
[Files]
Source: "..\\프로그램\\{name}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Tasks]
Name: "desktopicon"; Description: "{{cm:CreateDesktopIcon}}"; Flags: unchecked
[Icons]
Name: "{{group}}\\FlipRing"; Filename: "{{app}}\\{name}.exe"
Name: "{{autodesktop}}\\FlipRing"; Filename: "{{app}}\\{name}.exe"; Tasks: desktopicon
[Registry]
Root: HKCU; Subkey: "Software\\Microsoft\\Windows\\CurrentVersion\\Run"; ValueName: "FlipRing"; Flags: uninsdeletevalue
''', encoding="utf-8-sig")
compiler = Path(os.environ.get("ISCC", ""))
if not compiler.is_file():
    for candidate in [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Inno Setup 6/ISCC.exe", Path("C:/Program Files (x86)/Inno Setup 6/ISCC.exe")]:
        if candidate.is_file(): compiler = candidate; break
if not compiler.is_file(): raise SystemExit("Inno Setup 6을 설치하거나 ISCC 환경 변수에 컴파일러 경로를 지정해 주세요.")
subprocess.run([str(compiler), str(iss)], check=True, cwd=ROOT)
print("빌드 완료:", output, ROOT.parent / "설치파일")
