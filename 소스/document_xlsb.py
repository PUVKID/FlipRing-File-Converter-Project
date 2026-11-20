"""XLSB 시트 전체 내용 누락을 원본 관계와 BIFF12 셀로 확인한다.

MS-XLSB의 BrtBundleSh·Cell Table·RichStr 구조만 읽는다. 문서 변환기나
완전한 내용 동일성 검사가 아니며, 원본의 본문 문자열은 보관하지 않는다.
"""
from pathlib import PurePosixPath
import struct
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile


_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
_SHEETS = {_REL + kind: kind for kind in ('worksheet', 'chartsheet', 'dialogsheet')}
_SHEETS.update({
    'http://schemas.microsoft.com/office/2006/relationships/xlMacrosheet': 'macrosheet',
    'http://schemas.microsoft.com/office/2006/relationships/xlIntlMacrosheet': 'intlmacrosheet',
})


def _fail(detail):
    raise ValueError('XLSB 원본 구조를 안전하게 확인하지 못했습니다: ' + detail)


def _variable(stream, limit, first=None):
    value = 0
    for shift in range(limit):
        part = first if shift == 0 and first is not None else stream.read(1)
        if not part:
            _fail('잘린 레코드 머리말')
        value |= (part[0] & 127) << (7 * shift)
        if not part[0] & 128:
            return value
    _fail('레코드 머리말 길이 초과')


def _records(stream, check_cancel):
    """큰 레코드도 제한된 접두부만 메모리에 두고 끝까지 확인한다."""
    while True:
        check_cancel()
        first = stream.read(1)
        if not first:
            return
        number = _variable(stream, 2, first)
        size = _variable(stream, 4)
        prefix = stream.read(min(size, 4096))
        if len(prefix) != min(size, 4096):
            _fail('잘린 레코드 본문')
        remaining = size - len(prefix)
        while remaining:
            check_cancel()
            chunk = stream.read(min(remaining, 65536))
            if not chunk:
                _fail('잘린 레코드 본문')
            remaining -= len(chunk)
        yield number, size, prefix


def _integer(data, offset):
    if len(data) < offset + 4:
        _fail('잘린 정수 필드')
    return struct.unpack_from('<I', data, offset)[0]


def _wide(data, offset, size, *, nullable=False, decode=False, maximum=32767):
    length = _integer(data, offset)
    if nullable and length == 0xffffffff:
        return None, offset + 4
    end = offset + 4 + length * 2
    if length > maximum or end > size or (decode and end > len(data)):
        _fail('잘린 문자열 또는 허용 길이 초과')
    try:
        value = data[offset + 4:end].decode('utf-16le') if decode else bool(length)
    except UnicodeError:
        _fail('유효하지 않은 시트 문자열')
    return value, end


def _part(target):
    parsed = urlsplit(target)
    value = unquote(target)
    if (parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or '\\' in value or
            any(part in ('.', '..') for part in value.split('/')) or ':' in value or '\0' in value):
        _fail('모호하거나 외부로 벗어나는 관계 경로')
    path = value.lstrip('/') if value.startswith('/') else 'xl/' + value
    if not path.startswith('xl/') or str(PurePosixPath(path)) != path:
        _fail('통합 문서 밖의 관계 경로')
    return path


def _relationships(archive):
    raw = archive.read('xl/_rels/workbook.bin.rels')
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        _fail('관계 XML의 외부 선언')
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        _fail('유효하지 않은 관계 XML')
    if root.tag != '{http://schemas.openxmlformats.org/package/2006/relationships}Relationships':
        _fail('관계 XML 이름공간 불일치')
    result = {}
    for item in root:
        identifier = item.get('Id')
        if not identifier or identifier in result:
            _fail('중복되거나 비어 있는 관계 ID')
        result[identifier] = item.attrib
    return result


def _internal_part(relation):
    if relation.get('TargetMode', '') not in ('', 'Internal'):
        _fail('외부 관계는 읽지 않습니다')
    return _part(relation.get('Target', ''))


