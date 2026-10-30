"""납품 원본을 변경하지 않고 공개용 설명과 코드 사본을 준비한다."""
from pathlib import Path
import json
import shutil

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'work/enhancement-20261030/public'
table = (OUT / 'history-table.md').read_text(encoding='utf-8')
readme = (OUT / 'README.md').read_text(encoding='utf-8')
start = readme.index('### 🧭 차수 바로가기')
end = readme.index('<a name="preview"></a>', start)
readme = readme[:start] + '### 확인된 전체 버전과 보존 기준본\n\n' + table + '\n원래 1차·2차와 보존 파일의 대응은 확인되지 않았습니다. 1.3·1.5의 완전한 최종 소스도 확인되지 않아 번호를 만들어 채우지 않습니다. [보존 범위와 비교 한계](docs/VERSIONS.md)를 함께 확인해 주세요.\n\n' + readme[end:]
readme = readme.replace('| RAR 처리 | 사용 가능한 UnRAR·7-Zip 등 RAR 백엔드 |', '| RAR 처리 | 로컬 배포물에 동봉한 7-Zip 26.05 해제 도구 |')
readme = readme.replace('이 공개 사본에는 해당 실행 자산과 OCR 바이너리가 포함되어 있지 않으므로', '이 공개 사본에는 해당 실행 자산과 OCR·7-Zip 바이너리가 포함되어 있지 않으므로')
(OUT / 'README.md').write_text(readme, encoding='utf-8', newline='\n')

for p in (ROOT / '소스').iterdir():
    if p.is_file() and (p.suffix == '.py' or p.name in ('requirements-lock.txt', 'LICENSE.txt', '1.7-새기능안내.md', '빌드방법.md', '사용안내.txt')):
        target = OUT / '소스' / p.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, target)
for p in (ROOT / '소스/licenses/7Zip').glob('*'):
    if p.is_file():
        target = OUT / '소스/licenses/7Zip' / p.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, target)
shutil.copyfile(ROOT / '시작하기.txt', OUT / '시작하기.txt')

details = {
    '1.2.0': '파일 분류·Shift 원형 메뉴·트레이와 한영 설정, PDF 패널·처리 엔진·검사를 포함합니다. 보존된 설치 설정의 제품명은 DragWheel Mono입니다. 이후 플립링의 모든 기능을 이 소스에 소급하지 않습니다.',
    '1.4.0': '1.2와 실제 비교하면 app.py의 화면·입력 구성과 GUI 검사가 바뀌며 engine·i18n·PDF 처리·패널과 빌드·포장도 파일별 표로 구분됩니다. SUIT 글꼴과 버튼·탭·원형 메뉴의 유한 전환이 포함된 기준본입니다. 이 자료는 스튜디오 재설계 전 보존본으로 이후 결과의 증거가 아닙니다.',
    '내부모션-작업전': 'studio_ui.py가 보존된 Python 파일 목록에 추가된 상태입니다. app.py와 PDF 패널, GUI 검사, 빌드·포장 등의 실제 변화는 아래 원문 차이로 확인합니다. 완전한 1.5 배포 소스로 표기하지 않습니다.',
    '1.6.0': 'studio_ui.py·ui_motion.py와 확장된 app·PDF 패널이 포함됩니다. 파일·폴더 선택창, 내부 메뉴·메시지·입력 상태의 공통 UI와 유한 애니메이션을 연결한 보존 버전입니다. 검증 코드의 증가는 실행 결과 자체가 아니며, 1.4 이후 모든 중간 단계가 남아 있는 것은 아닙니다.',
    '1.7.0': '1.6 대비 app.py에 파일별 큐, flipring_workflow.py에 프리셋·사전 점검, preview_panel.py에 실제 이미지 비교, pdf_pages.py에 페이지 편집 모델, pdf_lock.py에 공용 PDFium 잠금을 추가했습니다. app.py는 전용 설정·큐·프리셋·미리보기와 모션 감소를 연결하며 pdf_panel.py는 썸네일 순서·선택·회전·삭제·추출·확대·저장을 제공합니다. engine.py는 짧은 독립 LibreOffice 프로필과 동봉 7-Zip RAR 처리·취소 회수를 포함합니다. build.py는 1.7.0과 별도 출력 경로를 사용하고 package.py는 새 코드·자산·7-Zip 고지와 상응 소스의 크기·해시를 검증합니다. test_workbench.py·test_pdf_workspace.py·test_conversion_matrix.py가 추가되며 기존 PDF 검사 원문은 변경하지 않았습니다. 화면·설정·실패 경로·검사의 세부 파일 차이와 공백·주석은 아래 전체 패치에 포함됩니다.',
}
for key, text in details.items():
    p = OUT / 'docs/versions' / (key + '.md')
    content = p.read_text(encoding='utf-8')
    marker = '## 코드·화면·설정·검사의 확인 범위\n\n'
    if marker not in content:
        content = content.replace('\n\n실제 보존 파일', '\n\n' + marker + text + '\n\n실제 보존 파일', 1)
        p.write_text(content, encoding='utf-8', newline='\n')

note = '\n## 2026-10-30 · 보존 버전의 가시성과 비교 범위 정정\n\n기존 기본 한 행의 버전 표만으로 과거 차수 전체가 설명됐다고 볼 수 없었습니다. 실제 남은 1.2·1.4·1.6·1.7과 부분 기준본을 구분하고, 완전한 직전 자료가 없는 경우 그 한계를 명시했습니다. 공개 가능한 원문 파일의 바이트·SHA-256과 주석·공백을 포함한 전체 패치를 연결했습니다. 이 보완은 과거의 설명 누락을 없었던 일로 바꾸지 않습니다.\n'
changelog = OUT / 'CHANGELOG.md'
text = changelog.read_text(encoding='utf-8')
if note not in text:
    changelog.write_text(text + note, encoding='utf-8', newline='\n')
print(json.dumps({'public_files': sum(1 for p in OUT.rglob('*') if p.is_file()), 'history_entries': 10}, ensure_ascii=False))
