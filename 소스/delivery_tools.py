"""원본 보존형 호환 안내·선택 메타데이터 정리·문서 비교. 결과는 로컬 전용이다."""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path, PurePosixPath
import stat
import struct
import tempfile
import unicodedata
import zipfile
import zlib

from PIL import Image, ExifTags
from lxml import etree
from pypdf import PdfWriter
from pypdf.generic import NameObject

import engine
import inspection_tools
from document_formats import validate_input, support_matrix, _safe_xml_import
from document_hwp import MAX_FILE, MAX_TOTAL, MAX_XML, require_regular, bounded_read
from pdf_tools import check_cancel, reader_for, publish, preflight_output, source_context

OOXML = set('docx docm dotx dotm xlsx xlsm xltx xltm xlsb pptx pptm potx potm ppsx ppsm'.split())
IMAGE_EDIT = {'jpg', 'jpeg', 'png'}
LIMITATION = {
    'ko': '본문·첨부·댓글·변경 이력에 있는 개인정보는 별도 검토해야 합니다. 탐지되지 않음은 보존·완전 제거 보장이 아닙니다.',
    'en': 'Review personal data in content, attachments, comments and revisions separately. No finding is not a guarantee of preservation or complete removal.',
}


class DeliveryError(ValueError):
    """기계 코드와 한영 로컬 안내를 함께 보존한다."""
    def __init__(self, code, ko, en):
        super().__init__(ko)
        self.code, self.ko, self.en = code, ko, en


def _package(source, cancel):
    """기존 문서 한도와 XML 선언 방어를 재사용하되 외부 관계는 실행하지 않고 탐지한다."""
    validate_input(source, source.suffix[1:].lower())
    result, total, seen = {}, 0, set()
    with zipfile.ZipFile(source) as archive:
        entries = archive.infolist()
        if len(entries) > 4096:
            raise ValueError('ZIP 항목 수 제한 초과')
        for item in entries:
            check_cancel(cancel)
            name = item.orig_filename
            normalized = unicodedata.normalize('NFC', name).casefold()
            if (normalized in seen or '\x00' in name or '\\' in name or ':' in name or
                    name.startswith('/') or '..' in PurePosixPath(name).parts or
                    stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1 or
                    item.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}):
                raise ValueError('안전하지 않은 ZIP 항목')
            seen.add(normalized)
            total += item.file_size
            if (item.file_size > MAX_FILE or total > MAX_TOTAL or
                    item.file_size > max(1, item.compress_size) * 1000):
                raise ValueError('ZIP 압축 해제 제한 초과')
            with archive.open(item) as stream:
                data = stream.read(min(MAX_FILE, item.file_size) + 1)
            if len(data) != item.file_size:
                raise ValueError('ZIP 실제 크기 불일치')
            if name.lower().endswith(('.xml', '.rels')):
                if len(data) > MAX_XML:
                    raise ValueError('XML 크기 제한 초과')
                _safe_xml_import(data, 'docx')
            result[name] = data
    return result


def _xml(data):
    _safe_xml_import(data, 'docx')
    return etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))


def compatibility_report(path, target, cancel=None):
    check_cancel(cancel)
    source = require_regular(path)
    extension = source.suffix[1:].lower()
    target = str(target).lower().lstrip('.')
    row = next((r for r in support_matrix() if extension in r['inputs']), None)
    report = {'path': str(source), 'source': extension, 'format': target, 'local_only': True,
              'supported': target in engine.targets([source]), 'checked': False,
              'macros': None, 'formulas': None, 'fonts': [], 'external_links': None,
              'notes': {'ko': [row['notes']] if row else [], 'en': []},
              'limitations': dict(LIMITATION)}
    if extension in OOXML:
        parts = _package(source, cancel)
        macros, formulas, external, fonts = False, 0, 0, set()
        for name, data in parts.items():
            check_cancel(cancel)
            macros |= name.lower().endswith('vbaproject.bin')
            if name.lower().endswith(('.xml', '.rels')):
                root = _xml(data)
                for node in root.iter():
                    if not isinstance(node.tag, str):
                        continue
                    local = node.tag.rsplit('}', 1)[-1]
                    if local in {'f', 'formula', 'oMath', 'fldSimple', 'instrText'}:
                        formulas += 1
                    if local == 'Relationship' and node.get('TargetMode', '').lower() == 'external':
                        external += 1
                    if local in {'rFonts', 'font', 'latin', 'ea', 'cs', 'name'}:
                        for key, value in node.attrib.items():
                            if key.rsplit('}', 1)[-1] in {'ascii', 'hAnsi', 'eastAsia', 'cs', 'typeface', 'name', 'val'}:
                                fonts.add(value)
        report.update(checked=True, macros=macros, formulas=formulas,
                      external_links=external, fonts=sorted(fonts))
    else:
        report['notes']['ko'].append('이 형식의 내부 매크로·수식·글꼴·외부 링크는 검사하지 못했습니다.')
        report['notes']['en'].append('Internal macros, formulas, fonts and external links were not inspected for this format.')
    report['notes']['ko'].append('출력에 따라 매크로·수식·글꼴·배치가 달라질 수 있습니다. 원본과 실제 결과를 비교하세요.')
    report['notes']['en'].append('Macros, formulas, fonts and layout may change on export. Compare the actual result with the original.')
    if row:
        report['notes']['en'].append('Only the advertised output formats are supported. Dedicated Office features and embedded objects may change; CSV/TSV contains the first sheet and displayed values. HWP input/output requires the configured local document tools.')
    check_cancel(cancel)
    return report