def _shared_strings(archive, relationships, check_cancel):
    relations = [item for item in relationships.values() if item.get('Type') == _REL + 'sharedStrings']
    if len(relations) > 1:
        _fail('모호한 공유 문자열 관계')
    if not relations:
        return []
    part = _internal_part(relations[0])
    values = []
    with archive.open(part) as stream:
        for number, size, prefix in _records(stream, check_cancel):
            if number == 19:
                nonblank, _ = _wide(prefix, 1, size)
                values.append(nonblank)
    return values


def _sheet_nonblank(archive, part, strings, check_cancel):
    nonblank = False
    in_cells = False
    seen_cells = False
    with archive.open(part) as stream:
        for number, size, prefix in _records(stream, check_cancel):
            if number == 145:
                if in_cells or seen_cells:
                    _fail('중복된 시트 본문 시작')
                in_cells = True
                seen_cells = True
            elif number == 146:
                if not in_cells:
                    _fail('시작하지 않은 시트 본문 끝')
                in_cells = False
            elif in_cells:
                if number in (2, 3, 4, 5, 8, 9, 10, 11):
                    minimum = {2: 12, 3: 9, 4: 9, 5: 16, 8: 12, 9: 16, 10: 9, 11: 9}[number]
                    if size < minimum:
                        _fail('잘린 값 또는 수식 셀')
                    nonblank = True
                elif number == 6:
                    value, _ = _wide(prefix, 8, size)
                    nonblank = nonblank or value
                elif number == 7:
                    index = _integer(prefix, 8)
                    if index >= len(strings):
                        _fail('유효하지 않은 공유 문자열 셀 참조')
                    nonblank = nonblank or strings[index]
                elif number == 62:
                    value, _ = _wide(prefix, 9, size)
                    nonblank = nonblank or value
                elif 12 <= number <= 18:
                    _fail('지원하지 않는 초기 XLSB 셀 레코드')
    if in_cells or not seen_cells:
        _fail('없거나 닫히지 않은 시트 본문')
    return bool(nonblank)


def source_sheets(source, check_cancel=lambda: None):
    """원본 worksheet별 내용 유무를 관계 ID로 연결해 수집한다."""
    check_cancel()
    try:
        with zipfile.ZipFile(source) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                _fail('중복 ZIP 항목')
            relationships = _relationships(archive)
            strings = _shared_strings(archive, relationships, check_cancel)
            result, used_names, used_parts = [], set(), set()
            with archive.open('xl/workbook.bin') as stream:
                for number, size, prefix in _records(stream, check_cancel):
                    if number != 156:
                        continue
                    relation_id, offset = _wide(prefix, 8, size, nullable=True, decode=True, maximum=255)
                    name, end = _wide(prefix, offset, size, decode=True, maximum=31)
                    if not name or name.casefold() in used_names or end != size:
                        _fail('모호한 시트 이름 또는 시트 레코드')
                    used_names.add(name.casefold())
                    relation = relationships.get(relation_id)
                    if relation is None:
                        _fail('시트 관계 누락 또는 지원하지 않는 모듈 시트')
                    kind = _SHEETS.get(relation.get('Type'))
                    if kind is None:
                        _fail('지원하지 않는 시트 관계 종류')
                    part = _internal_part(relation)
                    if part in used_parts or part not in names:
                        _fail('중복되거나 없는 시트 본문')
                    used_parts.add(part)
                    value = _sheet_nonblank(archive, part, strings, check_cancel) if kind == 'worksheet' else False
                    result.append(dict(name=name, part=part, kind=kind, nonblank=value))
            if not result:
                _fail('시트 목록이 없는 통합 문서')
            return result
    except (KeyError, zipfile.BadZipFile) as error:
        raise ValueError('XLSB 원본 필수 항목을 확인하지 못했습니다.') from error


def ensure_loaded_sheets(document, expected):
    """변환 엔진이 시트의 모든 내용을 놓친 경우 출력을 만들지 않는다."""
    actual = document.getSheets()
    for item in expected:
        if item['kind'] != 'worksheet':
            continue
        if not actual.hasByName(item['name']):
            raise ValueError('이 XLSB 변형의 시트 이름을 읽지 못해 변환을 중단했습니다: ' + item['name'])
        if item['nonblank'] and not actual.getByName(item['name']).queryContentCells(23).getCount():
            raise ValueError('XLSB 시트 내용 전체 누락을 발견해 변환을 중단했습니다: ' + item['name'])
