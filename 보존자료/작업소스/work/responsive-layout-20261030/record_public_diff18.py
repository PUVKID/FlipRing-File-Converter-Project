"""공개 파일의 실제 비교와 바이너리 해시를 로컬 Markdown에 선기록한다."""
from pathlib import Path
import difflib
import hashlib
import json
import subprocess

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'work/enhancement-20261030/public'
BASE=ROOT/'work/enhancement-20261030/remote-baseline'
NOTE='docs/changes/2026-10-30_1.8_고정창.md'
PATCH='docs/changes/2026-10-30_1.8_공개전체.patch'
excluded={NOTE,PATCH}
GIT=r'C:\Users\PUVKID\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe'
BASE_COMMIT='de8d71beef115c6cf88a123ac29304628dbe1c8f'
base_names=set(subprocess.run([GIT,'-C',str(BASE),'ls-tree','-r','--name-only','-z',BASE_COMMIT],capture_output=True,check=True).stdout.decode('utf-8').rstrip('\0').split('\0'))
rows=[]
patch=[]
items=[]
def sha(raw):
    return hashlib.sha256(raw).hexdigest()
for path in sorted(OUT.rglob('*')):
    if not path.is_file():
        continue
    name=path.relative_to(OUT).as_posix()
    if name in excluded:
        continue
    raw=path.read_bytes()
    old=subprocess.run([GIT,'-C',str(BASE),'show',BASE_COMMIT+':'+name],capture_output=True,check=True).stdout if name in base_names else None
    if raw==old:
        continue
    status='추가' if old is None else '수정'
    item={'path':name,'status':status,'before_bytes':None if old is None else len(old),
          'before_sha256':None if old is None else sha(old),'after_bytes':len(raw),'after_sha256':sha(raw)}
    items.append(item)
    rows.append(f"| {name} | {status} | {item['before_bytes']} / {item['before_sha256']} | {len(raw)} / {sha(raw)} |")
    try:
        a=(old or b'').decode('utf-8')
        b=raw.decode('utf-8')
    except UnicodeDecodeError:
        patch.append(f'바이너리 {name}: {item["before_bytes"]}/{item["before_sha256"]} → {len(raw)}/{sha(raw)}\n')
    else:
        patch.extend(difflib.unified_diff(a.splitlines(keepends=True),b.splitlines(keepends=True),fromfile='de8d71b/'+name,tofile='1.8/'+name))
(OUT/PATCH).parent.mkdir(parents=True,exist_ok=True)
(OUT/PATCH).write_text(''.join(patch),encoding='utf-8',newline='')
lines=['# 1.8 고정 창·세부 디자인 변경 기록','',
'비교 기준 커밋: `de8d71beef115c6cf88a123ac29304628dbe1c8f`. 기존 공개 차수를 보존하고 새 1.8 소스와 실제 직전 차이를 추가합니다.','',
'[1.8 기능·화면·검사와 한계](../versions/1.8.0.md) · [전체 공개 파일 원문 차이](2026-10-30_1.8_공개전체.patch) · [1.7→1.8 소스 원문 차이](../diffs/1.8.0.patch)','',
'실제 추가·수정 파일은 아래와 같습니다. 삭제 파일은 없습니다. 공백·주석을 포함해 비교했으며 바이너리는 크기와 해시만 기록합니다. 이 변경 기록과 전체 비교 패치 두 파일은 비교 자료 자체로 새로 생성했습니다. 자기 본문의 자기 해시를 넣는 순환 비교에서는 제외하고 Git 커밋의 전체 차이에 포함합니다.','',
'| 공개 파일 | 상태 | 이전 바이트 / SHA-256 | 현재 바이트 / SHA-256 |','|---|---|---|---|',*rows,'',
'## 검증·공개 범위','',
'제품 GUI85·PDF/OCR28·일반작업20·PDF편집30 총163과 Qt 가상화면35검사, EXE 주요12모듈의 코드 대조, 실제 설치625파일 대조 및 배포1017파일 해시 확인을 구분해 보존합니다. 모션400ms 기한의 이벤트 전달은 OS·이벤트 루프 부하에서 늦어질 수 있으며 이전420ms Running 실패도 보존합니다.','',
'변환 엔진과 변환표 검사기·7-Zip 두 실행부·RAR 시험 자료의 시작/종료/현재 해시가 일치하는 기존266조합 결과를 참조합니다. 새 UI에서266전체를 다시 실행했다고 주장하지 않습니다. 실제 Shift·중앙 취소·PDF 페이지 이동은1.7사용자 확인이며1.8의 물리 입력 재시험과 구분합니다.','',
'개인정보·개인 지침·메모리·대화·운영 파일 경로가 있는 비공개 원문 및 대용량 실행 자산·모델·설치 바이너리는 공개 저장소에서 제외합니다. 로컬 고객 폴더에는 전체 소스·자산·법적 고지와 해당 상응 소스·실행·설치 파일·빌드 방법을 보존합니다. 최종 독립 검토와 푸시·원격 대조는 별도 영수증에 기록합니다.','']
(OUT/NOTE).write_text('\n'.join(lines),encoding='utf-8')
(Path(__file__).parent/'공개18-실제변경목록.json').write_text(json.dumps(items,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'changed_files':len(items),'new_comparison_documents':2,'deleted_files':0},ensure_ascii=False))
