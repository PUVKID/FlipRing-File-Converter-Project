"""새 배포물·설치·실행·변환표의 실제 기록을 최종 파일과 대조한다."""
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8-sig'))


def inside(relative):
    path = (ROOT / relative).resolve()
    assert path.is_relative_to(ROOT) and path != ROOT, '프로젝트 경계 밖의 검증 경로'
    return path


def verify_matrix_context(context, report):
    """실제 실행 문맥의 다섯 경로를 시작·종료·현재 파일과 대조한다."""
    assert context['exit_code'] == 0
    expected = {inside(path) for path in (
        '소스/engine.py', '소스/test_conversion_matrix.py',
        '소스/vendor/7zip/7z.exe', '소스/vendor/7zip/7z.dll',
        'work/enhancement-20261030/matrix-test/fixture.rar',
    )}
    snapshots = []
    for field in ('start_sha256', 'end_sha256'):
        recorded = context[field]
        assert isinstance(recorded, dict), '변환표 문맥 해시 목록 형식 오류'
        resolved = {}
        for name, digest in recorded.items():
            assert isinstance(name, str) and Path(name).is_absolute(), '변환표 문맥은 절대 경로 필요'
            path = inside(name)
            assert path not in resolved, '변환표 문맥 경로 중복'
            resolved[path] = digest
        assert set(resolved) == expected, '변환표 문맥의 필수 경로 누락·추가'
        snapshots.append(resolved)
    for path in expected:
        assert snapshots[0][path] == snapshots[1][path] == sha(path), str(path)
    assert context['report_sha256'] == sha(inside(report))


def main():
    sources = sorted((ROOT / '소스').glob('*.py'))
    assert len(sources) == 19
    for path in sources:
        text = path.read_text(encoding='utf-8')
        assert '\ufffd' not in text
        ast.parse(text)
    release = read('evidence/1.7-배포검증.json')
    assert release['installer_exit_code'] == 0 and release['actual_launch_passed']
    assert release['manual_shift_png_cancel']['confirmed'], '새 설치본의 사용자 실제 Shift 확인 필요'
    assert release['manual_pdf_pages']['confirmed'], '새 설치본의 사용자 실제 PDF 편집 확인 필요'
    assert release['files']
    paths = [item['path'] for item in release['files']]
    assert len(set(paths)) == len(paths)
    assert {'프로그램/FlipRing/FlipRing.exe', '설치파일/FlipRing-Setup.exe',
            '소스/app.py', '소스/빌드방법.md'} <= set(paths)
    for item in release['files']:
        path = inside(item['path'])
        assert path.stat().st_size == item['size'] and sha(path) == item['sha256'], item['path']
    for record in release['bindings']:
        assert sha(inside(record['path'])) == record['sha256'], record['path']
    compiled = read('evidence/1.7-실행파일소스대조-수리19.json')
    assert compiled['passed'] and len(compiled['modules']) == 11
    assert sha(ROOT / '프로그램/FlipRing/FlipRing.exe') == compiled['exe_sha256']
    for item in compiled['modules']:
        assert item['code_equal'] and sha(ROOT / '소스' / (item['module'] + '.py')) == item['source_sha256']
    matrix = read(release['matrix_report'])
    assert matrix['expected'] == matrix['recorded'] == matrix['executed'] == 266
    assert not matrix['missing'] and matrix['duplicate'] == 0
    assert len(matrix['results']) == 266 and all(item['status'] == 'passed' for item in matrix['results'])
    assert matrix['extras'] and all(item['status'] == 'passed' for item in matrix['extras'])
    assert not matrix['fixture_errors']
    context = read(release['matrix_context'])
    verify_matrix_context(context, release['matrix_report'])
    installed = read('evidence/1.7-설치파일전체대조.json')
    assert installed['passed'] and len(installed['files']) == 624
    assert all(item['installed_matches'] for item in installed['files'])
    print(json.dumps({'source_files': len(sources), 'shipping_files': len(paths),
                      'compiled_modules': 11, 'installed_files': 624, 'conversion_pairs': 266,
                      'passed': True}, ensure_ascii=False))


if __name__ == '__main__':
    main()
