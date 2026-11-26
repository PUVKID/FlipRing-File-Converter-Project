"""오류 원문을 보존하면서 짧은 원인과 허용된 다음 동작을 정한다."""
from dataclasses import dataclass
import re
import engine

@dataclass(frozen=True)
class Recovery:
    title:str
    body:str
    action:str
    label:str
    tool:str=''

def explain_failure(error,language='ko'):
    raw=str(error);text=raw.casefold();en=language=='en'
    def row(ko_title,en_title,ko_body,en_body,action,ko_label,en_label,tool=''):
        return Recovery(en_title if en else ko_title,en_body if en else ko_body,action,en_label if en else ko_label,tool)
    if any(x in text for x in ('python312.dll','dll conflicts','module use of','runtime missing','동봉','언어 모델')):
        return row('실행 구성 확인이 필요해요','Check the app components','앱과 도우미 파일이 맞지 않거나 일부가 없습니다. 도구 화면에서 구성을 확인하세요.','The app or bundled helper components are missing or incompatible. Check the tools screen.','helpers','도구 확인','Check tools')
    if any(x in text for x in ('file not found:','no such file:','입력이 없','파일이 이동','file changed','파일이 변경')):
        return row('파일을 다시 선택해 주세요','Select the file again','파일이 이동됐거나 더 이상 읽을 수 없습니다. 현재 위치에서 다시 선택하세요.','The file moved or cannot be read. Select it from its current location.','select','파일 다시 선택','Choose file')
    for key,(name,_,_) in engine.TOOLS.items():
            token='(?:'+re.escape(name)+'|'+re.escape(key)+')'
            required=re.search(r'(?<![\w./\\-])'+token+r'\s+(?:도구(?:를)?\s*)?(?:설치|is required|required|not found|missing)',raw,re.I)
            required=required or re.search(r'\b(?:install|missing|required)\s+'+token+r'(?![\w./\\-])',raw,re.I)
            if required:
                return row(f'{name}가 필요해요',f'{name} is required','버튼을 눌러 필요한 도구를 설치한 뒤 다시 시도하세요.','Install the required tool, then retry the conversion.','install',f'{name} 설치',f'Install {name}',key)
    if any(x in text for x in ('암호','encrypted','password')):
        return row('암호를 먼저 해제해 주세요','Unlock the file first','원본 앱에서 암호를 해제한 사본을 저장한 뒤 선택해 주세요.','Save an unlocked copy in the original app, then select that copy.','unlock','파일 다시 선택','Select unlocked copy')
    if any(x in text for x in ('여유 공간','disk space','no space','공간이 부족','쓰기','permission denied','access is denied','권한')):
        return row('저장 위치를 확인해 주세요','Check the output location','저장 폴더의 여유 공간과 쓰기 권한을 확인하거나, 쓸 수 있는 폴더의 사본을 선택하세요.','Check free space and write access, or choose a copy in a writable folder.','location','저장 폴더 확인','Show folder')
    if any(x in text for x in ('이동','입력이 없','not exist','no such file','찾을 수 없','file changed','파일이 변경')):
        return row('파일을 다시 선택해 주세요','Select the file again','파일이 이동됐거나 더 이상 읽을 수 없습니다. 현재 위치에서 다시 선택하세요.','The file moved or cannot be read. Select it from its current location.','select','파일 다시 선택','Choose file')
    if any(x in text for x in ('시간','timeout','timed out','time limit')):
        return row('처리가 오래 걸렸어요','The operation timed out','작은 파일이나 낮은 해상도로 다시 시도하세요. 원본은 그대로 남아 있습니다.','Retry with a smaller file or lower resolution. The original is unchanged.','retry','다시 시도','Retry')
    if any(x in text for x in ('지원','unsupported','손상','읽을 수','corrupt','invalid','형식')):
        return row('파일이나 형식을 확인해 주세요','Check the file and format','원본 앱에서 파일이 열리는지 확인하고 다른 출력 형식을 선택해 보세요.','Check that the source opens in its original app, then try another output format.','format','출력 형식 선택','Choose format')
    return row('변환을 마치지 못했어요','Conversion did not finish','원본은 그대로입니다. 파일과 출력 형식을 확인한 뒤 다시 시도하세요. 상세 내용은 펼쳐 볼 수 있습니다.','The original is unchanged. Check the file and output format. Expand details for the original error.','retry','다시 시도','Retry')
