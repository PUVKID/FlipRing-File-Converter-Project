"""LibreOffice 전용 Python에서 실행하는 격리 문서 변환기.

앱의 Python·Qt DLL과 UNO 런타임을 섞지 않고 고유 로컬 파이프로만 연결한다.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from document_formats import EXPORT_FILTERS, prepare_import_source
from document_xlsb import ensure_loaded_sheets


def _property(name, value):
    import uno
    prop = uno.createUnoStruct("com.sun.star.beans.PropertyValue")
    prop.Name, prop.Value = name, value
    return prop


def load_options(handler, source_extension):
    """문서 자체 정책보다 강한 보안과 메인 스레드 실행 조건을 고정한다."""
    options = {"Hidden": True, "ReadOnly": True, "Silent": True, "AsTemplate": False,
               "MacroExecutionMode": 0, "UpdateDocMode": 0, "InteractionHandler": handler,
               "OnMainThread": True}
    if source_extension in ("hwp", "hwpx"):
        options["FilterName"] = "Hwp2002_File"
    if source_extension in ("csv", "tsv"):
        options["FilterName"] = "Text - txt - csv (StarCalc)"
        options["FilterOptions"] = ("9" if source_extension == "tsv" else "44") + ",34,76,1,,0,false,true,true,false,false,0"
    elif source_extension == "dif":
        # 읽기 전 정규화한 UTF-8을 명시해 시스템 설정과 확인창에 의존하지 않는다.
        options["FilterName"] = "DIF"
        options["FilterOptions"] = "76"
    return options


def export_options(handler, filter_name, target=None):
    """정규화와 최종 저장의 덮어쓰기·실행 조건을 함께 적용한다."""
    options = {"FilterName": filter_name, "Overwrite": False, "InteractionHandler": handler,
               "OnMainThread": True}
    if target in ("csv", "tsv"):
        options["FilterOptions"] = ("9" if target == "tsv" else "44") + ",34,76,1,,0,false,true,true,false,false,0"
    elif target == "txt":
        options["FilterOptions"] = "UTF8,LF"
    if target == "pdf":
        options["FilterData"] = (_property("ExportBookmarks", True), _property("ExportFormFields", False))
    return options


def abort_interaction(interaction, abort_type):
    """승인·재시도 대신 UNO의 명시적인 중단 continuation만 선택한다."""
    for continuation in interaction.getContinuations():
        abort = continuation.queryInterface(abort_type)
        if abort is not None:
            abort.select()
            return


def _stop(process):
    """이번 변환이 직접 시작한 프로세스와 자식만 회수한다."""
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
        else:
            process.terminate()
        if process.poll() is None:
            process.kill()
    process.wait(timeout=15)


def _plain_slide_text(document):
    result = []
    def visit(shape):
        if hasattr(shape, "getString"):
            value = shape.getString()
            if value:
                result.append(value)
        if hasattr(shape, "getCount") and hasattr(shape, "getByIndex"):
            for index in range(shape.getCount()):
                visit(shape.getByIndex(index))
    pages = document.getDrawPages()
    for index in range(pages.getCount()):
        result.append(f"--- {index + 1} ---")
        page = pages.getByIndex(index)
        for item in range(page.getCount()):
            visit(page.getByIndex(item))
    return "\n".join(result) + "\n"


def _shutdown_office(document, desktop, process, primary_error):
    """본변환의 첫 오류와 종료 실패를 보존하고 죽은 UNO를 재호출하지 않는다."""
    failures = []
    if primary_error is None:
        try:
            if document is not None:
                document.close(True)
            if desktop is not None and not desktop.terminate():
                raise RuntimeError("격리한 LibreOffice가 종료 요청을 거부했습니다.")
        except BaseException as error:
            failures.append(error)
    try:
        if primary_error is not None or failures:
            _stop(process)
        else:
            try:
                code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # 강제 회수에 성공해도 정상 종료 제한을 넘긴 변환은 실패다.
                failures.append(RuntimeError("LibreOffice가 정상 종료 제한 5초를 넘겼습니다."))
                _stop(process)
            else:
                if code != 0:
                    failures.append(RuntimeError(f"LibreOffice 직접 프로세스가 비정상 종료했습니다: {code}"))
    except BaseException as error:
        failures.append(error)
    if primary_error is not None:
        if failures:
            detail = " / ".join(type(error).__name__ + ": " + str(error) for error in failures)
            raise primary_error from RuntimeError("문서 정리 실패: " + detail)
        raise primary_error
    if failures:
        if len(failures) > 1:
            detail = " / ".join(type(error).__name__ + ": " + str(error) for error in failures[1:])
            raise failures[0] from RuntimeError("추가 문서 정리 실패: " + detail)
        raise failures[0]


def convert(request):
    import uno
    import unohelper
    from com.sun.star.task import XInteractionHandler

    class AbortInteractions(unohelper.Base, XInteractionHandler):
        """암호·복구·외부 연결 확인창을 승인하지 않는다."""
        def __init__(self):
            self.seen = False
            self.password = False

        def handle(self, interaction):
            self.seen = True
            value = interaction.getRequest()
            self.password = self.password or "password" in type(value).__name__.lower()
            abort_interaction(interaction, uno.getTypeByName("com.sun.star.task.XInteractionAbort"))

    source, output, profile = (Path(request[key]).resolve() for key in ("source", "output", "profile"))
    if output.exists():
        raise ValueError("이미 있는 문서 결과는 덮어쓰지 않습니다.")
    source = prepare_import_source(source, request["extension"], profile)
    family, target = request["family"], request["target"]
    if target != "txt" or family != "프레젠테이션":
        filter_name = EXPORT_FILTERS.get(family, {}).get(target)
        if not filter_name:
            raise ValueError("허용되지 않은 문서 출력입니다.")
    else:
        filter_name = None
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    env = dict(os.environ)
    env["UNO_PATH"] = str(Path(request["office"]).parent)
    if request.get("java"):
        java_home = Path(request["java"]).resolve().parent.parent
        env["JAVA_HOME"] = str(java_home)
        env["UNO_JAVA_JFW_JREHOME"] = java_home.as_uri()
        # 확장의 원문 포함 로그도 이 변환의 일회용 프로필 안에 머문다.
        env["JAVA_TOOL_OPTIONS"] = '-Duser.home="' + str(profile) + '"'
    if request.get("oxt"):
        unopkg = Path(request["office"]).parent / ("unopkg.com" if os.name == "nt" else "unopkg")
        command = [str(unopkg), f"-env:UserInstallation={profile.as_uri()}",
                   "add", "--force", "--suppress-license", request["oxt"]]
        install = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   stdin=subprocess.DEVNULL, creationflags=flags, env=env)
        try:
            stdout, stderr = install.communicate(timeout=45)
        except subprocess.TimeoutExpired:
            _stop(install)
            raise RuntimeError("격리한 HWP 확장 준비 시간이 초과되었습니다.")
        if install.returncode:
            raise RuntimeError("격리한 HWP 확장을 준비하지 못했습니다. Java 설치와 LibreOffice 비트수를 확인해 주세요.\n" +
                               (stderr or stdout).decode("utf-8", "replace")[-600:])

    pipe = "flipring_" + uuid.uuid4().hex
    listener = f"pipe,name={pipe};urp;StarOffice.ComponentContext"
    process = subprocess.Popen([request["office"], f"-env:UserInstallation={profile.as_uri()}",
                                "--headless", "--nologo", "--nodefault", "--norestore", "--nofirststartwizard",
                                "--accept=" + listener], stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=sys.stderr,
                               creationflags=flags, env=env)
    document = desktop = None
    primary_error = None
    try:
        context = uno.getComponentContext()
        resolver = context.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", context)
        # 새 격리 프로필의 연결이 25초에 근접한 관측에 따라 시작 대기를 60초로 제한한다.
        deadline = time.monotonic() + 60
        while True:
            try:
                remote = resolver.resolve("uno:" + listener)
                break
            except Exception:
                if process.poll() is not None:
                    raise RuntimeError("LibreOffice가 문서 연결 전에 종료되었습니다.")
                if time.monotonic() >= deadline:
                    raise RuntimeError("LibreOffice 문서 연결 시간이 초과되었습니다.")
                time.sleep(0.1)
        desktop = remote.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", remote)
        handler = AbortInteractions()
        properties = tuple(_property(name, value) for name, value in load_options(handler, request["extension"]).items())
        document = desktop.loadComponentFromURL(source.as_uri(), "_blank", 0, properties)
        if document is None:
            raise ValueError("암호·손상·복구 요청 또는 지원하지 않는 실제 문서 형식으로 열기를 거부했습니다.")
        services = {"문서": "com.sun.star.text.TextDocument", "프레젠테이션": "com.sun.star.presentation.PresentationDocument",
                    "스프레드시트": "com.sun.star.sheet.SpreadsheetDocument"}
        if not document.supportsService(services[family]):
            raise ValueError("확장자와 실제 문서 종류가 일치하지 않습니다.")
        if request["extension"] == "xlsb":
            ensure_loaded_sheets(document, request["xlsb_sheets"])
        if family == "문서" and target == "doc":
            # OOXML 표의 직접 DOC 내보내기 손실을 실제 대조했으므로 ODT로 정규화한다.
            normalized = output.parent / "legacy-normalization.odt"
            document.storeToURL(normalized.as_uri(), tuple(_property(name, value) for name, value in
                                                         export_options(handler, "writer8").items()))
            document.close(True)
            document = None
            properties = tuple(_property(name, value) for name, value in load_options(handler, "odt").items())
            document = desktop.loadComponentFromURL(normalized.as_uri(), "_blank", 0, properties)
            if document is None or not document.supportsService(services[family]):
                raise RuntimeError("구형 Word 문서를 위한 중간 형식을 확인하지 못했습니다.")
        if filter_name is None:
            output.write_bytes(_plain_slide_text(document).encode("utf-8"))
        else:
            if family == "스프레드시트" and target in ("csv", "tsv"):
                document.getCurrentController().setActiveSheet(document.getSheets().getByIndex(0))
            export = export_options(handler, filter_name, target)
            document.storeToURL(output.as_uri(), tuple(_property(name, value) for name, value in export.items()))
        if not output.is_file() or (output.stat().st_size == 0 and target != "txt"):
            raise RuntimeError("문서 변환기가 결과를 만들지 못했습니다.")
        return {"ok": True, "family": family, "target": target, "bytes": output.stat().st_size,
                "macro_execution_mode": 0, "update_doc_mode": 0, "interactions_aborted": handler.seen}
    except BaseException as error:
        primary_error = error
        raise
    finally:
        _shutdown_office(document, desktop, process, primary_error)


def main():
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    try:
        result = convert(request)
    except Exception as error:
        result = {"ok": False, "error": str(error)}
        if error.__cause__ is not None:
            result["cause"] = str(error.__cause__)
        print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
