"""화면 번역과 기존 변환 엔진의 오류 표현. 저장 데이터는 번역하지 않는다."""
from __future__ import annotations

import re


TEXT = {
    "app": ("플립링", "FlipRing"),
    "settings_title": ("{app} 설정", "{app} Settings"),
    "wheel_title": ("{app} · 변환 휠", "{app} · Conversion Wheel"),
    "settings": ("설정", "Settings"), "tools": ("도구", "Tools"),
    "history": ("기록", "History"), "about": ("정보", "About"),
    "pdf_tools": ("PDF·OCR", "PDF · OCR"),
    "language": ("언어 / Language", "Language / 언어"),
    "trigger_label": ("드래그 중 누를 키", "Key to hold while dragging"),
    "custom": ("사용자 지정", "Custom"),
    "custom_hint": ("지정 키 ({key})", "Custom key ({key})"),
    "drag_hint": ("파일을 끌고 {key}, 고른 형식에 놓으세요.", "Drag a file, hold {key}, then drop on a format."),
    "record": ("사용자 지정 키 기록", "Record a custom key"),
    "record_wait": ("사용할 키를 누르세요 · Esc 취소", "Press a key · Esc to cancel"),
    "recorded": ("사용자 지정 키: {key} · 다시 기록", "Custom key: {key} · Record again"),
    "auto": ("Windows 로그인 시 시작", "Start when signing in to Windows"),
    "reveal": ("완료 후 탐색기에서 결과 선택", "Select the result in Explorer when done"),
    "notifications": ("변환 결과 알림", "Show conversion notifications"),
    "original_note": ("원본을 보존하고 같은 폴더에 저장합니다.\nFn은 일부 기기에서 전달되지 않아 다른 키가 필요합니다.", "Originals are kept. Results go in the same folder.\nFn may be unavailable on some devices; use another key."),
    "pick_files": ("파일 선택", "Choose files"), "pick_folder": ("폴더 선택", "Choose a folder"),
    "pick_files_menu": ("파일 선택…", "Choose files…"), "pick_folder_menu": ("폴더 선택…", "Choose a folder…"),
    "install_command": ("설치 명령", "Install command"),
    "purpose_ffmpeg": ("오디오 · 비디오", "Audio · Video"),
    "purpose_pandoc": ("전자책 · 문서", "eBooks · Documents"),
    "purpose_soffice": ("Office 문서 · 발표 · 표", "Office documents · Slides · Sheets"),
    "tools_note": ("이미지·PDF·자막·ZIP/TAR 변환은 기본 포함됩니다.\nRAR 해제에는 UnRAR 또는 7-Zip이 필요할 수 있습니다.", "Image, PDF, subtitle and ZIP/TAR conversion is included.\nExtracting RAR may require UnRAR or 7-Zip."),
    "refresh_tools": ("도구 다시 확인", "Check tools again"),
    "available": ("사용 가능", "Available"),
    "not_installed": ("미설치 · 설치 명령을 복사해 설치할 수 있습니다.", "Not installed · Copy the command to install."),
    "recent_note": ("최근 200개 · 이 Windows 계정에 저장", "Last 200 results · Saved for this Windows account"),
    "about_text": ("{app}\n제작자 PUVKID · 무료 배포판\n\n인증·사용 횟수·체험·만료 제한이 없습니다.\n\n기본 PDF → 문서 변환은 텍스트 추출 방식입니다.\n문자 인식과 PDF 편집은 PDF·OCR 탭에서 사용합니다.\n인식 정확도와 문서 배치는 원본에 따라 다릅니다.\n탐색기 아이콘 위치는 Windows 정렬을 따릅니다.", "{app}\nMade by PUVKID · Free edition\n\nNo activation, usage, trial or expiry limits.\n\nBasic PDF to document conversion extracts text.\nUse the PDF · OCR tab for recognition and PDF editing.\nRecognition and document layout depend on the source.\nExplorer controls the placement of file icons."),
    "licenses": ("라이선스 폴더", "License folder"), "ready": ("준비됨", "Ready"),
    "tray_hint": ("파일 드래그 + {key}", "Drag a file + {key}"),
    "converting": ("{count}개 변환 중", "Converting {count} file(s)"),
    "queue": ("변환 중 · {count}개 대기", "Converting · {count} remaining"),
    "drag_key": ("드래그 키", "Drag key"), "auto_menu": ("로그인 시 시작", "Start at sign-in"),
    "reveal_menu": ("결과 파일 선택", "Select result file"), "notify_menu": ("변환 알림", "Conversion notifications"),
    "helpers": ("도우미 도구", "Helper tools"),
    "copy_install": ("{tool} 설치 명령 복사", "Copy {tool} install command"),
    "details": ("자세히…", "Details…"), "quit": ("종료", "Quit"),
    "busy_title": ("변환 진행 중", "Conversion in progress"),
    "busy_message": ("변환이 끝나면 종료해 주세요.", "Wait for conversion to finish before quitting."),
    "pick_files_title": ("변환할 파일 선택", "Choose files to convert"),
    "pick_folder_title": ("압축할 폴더 선택", "Choose a folder to archive"),
    "dialog_location": ("위치:", "Look in:"), "dialog_filename": ("파일 이름:", "File name:"),
    "dialog_filter": ("파일 형식:", "Files of type:"), "dialog_open": ("열기", "Open"),
    "dialog_choose": ("선택", "Choose"),
    "unsupported_title": ("변환할 수 없음", "Cannot convert"),
    "unsupported_message": ("선택한 파일 전체에 공통으로 적용할 수 있는 형식이 없습니다.", "No output format is available for all selected files."),
    "helper_title": ("도우미 도구 필요", "Helper tool required"),
    "helper_message": ("{tool}를 설치해 주세요.", "Install {tool} to use this format."),
    "needs_tool": ("{tool} 필요", "Needs {tool}"),
    "file_count": ("{count}개 파일", "{count} files"),
    "drop_convert": ("놓으면 변환", "Drop to convert"), "cancel": ("취소", "Cancel"),
    "drag_inside": ("파일을 원 안으로 끌어오세요", "Drag a file into the wheel"),
    "save_history_title": ("기록 저장 실패", "Could not save history"),
    "history_error": ("기존 기록을 읽을 수 없어 원본 기록 파일을 보존합니다.", "History could not be read. The original history file is preserved."),
    "failed_title": ("변환 실패", "Conversion failed"), "done_title": ("변환 완료", "Conversion complete"),
    "failed_status": ("변환 실패 · {error}", "Failed · {error}"),
    "done_status": ("완료 · {name}", "Done · {name}"),
    "history_failed": ("실패: {error}", "Failed: {error}"),
    "history_no_result_title": ("결과 파일 없음", "No result file"),
    "history_no_result": ("실패한 변환 기록에는 선택할 결과 파일이 없습니다.", "Failed conversions do not have a result file to select."),
    "history_missing_title": ("결과 파일을 찾을 수 없음", "Result file not found"),
    "history_missing_result": ("결과 파일이 없거나 폴더입니다. 이동 또는 삭제 여부를 확인해 주세요.", "The result is missing or is a folder. It may have been moved or deleted."),
    "history_explorer_title": ("탐색기 열기 실패", "Could not open Explorer"),
    "history_explorer_error": ("탐색기에서 결과를 선택하지 못했습니다: {detail}", "Could not select the result in Explorer: {detail}"),
    "autostart_failed": ("자동 시작 설정 실패", "Could not change startup setting"),
    "already_running": ("플립링이 이미 실행 중입니다. 트레이 아이콘을 확인해 주세요.", "FlipRing is already running. Check the system tray icon."),
    "running_title": ("플립링 실행 중", "FlipRing is running"),
    "running_message": ("파일을 끌며 Shift를 누르세요. 설정은 트레이 아이콘에 있습니다.", "Hold Shift while dragging a file. Settings are in the system tray."),
    "external_error": ("외부 도구 또는 시스템 오류: {detail}", "External tool or system error: {detail}"),
}