def _exif_items(exif):
    entries = []
    for key in sorted(exif):
        if key in {34665, 34853, 40965}:
            # GPS는 실제 하위 키·값을 보여주고 그룹 자체도 명시 선택한다.
            value = dict(exif.get_ifd(key))
        else:
            value = exif[key]
        entries.append({'key': f'exif:{key}', 'label': ExifTags.TAGS.get(key, str(key)), 'value': str(value)})
    return entries


def _jpeg_segments(raw):
    if not raw.startswith(b'\xff\xd8'):
        raise ValueError('JPEG 서명 오류')
    yield None, raw[:2]
    offset = 2
    while offset < len(raw):
        start = offset
        if raw[offset] != 255:
            raise ValueError('JPEG 마커 오류')
        while offset < len(raw) and raw[offset] == 255:
            offset += 1
        if offset >= len(raw):
            raise ValueError('JPEG 마커 누락')
        marker = raw[offset]
        offset += 1
        if marker in {0xDA, 0xD9}:
            yield marker, raw[start:]
            return
        if marker == 1 or 0xD0 <= marker <= 0xD7:
            yield marker, raw[start:offset]
            continue
        length = int.from_bytes(raw[offset:offset + 2], 'big')
        if length < 2 or offset + length > len(raw):
            raise ValueError('JPEG 세그먼트 길이 오류')
        end = offset + length
        yield marker, raw[start:end]
        offset = end
    raise ValueError('JPEG 영상 데이터 누락')


def _jpeg_payload(segment):
    """채움 FF와 마커, 길이 필드를 건너뛰어 실제 세그먼트 내용을 반환한다."""
    offset = 0
    while offset < len(segment) and segment[offset] == 255:
        offset += 1
    return segment[offset + 3:]


def _png_chunks(raw):
    if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('PNG 서명 오류')
    offset = 8
    while offset < len(raw):
        size = int.from_bytes(raw[offset:offset + 4], 'big')
        end = offset + size + 12
        if end > len(raw):
            raise ValueError('PNG 청크 길이 오류')
        kind, data = raw[offset + 4:offset + 8], raw[offset + 8:end - 4]
        if zlib.crc32(kind + data) != int.from_bytes(raw[end - 4:end], 'big'):
            raise ValueError('PNG 청크 CRC 오류')
        yield kind, data, raw[offset:end]
        offset = end
        if kind == b'IEND':
            if offset != len(raw):
                raise ValueError('PNG 종료 뒤 추가 데이터')
            return
    raise ValueError('PNG 종료 누락')


