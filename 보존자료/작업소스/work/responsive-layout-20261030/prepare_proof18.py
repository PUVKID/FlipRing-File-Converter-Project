"""현재 납품 파일과 실제 설치·배율·기존 변환 근거를 연결한다."""
from pathlib import Path
from datetime import datetime
import hashlib
import json

ROOT=Path(__file__).resolve().parents[2]
WORK=Path(__file__).resolve().parent
def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()
install=read(WORK/'actual-install.json')
assert install['installer_exit_code']==0 and install['actual_launch_passed']
files=[]
for line in (ROOT/'SHA256SUMS.txt').read_text(encoding='utf-8').split('\n'):
    if not line:
        continue
    digest,name=line.split('  ',1)
    path=(ROOT/name).resolve()
    assert path.is_relative_to(ROOT) and sha(path)==digest,name
    files.append({'path':name,'size':path.stat().st_size,'sha256':digest})
renders={label:f'work/responsive-layout-20261030/render-{label}-repair24/고정창-검증.json' for label in ['100','125','150','200','small']}
matrix='work/enhancement-20261030/matrix-test/run-bf49e1f2-7b56-471b-918f-3bc495f6e860/report.json'
context='work/enhancement-20261030/matrix-test/run-bf49e1f2-7b56-471b-918f-3bc495f6e860/run-context.json'
compiled='evidence/1.8-실행파일소스대조.json'
installed='evidence/1.8-설치파일전체대조.json'
required={compiled,installed,matrix,context,*renders.values(),
          'evidence/1.7-사용자실제조작확인.json','.codex/gui_test_manifest.json',
          '.codex/release_artifacts18_check.py','SHA256SUMS.txt',
          'work/responsive-layout-20261030/최종소스동결-수리24.json',
          'work/responsive-layout-20261030/actual-install.json',
          'work/responsive-layout-20261030/부모-회귀163-결과.json',
          'evidence/fixed-design-visual-review-20261030/선택창보완24_시각검토.md'}
bindings=[{'path':name,'sha256':sha(ROOT/name)} for name in sorted(required)]
record={'time_kst':datetime.now().astimezone().isoformat(),'release':'1.8.0',
        'installer_exit_code':install['installer_exit_code'],'actual_launch_passed':install['actual_launch_passed'],
        'files':files,'bindings':bindings,'compiled_report':compiled,'installed_report':installed,
        'matrix_report':matrix,'matrix_context':context,'render_reports':renders,'manual_baseline_release':'1.7.0',
        'scope':'현재1.8실제설치·응답창·출하파일·소스와Qt렌더대조. 탐색기Shift/PDF사용자실제조작은1.7기록을구분해참조. 기존266변환기록은시작/종료/현재5해시동일성검증후재사용.',
        'overall_completed':False,'remaining':['최종독립검증과부모Stop','GitHub1.8게시·원격대조']}
target=ROOT/'evidence/1.8-배포검증.json'
assert not target.exists()
target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'files':len(files),'bindings':len(bindings),'release':'1.8.0'},ensure_ascii=False))
