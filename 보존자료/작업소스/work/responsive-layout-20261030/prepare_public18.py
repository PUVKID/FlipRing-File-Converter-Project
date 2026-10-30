"""기존 공개 차수를 보존하고 새 고정 창 변경과 전체 차이를 선기록한다."""
from pathlib import Path
import difflib
import hashlib
import json
import re
import shutil

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'work/enhancement-20261030/public'
SOURCE=ROOT/'소스'
HISTORY=OUT/'history/1.8.0'
HISTORY.mkdir(parents=True,exist_ok=True)
names=sorted(p.name for p in SOURCE.iterdir() if p.is_file() and (p.suffix=='.py' or p.name in ('requirements-lock.txt','LICENSE.txt')))
inventory=[]
for name in names:
    raw=(SOURCE/name).read_bytes()
    text=raw.decode('utf-8')
    assert '\ufffd' not in text
    assert not re.search(r'(?:[CD]:[/\\]Users[/\\]|sk-[A-Za-z0-9]{20}|gh[pousr]_[A-Za-z0-9]{20})',text),name
    (HISTORY/name).write_bytes(raw)
    (OUT/'소스'/name).write_bytes(raw)
    inventory.append({'path':name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
for name in ('빌드방법.md','1.8-화면안내.md','offscreen-monitor.json'):
    shutil.copy2(SOURCE/name,OUT/'소스'/name)
(HISTORY/'파일목록.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
old=OUT/'history/1.7.0'
old_names={p.name for p in old.iterdir() if p.is_file() and p.name!='파일목록.json'}
patches=[]
rows=[]
for name in sorted(old_names|set(names)):
    a=(old/name).read_bytes() if (old/name).is_file() else None
    b=(HISTORY/name).read_bytes() if (HISTORY/name).is_file() else None
    state='동일' if a==b else '추가' if a is None else '삭제' if b is None else '수정'
    desc=lambda raw:'없음' if raw is None else f'{len(raw)} / `{hashlib.sha256(raw).hexdigest()}`'
    rows.append(f'| {name} | {state} | {desc(a)} | {desc(b)} |')
    if a!=b:
        patches.extend(difflib.unified_diff((a or b'').decode('utf-8').splitlines(keepends=True),(b or b'').decode('utf-8').splitlines(keepends=True),fromfile='1.7.0/'+name,tofile='1.8.0/'+name))
(OUT/'docs/diffs/1.8.0.patch').write_text(''.join(patches),encoding='utf-8',newline='')
lines=['# 1.8.0 · 고정 창과 세부 디자인','',
'기본 창을 1080×780에서 1160×820 논리 픽셀로 늘리고 사용자 크기 변경을 잠급니다. 작은 사용 가능 화면에는 창 맞춤과 스크롤을 제공합니다. 메뉴의 선택선·본문 경계·프리셋·작업·출력·비교 영역의 제목과 구분을 보강하고 이미지·SVG의 고배율 렌더를 조정했습니다.','',
'상태 표시의 첫 애니메이션 틱이 늦게 시작되면 완료가 지연될 수 있는 기전을 제어 시험으로 재현했습니다. 400ms 단발 타이머로 유한 종료를 보완하고 숨김·재진입·모션 줄이기 동작을 검사합니다. 이전 실제 실패와 원래 420ms 기대 검사는 보존합니다.','',
'[소스](../../history/1.8.0/) · [파일 목록](../../history/1.8.0/파일목록.json) · [직전 1.7](1.7.0.md) · [공백·주석을 포함한 전체 차이](../diffs/1.8.0.patch) · [사용 안내](../../소스/1.8-화면안내.md)','',
'## 실제 파일 비교','',
'| 파일 | 상태 | 이전 바이트 / SHA-256 | 현재 바이트 / SHA-256 |','|---|---|---|---|',*rows,'',
'## 검증과 공개 범위','',
'현재 구현·포장 준비 자료를 로컬에 선기록했습니다. 최종 검사·실행 파일·설치·독립 검토 결과는 검증 후 아래에 추가합니다. 이전 1.7의 사용자 실제 탐색기·PDF 조작 확인과 이번 Qt 오프스크린 배율 시험을 구분합니다. 변환 엔진·검사기·7-Zip 바이너리 해시가 같을 때만 기존 266개 변환 기록을 재사용합니다.','',
'실행 자산·모델·대용량 바이너리·개인 지침·메모리·원문 대화·운영 경로가 들어 있는 비공개 기록은 이 공개 사본에 넣지 않습니다. 로컬 전체 소스에는 실행 자산·법적 고지·빌드 방법을 보존합니다. 이전 공개 차수 파일은 덮어쓰지 않습니다.','']
(OUT/'docs/versions/1.8.0.md').write_text('\n'.join(lines),encoding='utf-8')
readme=OUT/'README.md'
text=readme.read_text(encoding='utf-8')
intro='''**1.8.0 · 고정 창과 세부 디자인**

- 기본 창을 1160×820 논리 픽셀로 고정하고 메뉴·작업·원본/결과의 구분을 보강했습니다.
- 파일·폴더 선택창, PDF 페이지 번호, 고배율 아이콘·미리보기와 작은 화면의 스크롤 접근을 보완했습니다.
- [1.8 실제 변경·검증 범위](docs/versions/1.8.0.md) · [화면 안내](소스/1.8-화면안내.md)

'''
if '**1.8.0 · 고정 창과 세부 디자인**' not in text:
    text=text.replace('**1.7.0 · 파일별 작업 흐름과 PDF 페이지 편집**',intro+'**1.7.0 · 파일별 작업 흐름과 PDF 페이지 편집**')
row='| 1.8.0 | 고정 창·영역 구분·배율 렌더 개선 | [폴더](history/1.8.0/) · [설명](docs/versions/1.8.0.md) | [1.7.0 대비 전체 차이](docs/diffs/1.8.0.patch) |'
if row not in text:
    marker='원래 1차·2차와 보존 파일의 대응'
    text=text.replace(marker,row+'\n\n'+marker)
    # 표 마지막 행과 새 행 사이 빈 줄을 제거한다.
    text=text.replace('|\n\n'+row,'|\n'+row)
readme.write_text(text,encoding='utf-8')
index=OUT/'docs/VERSIONS.md'
text=index.read_text(encoding='utf-8')
if '(versions/1.8.0.md)' not in text:
    text+='\n## 1.8.0 추가\n\n[고정 창·영역 구분·배율 개선의 전체 파일 비교와 검증](versions/1.8.0.md) · [직전1.7대비 원문 차이](diffs/1.8.0.patch) · [보존 소스](../history/1.8.0/)\n'
index.write_text(text,encoding='utf-8')
print(json.dumps({'version':'1.8.0','source_files':len(names),'history_preserved':'1.7.0','status':'로컬 선기록, 최종 검증과 게시 전'},ensure_ascii=False))
