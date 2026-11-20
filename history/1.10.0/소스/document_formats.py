"""대표 문서의 읽기·쓰기 방향과 로컬 도우미를 한곳에서 정의한다."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
import zipfile


DOCUMENT_INPUTS = "hwp hwpx doc docx docm dot dotx dotm odt ott fodt rtf txt md html xhtml epub pages wpd abw sxw stw"
PRESENTATION_INPUTS = "ppt pptx pptm pot potx potm pps ppsx ppsm odp otp fodp key"
SPREADSHEET_INPUTS = "xls xlsx xlsb xlsm xlt xltx xltm ods ots fods csv tsv dif slk numbers"
DOCUMENT_OUTPUTS = "docx doc odt rtf md txt epub html pdf jpg png"
PRESENTATION_OUTPUTS = "pptx ppt odp pdf jpg png txt"
SPREADSHEET_OUTPUTS = "xlsx xls ods csv tsv pdf html"
SIMPLE_TEXT = {"md", "txt", "html", "xhtml", "epub"}
OFFICE_DOCUMENTS = set(DOCUMENT_INPUTS.split()) - SIMPLE_TEXT

EXPORT_FILTERS = {
    "문서": {"docx": "Office Open XML Text", "doc": "MS Word 97", "odt": "writer8",
             "rtf": "Rich Text Format", "txt": "Text (encoded)", "html": "HTML (StarWriter)",
             "pdf": "writer_pdf_Export", "epub": "EPUB"},
    "프레젠테이션": {"pptx": "Impress MS PowerPoint 2007 XML", "ppt": "MS PowerPoint 97",
                    "odp": "impress8", "pdf": "impress_pdf_Export"},
    "스프레드시트": {"xlsx": "Calc MS Excel 2007 XML", "xls": "MS Excel 97", "ods": "calc8",
                    "csv": "Text - txt - csv (StarCalc)", "tsv": "Text - txt - csv (StarCalc)",
                    "pdf": "calc_pdf_Export", "html": "HTML (StarCalc)"},
}


def support_matrix():
    """입력 전용 형식과 출력 전용 형식을 혼동하지 않는 정적 안내를 반환한다."""
    return [
        {"kind": "문서", "inputs": DOCUMENT_INPUTS.split(), "outputs": DOCUMENT_OUTPUTS.split(),
         "notes": "HWP/HWPX는 읽기 전용이며 H2Orestart와 Java가 필요합니다. 매크로는 실행하지 않습니다."},
        {"kind": "프레젠테이션", "inputs": PRESENTATION_INPUTS.split(), "outputs": PRESENTATION_OUTPUTS.split(),
         "notes": "전용 효과·글꼴·차트는 원본과 다를 수 있습니다. TXT는 슬라이드의 텍스트만 저장합니다."},
        {"kind": "스프레드시트", "inputs": SPREADSHEET_INPUTS.split(), "outputs": SPREADSHEET_OUTPUTS.split(),
         "notes": "XLSB·매크로·템플릿은 입력 전용입니다. CSV/TSV는 첫 시트이며 수식 대신 표시값을 저장합니다."},
    ]


def office_python(office_path):
    """실제 LibreOffice 설치의 UNO Python만 선택한다."""
    if not office_path:
        return None
    program = Path(office_path).resolve().parent
    candidate = program / ("python.exe" if os.name == "nt" else "python")
    return str(candidate) if candidate.is_file() else None


def java_path():
    """설치 상태 표시에서는 프로세스를 실행하지 않고 실제 파일만 찾는다."""
    exe = "java.exe" if os.name == "nt" else "java"
    roots = [Path(__file__).resolve().parent / "vendor/java"]
    if os.environ.get("JAVA_HOME"):
        roots.append(Path(os.environ["JAVA_HOME"]))
    for root in roots:
        if (root / "bin" / exe).is_file():
            return str((root / "bin" / exe).resolve())
    found = shutil.which(exe)
    if found:
        return found
    if os.name == "nt":
        # Java 설치 프로그램의 공인 등록 위치와 앱별 사용자 설치 위치만 살핀다.
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for key in (r"SOFTWARE\JavaSoft\JRE", r"SOFTWARE\JavaSoft\Java Runtime Environment",
                        r"SOFTWARE\JavaSoft\JDK", r"SOFTWARE\JavaSoft\Java Development Kit"):
                try:
                    with winreg.OpenKey(hive, key) as handle:
                        version = winreg.QueryValueEx(handle, "CurrentVersion")[0]
                    with winreg.OpenKey(hive, key + "\\" + version) as handle:
                        location = Path(winreg.QueryValueEx(handle, "JavaHome")[0])
                    if (location / "bin" / exe).is_file():
                        return str(location / "bin" / exe)
                except OSError:
                    continue
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        for base in (local / "Programs/Eclipse Adoptium", local / "Programs/Java", local / "Programs/FlipRing-Java"):
            if base.is_dir():
                for candidate in sorted(base.glob("*/bin/java.exe"), reverse=True):
                    if candidate.is_file():
                        return str(candidate)
    return None


def hwp_status(office_path):
    extension = Path(__file__).resolve().parent / "vendor/h2orestart/H2Orestart.oxt"
    java = java_path()
    code = ("missing_office" if not office_path else "missing_bridge" if not office_python(office_path)
            else "missing_oxt" if not extension.is_file() else "missing_java" if not java else "ready")
    messages = {"missing_office": "LibreOffice를 설치해 주세요.",
                "missing_bridge": "이 LibreOffice 설치에 UNO Python이 없습니다. 공식 Windows 설치본을 사용해 주세요.",
                "missing_oxt": "H2Orestart 확장 파일이 없습니다. 전체 프로그램 폴더를 확인해 주세요.",
                "missing_java": "HWP/HWPX를 읽으려면 LibreOffice와 같은 비트수의 Java가 필요합니다.",
                "ready": "HWP/HWPX 읽기에 필요한 파일이 있습니다. 실제 문서 호환 여부는 변환 시 검사합니다."}
    return {"ready": code == "ready", "code": code, "message": messages[code],
            "oxt": str(extension) if extension.is_file() else None, "java": java}


def write_secure_profile(profile):
    """일회용 프로필에서 능동 콘텐츠를 차단하고 사이드바 초기 생성을 끈다."""
    profile = Path(profile)
    user = profile / "user"
    user.mkdir(parents=True, exist_ok=True)
    values = [("/org.openoffice.Office.Common/Security/Scripting", "MacroSecurityLevel", "3"),
              ("/org.openoffice.Office.Common/Security/Scripting", "DisableMacrosExecution", "true"),
              ("/org.openoffice.Office.Common/Security/Scripting", "DisableActiveContent", "true"),
              ("/org.openoffice.Office.Common/Security/Scripting", "BlockUntrustedRefererLinks", "true"),
              ("/org.openoffice.Office.Common/Load", "UpdateDocMode", "0")]
    body = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema">']
    body += [f'<item oor:path="{path}"><prop oor:name="{name}" oor:op="fuse"><value>{value}</value></prop></item>'
             for path, name, value in values]
    # 새 프로필에서는 이전 창 상태 대신 모듈별 초기 생성 조건을 명시한다.
    body.append('<item oor:path="/org.openoffice.Office.Views/Windows">')
    for module in ("scalc", "sdraw", "simpress", "smath", "swriter"):
        body += [f'<node oor:name="{module}/10336" oor:op="fuse">',
                 '<prop oor:name="Visible"><value>false</value></prop>',
                 '<node oor:name="UserData"><prop oor:name="Data" oor:type="xs:string" oor:op="fuse"><value></value></prop></node>',
                 '</node>']
    body.append('</item>')
    body.append('</oor:items>')
    (user / "registrymodifications.xcu").write_bytes(("\n".join(body) + "\n").encode("utf-8"))


def validate_input(source, extension):
    """확장자만 바꾼 가짜 문서·깨진 ZIP·암호화 패키지를 조기에 거부한다."""
    source = Path(source)
    with source.open("rb") as stream:
        header = stream.read(32)
    if not header:
        raise ValueError("비어 있는 문서는 변환할 수 없습니다.")
    packages = {"docx": "word/document.xml", "docm": "word/document.xml", "dotx": "word/document.xml",
                "dotm": "word/document.xml", "xlsx": "xl/workbook.xml", "xlsm": "xl/workbook.xml",
                "xltx": "xl/workbook.xml", "xltm": "xl/workbook.xml", "xlsb": "xl/workbook.bin",
                "pptx": "ppt/presentation.xml", "pptm": "ppt/presentation.xml", "potx": "ppt/presentation.xml",
                "potm": "ppt/presentation.xml", "ppsx": "ppt/presentation.xml", "ppsm": "ppt/presentation.xml"}
    zipped = set(packages) | {"odt", "ott", "ods", "ots", "odp", "otp", "sxw", "stw", "hwpx", "pages", "numbers", "key"}
    if extension in zipped:
        if header.startswith(b"\xd0\xcf\x11\xe0"):
            raise ValueError("암호화된 문서이거나 확장자와 실제 형식이 다릅니다. 암호를 해제한 복사본을 사용해 주세요.")
        try:
            with zipfile.ZipFile(source) as package:
                names = set(package.namelist())
                if any(item.flag_bits & 1 for item in package.infolist()):
                    raise ValueError("암호화된 ZIP 문서는 지원하지 않습니다.")
                if extension in packages and packages[extension] not in names:
                    raise ValueError("문서의 필수 본문이 없거나 확장자와 실제 형식이 다릅니다.")
                if extension in {"odt", "ott", "ods", "ots", "odp", "otp", "sxw", "stw"} and "content.xml" not in names:
                    raise ValueError("OpenDocument 본문이 없습니다.")
                if extension == "hwpx" and not any(name.startswith("Contents/section") and name.endswith(".xml") for name in names):
                    raise ValueError("HWPX 본문이 없습니다.")
                if extension in {"pages", "numbers", "key"} and not any(name.endswith((".iwa", "index.xml", "index.apxl", "index.xml.gz", "index.apxl.gz")) for name in names):
                    raise ValueError("지원 가능한 iWork 본문이 없습니다.")
                for item in package.infolist():
                    if item.filename.startswith("META-INF/") and item.filename.endswith("manifest.xml"):
                        if item.file_size > 8 * 1024 * 1024:
                            raise ValueError("문서 매니페스트가 비정상적으로 큽니다.")
                        if b"encryption-data" in package.read(item):
                            raise ValueError("암호화된 OpenDocument는 지원하지 않습니다.")
        except zipfile.BadZipFile as exc:
            raise ValueError("문서 패키지가 손상되었거나 실제 형식이 다릅니다.") from exc
    elif extension in {"doc", "dot", "xls", "xlt", "ppt", "pot", "pps"}:
        # 초기 Excel BIFF2/3/4는 OLE 컨테이너를 쓰지 않는다.
        old_biff = extension in {"xls", "xlt"} and header[:2] in (b"\x09\x00", b"\x09\x02", b"\x09\x04", b"\x09\x08")
        if not header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1") and not old_biff:
            raise ValueError("구형 Office 문서의 실제 파일 형식을 확인할 수 없습니다.")
    elif extension == "hwp":
        if not header.startswith((b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", b"HWP Document File")):
            raise ValueError("HWP 파일의 실제 형식을 확인할 수 없습니다.")
    elif extension == "rtf" and not header.lstrip().startswith(b"{\\rtf"):
        raise ValueError("RTF 문서의 실제 형식을 확인할 수 없습니다.")
    elif extension in {"fodt", "fods", "fodp", "abw"}:
        # XML 확장 엔터티는 로컬 파일·네트워크를 참조할 수 있으므로 사용하지 않는다.
        raw = source.read_bytes()
        if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
            raise ValueError("외부 엔터티가 있는 문서는 변환하지 않습니다.")
        try:
            ET.fromstring(raw)
        except ET.ParseError as exc:
            raise ValueError("XML 문서가 손상되었습니다.") from exc