def metadata_report(path, cancel=None):
    check_cancel(cancel)
    source = require_regular(path)
    extension = source.suffix[1:].lower()
    entries = []
    supported = extension in OOXML | IMAGE_EDIT | {'pdf'}
    with source_context(source):
        if extension in OOXML:
            parts = _package(source, cancel)
            for name in ('docProps/core.xml', 'docProps/app.xml', 'docProps/custom.xml'):
                if name not in parts:
                    continue
                for index, node in enumerate(_xml(parts[name])):
                    if not isinstance(node.tag, str):
                        continue
                    entries.append({'key': f'ooxml:{name}:{index}',
                                    'label': node.get('name') or node.tag.rsplit('}', 1)[-1],
                                    'value': ''.join(node.itertext()),
                                    'fingerprint': sha256(etree.tostring(node, method='c14n', with_tail=False)).hexdigest()})
        elif extension == 'pdf':
            reader = reader_for(source)
            try:
                for key, value in (reader.metadata or {}).items():
                    entries.append({'key': 'pdf:' + str(key), 'label': str(key), 'value': str(value)})
                if '/Metadata' in reader.trailer['/Root']:
                    data = reader.trailer['/Root']['/Metadata'].get_data()
                    if len(data) > MAX_XML:
                        raise ValueError('PDF XMP 크기 제한 초과')
                    entries.append({'key': 'pdf:xmp', 'label': 'XMP (전체 / entire packet)',
                                    'value': data.decode('utf-8', errors='replace')})
            finally:
                reader.close()
        elif extension in IMAGE_EDIT:
            raw = bounded_read(source)
            with Image.open(source) as image:
                entries.extend(_exif_items(image.getexif()))
            if extension in {'jpg', 'jpeg'}:
                for index, (marker, segment) in enumerate(_jpeg_segments(raw)):
                    if marker not in {0xFE, 0xE1, 0xED}:
                        continue
                    payload = _jpeg_payload(segment)
                    if marker == 0xFE or (marker == 0xE1 and not payload.startswith(b'Exif\x00\x00')) or marker == 0xED:
                        entries.append({'key': f'jpeg:{index}', 'label': 'JPEG comment / XMP / IPTC',
                                        'value': repr(payload[:4096]),
                                        'fingerprint': sha256(bytes([marker]) + payload).hexdigest()})
            else:
                for index, (kind, data, _) in enumerate(_png_chunks(raw)):
                    if kind in {b'tEXt', b'iTXt', b'zTXt'}:
                        entries.append({'key': f'png:{index}', 'label': kind.decode() + ': ' + data.split(b'\x00')[0].decode('latin1'),
                                        'value': repr(data[:4096]),
                                        'fingerprint': sha256(kind + data).hexdigest()})
    check_cancel(cancel)
    return {'path': str(source), 'source': extension, 'format': extension, 'local_only': True,
            'supported': supported, 'entries': entries, 'limitations': dict(LIMITATION),
            'notice': {'ko': ('JPEG/PNG 영상 데이터를 재압축하지 않습니다.' if extension in IMAGE_EDIT else
                              'PDF는 전체 문서 객체를 복제합니다. 전자서명 유효성·프로그램별 동작의 동일성은 보장하지 않습니다.' if extension == 'pdf' else
                              '선택한 속성만 제거하며 나머지 ZIP 부분은 내용 바이트를 보존합니다.' if extension in OOXML else
                              '이 형식의 선택 메타데이터 정리는 지원하지 않습니다. 원본을 변경하지 않았습니다.'),
                       'en': ('JPEG/PNG image data is not recompressed.' if extension in IMAGE_EDIT else
                              'PDF document objects are cloned; digital signature validity and identical application behavior are not guaranteed.' if extension == 'pdf' else
                              'Only selected properties are removed; other ZIP parts retain their content bytes.' if extension in OOXML else
                              'Selective metadata removal is unsupported for this format. The original was not modified.')}}


def _verify_metadata_removed(before, after, keys):
    """위치 키는 삭제 뒤 재색인되므로 원문 지문과 개수로 미선택 항목을 대조한다."""
    stable_keys = {key for key in keys if key.startswith(('exif:', 'pdf:'))}
    if stable_keys & {entry['key'] for entry in after['entries']}:
        raise ValueError('선택한 메타데이터가 남아 있습니다.')

    def indexed_entries(entries, excluded):
        return Counter((entry['key'].rsplit(':', 1)[0], entry['fingerprint'])
                       for entry in entries if entry['key'].startswith(('ooxml:', 'jpeg:', 'png:'))
                       and entry['key'] not in excluded)

    if indexed_entries(before['entries'], keys) != indexed_entries(after['entries'], set()):
        raise ValueError('선택한 메타데이터 제거 또는 미선택 항목 보존을 확인하지 못했습니다.')


