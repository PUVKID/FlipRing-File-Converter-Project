"""사용자 프리셋과 파일별 실행 전 점검. 원본과 손상된 저장 파일은 덮지 않는다."""
from __future__ import annotations
import copy
import json
import os
import re
from pathlib import Path
import shutil
import tempfile
import engine

BUILTINS = [
    {'name': 'photo_jpg', 'kind': 'convert', 'format': 'jpg', 'options': {}},
    {'name': 'scan_pdf', 'kind': 'pdf', 'format': 'pdf', 'options': {'operation': 'recognize', 'output_format': 'pdf', 'ocr_language': 'kor+eng'}},
]

class PresetStore:
    def __init__(self, path):
        self.path = Path(path)
        self.items = []
        self.error = ''
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(data, list): raise ValueError('프리셋 목록 형식 오류')
            self.items = [self.validate(row) for row in data]
            if len({row['name'].casefold() for row in self.items}) != len(self.items):
                raise ValueError('중복 프리셋 이름')
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError) as exc:
            self.error = str(exc)
            self.items = []

    @staticmethod
    def validate(row):
        if not isinstance(row, dict): raise ValueError('잘못된 프리셋')
        if set(row) - {'name', 'kind', 'format', 'options'}: raise ValueError('PDF 프리셋에 경로 또는 잘못된 옵션이 있습니다.')
        name = row.get('name', '')
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80 or any(ord(c) < 32 for c in name):
            raise ValueError('이름은 1~80자의 표시 가능한 문자여야 합니다.')
        kind, fmt, options = row.get('kind'), row.get('format'), row.get('options', {})
        formats = {fmt for _, values in engine.TABLE.values() for fmt in values.split()}
        if kind not in ('convert', 'pdf') or not isinstance(fmt, str) or fmt not in formats:
            raise ValueError('지원하지 않는 프리셋 형식입니다.')
        if not isinstance(options, dict) or (kind == 'convert' and options): raise ValueError('잘못된 프리셋 옵션입니다.')
        if kind == 'pdf':
            allowed = {'operation', 'pages', 'rotation', 'compression', 'quality', 'dpi', 'ocr_language', 'output_format', 'force_ocr', 'psm'}
            if fmt != 'pdf' or set(options) - allowed: raise ValueError('PDF 프리셋에 경로 또는 잘못된 옵션이 있습니다.')
            from pdf_tools import Request, OPERATIONS
            values = vars(Request('merge', [])).copy()
            values.pop('paths')
            values.update(options)
            integer_rules = {'rotation': {90, 180, 270}, 'quality': range(20, 96), 'dpi': range(60, 601), 'psm': {3, 6, 11}}
            valid = all(type(values[key]) is int and values[key] in choices for key, choices in integer_rules.items())
            valid = valid and isinstance(values['operation'], str) and values['operation'] in OPERATIONS
            valid = valid and isinstance(values['compression'], str) and values['compression'] in {'lossless', 'images'}
            valid = valid and isinstance(values['ocr_language'], str) and values['ocr_language'] in {'kor+eng', 'kor', 'eng'}
            valid = valid and type(values['force_ocr']) is bool and isinstance(values['pages'], str) and len(values['pages']) <= 10000
            if valid and values['pages'].strip():
                valid = bool(re.fullmatch(r'\s*[1-9][0-9]*(?:\s*-\s*[1-9][0-9]*)?(?:\s*,\s*[1-9][0-9]*(?:\s*-\s*[1-9][0-9]*)?)*\s*', values['pages']))
            outputs = {'pdf', 'txt', 'docx', 'xlsx'} if values['operation'] == 'recognize' else {'png', 'jpg'} if values['operation'] == 'pdf_to_images' else {'pdf', 'txt', 'docx', 'xlsx', 'png', 'jpg'}
            valid = valid and isinstance(values['output_format'], str) and values['output_format'] in outputs
            if not valid: raise ValueError('잘못된 프리셋 옵션입니다.')
        return {'name': name.strip(), 'kind': kind, 'format': fmt, 'options': copy.deepcopy(options)}

    def _write(self, rows):
        if self.error: raise ValueError('손상된 프리셋 파일을 보존했습니다: ' + self.error)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(rows, stream, ensure_ascii=False, indent=2)
                stream.flush(); os.fsync(stream.fileno())
            temporary.replace(self.path)
            self.items = rows
        finally:
            if temporary and temporary.exists(): temporary.unlink()

    def save(self, row):
        value = self.validate(row)
        if any(item['name'].casefold() == value['name'].casefold() for item in self.items):
            raise ValueError('이미 사용 중인 프리셋 이름입니다.')
        self._write([*self.items, value])

    def delete(self, name):
        self._write([row for row in self.items if row['name'] != name])


def preflight(path, dst):
    """최종 크기는 알 수 없으므로 입력의 4배+64MiB를 보수적인 준비 공간으로 표시한다."""
    source = Path(path)
    report = {'ok': False, 'error': '', 'code': '', 'free': 0, 'estimated': 0, 'conservative': True}
    try:
        if not source.exists():
            report['code'] = 'missing'; raise ValueError('입력이 없거나 이동되었습니다.')
        if dst not in engine.targets([source]):
            report['code'] = 'unsupported'; raise ValueError('원본과 같은 형식이거나 지원하지 않는 출력입니다.')
        missing = engine.requirement(source, dst)
        if missing:
            report['code'] = 'helper'; raise ValueError(f'{missing} 설치가 필요합니다. 외부 도우미 화면에서 설치 방법을 확인해 주세요.')
        if source.is_file():
            with source.open('rb') as stream: stream.read(1)
            size = source.stat().st_size
        else:
            size = sum(p.stat().st_size for p in source.rglob('*') if p.is_file())
        report['estimated'] = size * 4 + 64 * 1024 * 1024
        report['free'] = shutil.disk_usage(source.parent).free
        if report['free'] < report['estimated']:
            report['code'] = 'space'; raise ValueError('보수적인 예상 필요 공간보다 여유 공간이 부족합니다.')
        report['code'] = 'write'
        with tempfile.TemporaryFile(dir=source.parent) as stream:
            stream.write(b'check'); stream.flush()
        report['ok'], report['code'] = True, 'ready'
    except (OSError, ValueError) as exc:
        report['error'] = str(exc)
        if not report['code']: report['code'] = 'input'
    return report