def tr(language, message_id, **values):
    return TEXT[message_id][1 if language == "en" else 0].format(**values)


ERROR_TEXT = {
    "변환 도구를 찾을 수 없습니다. 설정의 도우미 도구를 확인해 주세요.": "Conversion tool not found. Check Helper tools in Settings.",
    "변환 제한 시간 30분을 초과했습니다.": "Conversion exceeded the 30-minute time limit.",
    "텍스트 인코딩을 확인해 주세요.": "Check the text encoding.",
    "페이지가 없는 PDF입니다.": "The PDF has no pages.",
    "지원하지 않는 문서 출력입니다.": "This document output format is not supported.",
    "자막 시간 정보를 찾지 못했습니다.": "Subtitle timing information could not be found.",
    "압축 파일에 안전하지 않은 경로가 있습니다.": "The archive contains an unsafe path.",
    "압축 해제 경로가 작업 폴더를 벗어납니다.": "An extraction path is outside the working folder.",
    "심볼릭 링크 압축은 지원하지 않습니다.": "Archives containing symbolic links are not supported.",
    "RAR 해제에 UnRAR 또는 7-Zip 도구가 필요합니다.": "Extracting RAR requires UnRAR or 7-Zip.",
    "링크·특수 파일 압축은 지원하지 않습니다.": "Archives containing links or special files are not supported.",
    "링크·접합점이 포함된 폴더는 압축하지 않습니다.": "Folders containing links or junctions cannot be archived.",
    "SVG를 읽을 수 없습니다.": "The SVG could not be read.",
    "지원하지 않는 변환입니다.": "This conversion is not supported.",
    "이 파일에 사용할 수 없는 출력 형식입니다.": "This output format is unavailable for this file.",
    "변환기가 유효한 출력 파일을 만들지 못했습니다.": "The converter did not produce a valid output file.",
    "새 파일 이름을 만들지 못했습니다.": "A new output filename could not be created.",
}
ERROR_PATTERNS = [
    (r"지원하지 않는 파일입니다: (.*)", "Unsupported file: {0}"),
    (r"LibreOffice에서 (.+) 결과를 만들지 못했습니다\.", "LibreOffice did not produce a {0} result."),
    (r"(.+) 도구를 설치해 주세요\. 설정에서 설치 명령을 복사할 수 있습니다\.", "Install {0}. You can copy the install command in Settings."),
    (r"(.+) 변환 실패 \(([-\d]+)\)([\s\S]*)", "{0} conversion failed ({1}){2}"),
]