def strip_metadata(path, keys, output_dir, cancel=None):
    check_cancel(cancel)
    source = require_regular(path)
    output = inspection_tools._output(output_dir)
    report = metadata_report(source, cancel)
    if not report['supported']:
        raise DeliveryError('unsupported_metadata', report['notice']['ko'], report['notice']['en'])
    keys = set(keys)
    if not keys or not keys <= {entry['key'] for entry in report['entries']}:
        raise DeliveryError('metadata_keys', '현재 탐지한 항목을 하나 이상 선택하세요.', 'Select one or more currently detected metadata entries.')
    preflight_output(output, source.stat().st_size * 3 + 4 * 1024 * 1024, cancel)
    extension = report['source']
    with source_context(source), tempfile.TemporaryDirectory(prefix='.flipring-metadata-', dir=output) as folder:
        destination = Path(folder) / ('clean' + source.suffix)
        if extension in OOXML:
            parts = _package(source, cancel)
            for name in ('docProps/core.xml', 'docProps/app.xml', 'docProps/custom.xml'):
                selected = [key for key in keys if key.startswith(f'ooxml:{name}:')]
                if selected:
                    root = _xml(parts[name])
                    for index, node in reversed(list(enumerate(root))):
                        if f'ooxml:{name}:{index}' in keys:
                            root.remove(node)
                    parts[name] = etree.tostring(root, xml_declaration=True, encoding='UTF-8')
            with zipfile.ZipFile(source) as original, zipfile.ZipFile(destination, 'x') as cleaned:
                cleaned.comment = original.comment
                for item in original.infolist():
                    check_cancel(cancel)
                    cleaned.writestr(item, parts[item.filename])
        elif extension == 'pdf':
            reader = reader_for(source)
            writer = PdfWriter()
            try:
                writer.clone_document_from_reader(reader)
                if writer._info is not None:
                    info = writer._info.get_object()
                    for key in keys:
                        if key.startswith('pdf:/'):
                            info.pop(NameObject(key[4:]), None)
                if 'pdf:xmp' in keys:
                    writer._root_object.pop(NameObject('/Metadata'), None)
                check_cancel(cancel)
                with destination.open('xb') as stream:
                    writer.write(stream)
            finally:
                writer.close()
                reader.close()
        else:
            raw = bounded_read(source)
            with Image.open(source) as image:
                exif = image.getexif()
                for key in keys:
                    if key.startswith('exif:'):
                        del exif[int(key[5:])]
                exif_data = exif.tobytes() if len(exif) else b''
            if extension in {'jpg', 'jpeg'}:
                pieces = []
                for index, (marker, segment) in enumerate(_jpeg_segments(raw)):
                    check_cancel(cancel)
                    if f'jpeg:{index}' in keys:
                        continue
                    payload = _jpeg_payload(segment) if marker == 0xE1 else b''
                    if marker == 0xE1 and payload.startswith(b'Exif\x00\x00') and any(k.startswith('exif:') for k in keys):
                        if exif_data:
                            if len(exif_data) > 65533:
                                raise ValueError('JPEG EXIF 크기 제한 초과')
                            prefix = segment[:len(segment) - len(payload) - 2]
                            segment = prefix + struct.pack('>H', len(exif_data) + 2) + exif_data
                        else:
                            continue
                    pieces.append(segment)
                with destination.open('xb') as stream:
                    stream.write(b''.join(pieces))
            else:
                pieces = [raw[:8]]
                for index, (kind, data, chunk) in enumerate(_png_chunks(raw)):
                    check_cancel(cancel)
                    if f'png:{index}' in keys:
                        continue
                    if kind == b'eXIf' and any(k.startswith('exif:') for k in keys):
                        if not exif_data:
                            continue
                        data = exif_data[6:]
                        chunk = struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
                    pieces.append(chunk)
                with destination.open('xb') as stream:
                    stream.write(b''.join(pieces))
        check_cancel(cancel)
        # 실제 사본을 다시 읽어 선택 제거를 확인한 후에만 배타적으로 발행한다.
        after = metadata_report(destination, cancel)
        _verify_metadata_removed(report, after, keys)
        return publish(destination, output / source.stem, 'metadata', cancel)


def compare_documents(left, right, cancel=None, page=0):
    """문서는 임시 사본을 변환하므로 입력 폴더에도 변환 결과를 남기지 않는다."""
    check_cancel(cancel)
    sources = [require_regular(path) for path in (left, right)]
    with tempfile.TemporaryDirectory(prefix='.flipring-compare-') as folder:
        prepared = []
        for index, source in enumerate(sources):
            check_cancel(cancel)
            if source.suffix.lower() == '.pdf' or engine.classify(source)[0] == '이미지':
                prepared.append(source)
            else:
                work = Path(folder) / str(index)
                work.mkdir()
                copied = work / source.name
                with source.open('rb') as original, copied.open('xb') as stream:
                    while block := original.read(1024 * 1024):
                        check_cancel(cancel)
                        stream.write(block)
                prepared.append(Path(engine.convert(copied, 'pdf', cancel=cancel)))
        result = inspection_tools.compare_files(*prepared, cancel=cancel)
        images = []
        for index, path in enumerate(prepared):
            check_cancel(cancel)
            count = result['left' if index == 0 else 'right']['page_count']
            images.append(inspection_tools.render_page(path, page, 120) if page < count else None)
        for key, source in zip(('left', 'right'), sources):
            result[key]['path'] = str(source)
        result.update(images=images, page=page, local_only=True,
                      limitations={'ko': '실제 렌더와 추출 텍스트 비교입니다. 픽셀·의미의 완전 동일성을 자동 판정하지 않습니다.',
                                   'en': 'Actual rendered pages and extracted text are compared. Complete pixel or semantic equivalence is not automatically determined.'})
        return result
