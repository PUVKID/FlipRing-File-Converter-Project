"""보존된 공개 가능 소스만 복제하고 공백을 포함한 전체 차이를 기록한다."""
from pathlib import Path
import ast
import difflib
import hashlib
import json
import re
import shutil

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'work/enhancement-20261030/public'
STAGES = [
    ('1.2.0', 'evidence/이전Mono보존/소스', '설치 구성의 AppVersion=1.2.0으로 확인한 이전 Mono 소스', None),
    ('부드러운디자인-작업전', 'work/fluid-baseline', 'app·PDF 화면·GUI 검사만 남은 부분 기준본', None),
    ('버튼모션-작업전', 'work/button-motion-baseline', 'app·GUI 검사만 남은 부분 기준본', None),
    ('콤보-작업전', 'work/combo-baseline', 'app·GUI 검사만 남은 부분 기준본', None),
    ('탭잔상-작업전', 'work/tab-ghost-baseline', 'app·GUI 검사만 남은 부분 기준본', None),
    ('호버대비-작업전', 'work/hover-contrast-baseline', 'app·GUI 검사만 남은 부분 기준본', None),
    ('1.4.0', 'work/studio-baseline/소스', '설치 구성의 AppVersion=1.4.0으로 확인한 스튜디오 재설계 전 소스', '1.2.0'),
    ('내부모션-작업전', 'work/internal-motion-baseline', '내부 모션 확장 전 보존된 11개 Python 파일', '1.4.0'),
    ('1.6.0', 'work/enhancement-20261030/baseline-source', '설치 구성의 AppVersion=1.6.0으로 확인한 이번 작업 전 소스', '1.4.0'),
    ('1.7.0', '소스', '이번 작업 흐름 확장 소스. 설치·실제 조작 결과는 별도 검증 기록으로 구분', '1.6.0'),
]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='\n')


def symbols(data):
    tree = ast.parse(data.decode('utf-8'))
    return sorted({node.name for node in ast.walk(tree)
                   if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))})


maps = {}
table = []
for key, source, description, previous in STAGES:
    folder = ROOT / source
    files = {p.name: p.read_bytes() for p in sorted(folder.iterdir())
             if p.is_file() and (p.suffix == '.py' or p.name in ('requirements-lock.txt', 'LICENSE.txt'))}
    for name, data in files.items():
        text = data.decode('utf-8')
        assert '\ufffd' not in text
        assert not re.search(r'(?:[CD]:[/\\]Users[/\\]|sk-[A-Za-z0-9]{20}|gh[pousr]_[A-Za-z0-9]{20})', text), (key, name)
        target = OUT / 'history' / key / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    maps[key] = files
    inventory = [{'path': name, 'bytes': len(data), 'sha256': digest(data)} for name, data in files.items()]
    write(OUT / 'history' / key / '파일목록.json', json.dumps(inventory, ensure_ascii=False, indent=2) + '\n')
    lines = [f'# {key}', '', description, '',
             '실제 보존 파일의 공개 가능한 Python·고정 의존성·기존 라이선스만 바이트 그대로 수록했습니다. 실행 자산·개인 작업 기록·설치 바이너리는 이 사본에 포함하지 않습니다.', '',
             '[소스 폴더](../../history/' + key + '/) · [크기·SHA-256 목록](../../history/' + key + '/파일목록.json)', '',
             '원래 1차·2차와 이 자료의 대응 번호는 입증되지 않아 임의로 붙이지 않았습니다. 부분 기준본의 누락 파일은 제품에서 삭제됐다는 뜻이 아닙니다.', '']
    if previous:
        old = maps[previous]
        lines += [f'비교 대상: [{previous}]({previous}.md). 확인 가능한 앞선 보존 버전과의 비교이며, 중간 버전 전체가 존재한다는 뜻은 아닙니다.', '',
                  '[공백·주석을 포함한 전체 차이](../diffs/' + key + '.patch)', '',
                  '| 파일 | 비교 상태 | 이전 바이트 / SHA-256 | 현재 바이트 / SHA-256 | 코드에서 확인한 이름 변화 |',
                  '|---|---|---|---|---|']
        patches = []
        for name in sorted(set(old) | set(files)):
            a, b = old.get(name), files.get(name)
            if a == b:
                state = '동일'
            elif a is None:
                state = '현재 사본에 추가'
            elif b is None:
                state = '현재 사본에 없음·삭제 의도 확인 불가'
            else:
                state = '수정'
            changes = ''
            if name.endswith('.py') and a is not None and b is not None and a != b:
                aa, bb = set(symbols(a)), set(symbols(b))
                changes = '추가: ' + ', '.join(sorted(bb-aa)) + '; 제거: ' + ', '.join(sorted(aa-bb))
            value = lambda data: '없음' if data is None else f'{len(data)} / `{digest(data)}`'
            lines.append(f'| `{name}` | {state} | {value(a)} | {value(b)} | {changes} |')
            if a != b:
                patches.extend(difflib.unified_diff((a or b'').decode('utf-8').splitlines(keepends=True),
                               (b or b'').decode('utf-8').splitlines(keepends=True),
                               fromfile=f'{previous}/{name}', tofile=f'{key}/{name}', n=3))
        write(OUT / 'docs/diffs' / (key + '.patch'), ''.join(patches))
    else:
        lines += ['확인된 직전 버전의 완전한 사본과 순서를 입증할 근거가 없어 이전 차수 비교를 만들지 않았습니다. 이후 버전 비교에 필요한 원문·해시는 위 목록에 보존했습니다.', '']
    lines += ['검증 구분: 보존 파일·해시·문법 구조의 실제 비교입니다. 이 문서를 생성하면서 과거 실행 파일이나 당시 Windows 조작을 다시 실행하지 않았습니다.', '']
    write(OUT / 'docs/versions' / (key + '.md'), '\n'.join(lines))
    table.append(f'| {key} | {description} | [폴더](history/{key}/) · [설명](docs/versions/{key}.md) | ' +
                 (f'[{previous} 대비 전체 차이](docs/diffs/{key}.patch)' if previous else '직전 비교 대상·순서 근거 없음') + ' |')

table_text = '\n'.join(['| 확인된 버전·기준본 | 보존 범위 | 소스·설명 | 비교 |', '|---|---|---|---|', *table])
write(OUT / 'history-table.md', table_text + '\n')
write(OUT / 'docs/VERSIONS.md', '# 확인된 버전과 중간 기준본\n\n' + table_text.replace('(history/', '(../history/').replace('(docs/', '(') +
      '\n\n1차·2차와 1.3·1.5의 완전한 최종 소스 대응은 확인되지 않았습니다. 남은 부분 기준본을 최종 버전으로 바꾸어 표시하지 않습니다. 최신 1.7과 앞선 1.6은 원문 파일 전체 차이로 비교합니다.\n')
print(json.dumps({'snapshots': len(STAGES), 'files': sum(len(v) for v in maps.values()),
                  'bytes': sum(len(b) for v in maps.values() for b in v.values())}, ensure_ascii=False))