# Qt 파일 선택창에 필요한 공통 문구만 직접 작성한다. 외부 번역 카탈로그를 복사하지 않는다.
QT_KOREAN = {
    "Open": "열기", "Save": "저장", "Cancel": "취소", "Close": "닫기",
    "OK": "확인", "Yes": "예", "No": "아니요", "Choose": "선택",
    "Look in:": "위치:", "File name:": "파일 이름:", "Files of type:": "파일 형식:",
    "Name": "이름", "Size": "크기", "Type": "종류", "Kind": "종류",
    "Date Modified": "수정한 날짜", "Date modified": "수정한 날짜",
    "Back": "뒤로", "Forward": "앞으로", "Parent Directory": "상위 폴더",
    "Go back": "뒤로 이동", "Go forward": "앞으로 이동", "Go to the parent directory": "상위 폴더로 이동",
    "List View": "목록 보기", "Detail View": "자세히 보기", "Create New Folder": "새 폴더 만들기",
    "Show hidden files": "숨김 파일 표시", "Show Hidden Files": "숨김 파일 표시",
    "New Folder": "새 폴더", "Folder": "폴더", "Directory": "폴더", "My Computer": "내 컴퓨터",
    "Computer": "컴퓨터", "All Files (*)": "모든 파일 (*)", "All Files": "모든 파일",
    "Rename": "이름 바꾸기", "Delete": "삭제", "Select All": "모두 선택",
    "Cut": "잘라내기", "Copy": "복사", "Paste": "붙여넣기", "Undo": "실행 취소",
    "Redo": "다시 실행", "Sort by Name": "이름으로 정렬", "Sort by Size": "크기로 정렬",
    "Sort by Type": "종류로 정렬", "Sort by Date": "날짜로 정렬", "Recent Places": "최근 위치",
    "Show ": "표시 ", "File": "파일", "File Folder": "파일 폴더", "Shortcut": "바로 가기",
    "%1 File": "%1 파일", "%1 bytes": "%1바이트", "File not found": "파일을 찾을 수 없습니다",
    "Directory not found": "폴더를 찾을 수 없습니다", "Open %1": "%1 열기",
    "%1\nFile not found.\nPlease verify the correct file name was given.": "%1\n파일을 찾을 수 없습니다.\n파일 이름을 확인해 주세요.",
    "File %1 already exists.\nDo you want to replace it?": "%1 파일이 이미 있습니다.\n바꾸시겠습니까?",
}


def error_text(language, message):
    """기록된 표준 오류를 현재 언어로 표시하고 외부 진단은 원문으로 구분한다."""
    if not message:
        return message
    # 저장 스키마와 원문은 유지하며 PDF 패널의 단일 사전에서 양방향 표시만 바꾼다.
    from pdf_panel import ERRORS as PDF_ERRORS
    for pair in PDF_ERRORS.values():
        if message in pair:
            return pair[language == "en"]
    if language != "en":
        return message
    if message in ERROR_TEXT:
        return ERROR_TEXT[message]
    for pattern, translated in ERROR_PATTERNS:
        match = re.fullmatch(pattern, message)
        if match:
            return translated.format(*match.groups())
    return tr(language, "external_error", detail=message)
