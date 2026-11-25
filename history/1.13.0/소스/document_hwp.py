"""앱 Python에서만 실행하는 제한된 HWP5/HWPX 저장 코어."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import tempfile
import unicodedata
import warnings
import zipfile
import zlib

import document_formats

MAX_FILE = 128 * 1024 * 1024
MAX_TOTAL = 512 * 1024 * 1024
MAX_XML = 64 * 1024 * 1024
MAX_IMAGE = 32 * 1024 * 1024
MAX_PIXELS = 50_000_000
NATIVE_INPUTS = frozenset({'docx', 'txt', 'hwp', 'hwpx'})
NATIVE_TARGETS = frozenset({'hwp', 'hwpx'})
# python-hwpx 6.12.0 summary.py의 새 문서 상수만 허용한다. 임의 공백·후행 코드도 거부한다.
_DEFAULT_HEADER_SCRIPT = 'var Documents = XHwpDocuments;\r\nvar Document = Documents.Active_XHwpDocument;\r\n'
_DEFAULT_SOURCE_SCRIPT = 'function OnDocument_New()\r\n{\r\n\t//todo : \r\n}\r\n'
_SCRIPT_TEXTS = {'Scripts/headerScripts': ('', _DEFAULT_HEADER_SCRIPT),
                 'Scripts/sourceScripts': ('', _DEFAULT_SOURCE_SCRIPT)}


def plain(value):
    """보고서 필드를 빠짐없이 보존하고 모르는 타입은 거부한다."""
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError('보고서 키는 문자열이어야 합니다.')
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise TypeError('보고서의 미지원 값 형식: ' + type(value).__name__)


def bounded_read(path, limit=MAX_FILE):
    with Path(path).open('rb') as stream:
        data = stream.read(limit + 1)
    if not data or len(data) > limit:
        raise ValueError('입력이 비어 있거나 크기 제한을 초과했습니다.')
    return data


def require_regular(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('링크·재분석 경로는 문서 작업에 사용하지 않습니다.')
    if not path.is_file():
        raise ValueError('일반 문서 파일이 필요합니다.')
    return path


def _xml(data, name):
    from hwpx.opc.xml_utils import parse_untrusted_xml
    if len(data) > MAX_XML:
        raise ValueError('XML 크기 제한을 초과했습니다.')
    try:
        root = parse_untrusted_xml(data, part_name=name)
    except Exception as error:
        raise ValueError('안전하지 않거나 손상된 XML: ' + name) from error
    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        local = node.tag.rsplit('}', 1)[-1]
        if local in {'script', 'scriptCode', 'ole', 'equation', 'video', 'chart'}:
            raise ValueError('지원하지 않는 능동 콘텐츠·수식·개체입니다: ' + local)
        if local == 'linkinfo' and (node.get('path', '') or
                node.get('pageInherit', '0') not in {'0', 'false'} or
                node.get('footnoteInherit', '0') not in {'0', 'false'}):
            raise ValueError('연결 문서 정보는 변환하지 않습니다.')
        for key, value in node.attrib.items():
            attr = key.rsplit('}', 1)[-1]
            if attr == 'TargetMode' and value.lower() == 'external':
                raise ValueError('외부 문서 관계는 변환하지 않습니다.')
            if attr in {'href', 'src', 'Target'} and (re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', value) or value.startswith(('//', '\\'))):
                raise ValueError('외부 파일·네트워크 참조는 변환하지 않습니다.')
    return root


def _image(data):
    from PIL import Image
    if len(data) > MAX_IMAGE:
        raise ValueError('그림 바이트 제한을 초과했습니다.')
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in {'PNG', 'JPEG'} or image.width * image.height > MAX_PIXELS or getattr(image, 'n_frames', 1) != 1:
                    raise ValueError('PNG/JPEG 단일 그림과 픽셀 제한을 확인해 주세요.')
                result = (image.format.lower(), image.size)
                image.verify()
        except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
            raise ValueError('손상되었거나 과대한 그림입니다.') from error
    return result


def guard_package(source):
    """메타데이터와 유한 읽기·XML 검사를 legacy 검증보다 먼저 수행한다."""
    try:
        with zipfile.ZipFile(source) as package:
            entries = package.infolist()
            if len(entries) > 4096:
                raise ValueError('ZIP 항목 수 제한을 초과했습니다.')
            seen, total, parts = set(), 0, {}
            for info in entries:
                name = info.orig_filename
                normalized = unicodedata.normalize('NFC', name).casefold()
                path = PurePosixPath(name)
                if ('\x00' in name or '\\' in name or ':' in name or name.startswith('/')
                        or any(p in {'..', '.'} for p in name.split('/')) or normalized in seen
                        or any(p.endswith((' ', '.')) for p in path.parts)
                        or stat.S_ISLNK(info.external_attr >> 16)):
                    raise ValueError('ZIP 이름 충돌·링크·위험 경로를 거부했습니다.')
                seen.add(normalized)
                if info.flag_bits & 1 or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise ValueError('암호·미지원 압축방식의 ZIP입니다.')
                total += info.file_size
                if (info.file_size > MAX_FILE or total > MAX_TOTAL
                        or info.file_size > max(1, info.compress_size) * 1000):
                    raise ValueError('ZIP 압축 해제 제한을 초과했습니다.')
            actual = 0
            for info in entries:
                limit = min(MAX_FILE, MAX_TOTAL - actual)
                with package.open(info) as stream:
                    data = stream.read(limit + 1)
                if len(data) > limit or len(data) != info.file_size:
                    raise ValueError('ZIP 실제 크기가 안전 범위·선언 크기와 다릅니다.')
                actual += len(data)
                name = info.filename
                if name.lower().endswith(('.xml', '.rels', '.hpf')):
                    _xml(data, name)
                if name.startswith('META-INF/') and name.endswith('manifest.xml') and len(data) > 8 * 1024 * 1024:
                    raise ValueError('문서 매니페스트가 비정상적으로 큽니다.')
                if name.startswith(('BinData/', 'word/media/')) and not info.is_dir():
                    _image(data)
                parts[name] = data
            _guard_hwpx_parts(parts)
            return parts
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as error:
        raise ValueError('손상되었거나 지원하지 않는 ZIP 문서입니다.') from error


def _guard_hwpx_parts(parts):
    """실제 스크립트와 HWPX 매니페스트를 함께 검사해 외부 운반을 막는다."""
    for name, data in parts.items():
        if name.casefold().startswith('scripts/') and not name.endswith('/'):
            allowed = _SCRIPT_TEXTS.get(name)
            if allowed is None or data not in {
                    prefix + text.encode('utf-16-le') for text in allowed for prefix in (b'', b'\xff\xfe')}:
                raise ValueError('사용자 스크립트·알 수 없는 스크립트 부품은 변환하지 않습니다.')
    if 'Contents/content.hpf' not in parts:
        return
    root = _xml(parts['Contents/content.hpf'], 'Contents/content.hpf')
    for item in root.iter():
        if not isinstance(item.tag, str) or item.tag.rsplit('}', 1)[-1] != 'item':
            continue
        href = item.get('href', '')
        if (item.get('isEmbeded', '1') not in {'1', 'true'} or not href
                or href != href.strip() or any(c in href for c in ('\\', ':', '%', '?', '#', '\x00'))
                or href.startswith('/') or any(p in {'', '.', '..'} for p in href.split('/'))
                or href not in parts):
            raise ValueError('외부·누락·위험 경로의 HWPX 참조는 변환하지 않습니다.')
        script_part = {'headersc': 'Scripts/headerScripts', 'sourcesc': 'Scripts/sourceScripts'}.get(item.get('id'))
        if script_part is not None and href != script_part:
            raise ValueError('스크립트 매니페스트 경로가 허용된 기본 부품과 다릅니다.')


def _guard_hwp_script(name, data, compressed):
    """실행하지 않고 유한 해제·CRC와 정확한 기본 스텁 바이트를 대조한다."""
    if compressed:
        decoder = zlib.decompressobj(-15)
        raw = decoder.decompress(data, 4097)
        trailer = decoder.unused_data
        if (len(raw) > 4096 or decoder.unconsumed_tail or not decoder.eof or len(trailer) != 8
                or struct.unpack('<II', trailer) != (zlib.crc32(raw), len(raw))):
            raise ValueError('손상·과대·후행 데이터가 있는 HWP 스크립트입니다.')
    else:
        raw = data
    if name == 'Scripts/JScriptVersion':
        allowed = {b'\x01\x00\x00\x00\x00\x00\x00\x00'}
    elif name == 'Scripts/DefaultJScript':
        allowed = set()
        for header in ('', _DEFAULT_HEADER_SCRIPT):
            for source in ('', _DEFAULT_SOURCE_SCRIPT):
                stub = b''
                for text in (header, source, '', ''):
                    encoded = text.encode('utf-16-le')
                    stub += struct.pack('<I', len(encoded) // 2) + encoded
                allowed.add(stub + b'\xff\xff\xff\xff')
    else:
        raise ValueError('알 수 없는 HWP 스크립트 부품입니다.')
    if raw not in allowed:
        raise ValueError('사용자 실행 코드를 포함한 HWP 스크립트는 변환하지 않습니다.')


def _guard_hwp_bin_links(data):
    """객체 트리를 만들지 않고 유한 DocInfo 레코드에서 BIN_LINK를 검사한다."""
    from hwpx.hwp5.docinfo import BinDataItem
    binary_streams = set()
    offset = count = 0
    while offset < len(data):
        if offset + 4 > len(data):
            raise ValueError('잘린 HWP DocInfo 레코드입니다.')
        word = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        size = word >> 20
        if size == 0xfff:
            if offset + 4 > len(data):
                raise ValueError('잘린 HWP 확장 레코드 길이입니다.')
            size = struct.unpack_from('<I', data, offset)[0]
            offset += 4
        if offset + size > len(data):
            raise ValueError('HWP 레코드가 스트림을 벗어납니다.')
        count += 1
        if count > 4_000_000:
            raise ValueError('HWP 레코드 수 제한을 초과했습니다.')
        # HWP5 BIN_DATA 태그 0x12의 속성 하위 4비트: 0=링크, 1=내장 그림, 2=저장소.
        if word & 0x3ff == 0x12:
            if size < 2 or struct.unpack_from('<H', data, offset)[0] & 0xf != 1:
                raise ValueError('외부 BIN_LINK·미지원 저장소 개체는 변환하지 않습니다.')
            item = BinDataItem.decode(data[offset:offset + size])
            binary_streams.add('BinData/' + item.stream_name)
        offset += size
    return binary_streams


def _inflate(data):
    decoder = zlib.decompressobj(-15)
    raw = decoder.decompress(data, MAX_FILE + 1)
    if len(raw) > MAX_FILE or decoder.unconsumed_tail or not decoder.eof:
        raise ValueError('HWP 압축 스트림이 손상되었거나 제한을 초과했습니다.')
    return raw


def guard_hwp(data):
    from hwpx.hwp5.cfb import CompoundFile
    from hwpx.hwp5.fileheader import parse_file_header
    from hwpx.hwp5.reader import refuse_protected
    try:
        compound = CompoundFile(data)
        paths = compound.stream_paths()
        if len(paths) > 4096 or len({p.casefold() for p in paths}) != len(paths):
            raise ValueError('HWP 스트림 수·이름 충돌을 확인해 주세요.')
        header = parse_file_header(compound.read('FileHeader'))
        if header.version[0] != 5:
            raise ValueError('새 저장 경로는 HWP5만 지원합니다.')
        refuse_protected(header)
        if header.has('script'):
            raise ValueError('스크립트 플래그가 있는 HWP는 변환하지 않습니다.')
        # reader/package/writer가 실제 처리하는 최소 스트림만 허용한다.
        # MemoExtended/Bibliography/ViewText 등 왕복 보존이 확인되지 않은 부품도 거부한다.
        fixed = {'FileHeader', 'DocInfo', 'DocOptions/_LinkDoc',
                 '\x05HwpSummaryInformation', 'PrvText', 'PrvImage',
                 'Scripts/DefaultJScript', 'Scripts/JScriptVersion'}
        metadata = {'standard_metadata_streams': [], 'omitted_derived_streams': [],
                    'normalized_derived_streams': [], 'default_script_streams': [],
                    'summary_mapping': '선택한 표준 속성만 매핑하며 전체 원메타 바이트 보존을 뜻하지 않음'}
        declared_binaries = set()
        present_binaries = set()
        total = 0
        for name in paths:
            if (name not in fixed and not re.fullmatch(r'BodyText/Section(?:0|[1-9][0-9]*)', name)
                    and not name.startswith('BinData/')):
                raise ValueError('보존을 지원하지 않는 HWP 스트림이 있어 저장하지 않았습니다: ' + name)

            raw = compound.read(name)
            if len(raw) > MAX_FILE:
                raise ValueError('HWP 스트림 크기 제한을 초과했습니다.')
            if name.casefold().startswith('scripts/'):
                _guard_hwp_script(name, raw, header.compressed)
                metadata['default_script_streams'].append(name)
            if name.casefold() == 'docoptions/_linkdoc' and raw != bytes(524):
                raise ValueError('연결 문서가 있는 HWP는 변환하지 않습니다.')
            if header.compressed and (name == 'DocInfo' or name.startswith(('BodyText/', 'BinData/'))):
                raw = _inflate(raw)
            total += len(raw)
            if total > MAX_TOTAL:
                raise ValueError('HWP 전체 해제 크기 제한을 초과했습니다.')
            if name == 'DocInfo':
                declared_binaries = _guard_hwp_bin_links(raw)
            if name.startswith('BinData/'):
                present_binaries.add(name)
                _image(raw)
            if name == '\x05HwpSummaryInformation':
                metadata['standard_metadata_streams'].append(name)
            elif name == 'PrvImage':
                metadata['omitted_derived_streams'].append(name)
            elif name == 'PrvText':
                metadata['normalized_derived_streams'].append(name)
        if declared_binaries != present_binaries:
            raise ValueError('DocInfo와 실제 HWP 그림 스트림 목록이 달라 저장하지 않았습니다.')
        return metadata
    except ValueError:
        raise
    except Exception as error:
        raise ValueError('보호되었거나 손상된 HWP5입니다: ' + str(error)) from error


def require_no_loss(report):
    report = plain(report) if report is not None else {}
    if any(report.get(name) for name in ('unconverted', 'dropped')):
        raise ValueError('지원하지 않는 내용이 있어 저장하지 않았습니다: ' + json.dumps(report, ensure_ascii=False))
    return report


def require_quality(report):
    report = plain(report)
    if report.get('ok') is not True or report.get('errors') or report.get('error_codes'):
        raise ValueError('문서 구조 저장 검사를 통과하지 못했습니다.')
    for stage in ('open_safety', 'semantic', 'form', 'layout'):
        value = report.get(stage, {})
        if value.get('ok') is not True or value.get('errors'):
            raise ValueError('문서 구조 단계 실패: ' + stage)
    if report['layout'].get('status') != 'passed':
        raise ValueError('문서 배치 구조 검사가 실행되지 않았습니다.')
    if report.get('render_checked') is not False or report.get('visual_complete') is not False:
        raise ValueError('허용하지 않은 시각 검사 상태입니다.')
    return report


def _docx_document(source, parts):
    from docx import Document
    from docx.text.paragraph import Paragraph
    from docx.table import Table
    from hwpx import HwpxDocument
    from docx.oxml.ns import qn
    doc = Document(source)
    out = HwpxDocument.new(inherit_style=False)
    # 조용히 사라질 수 있는 본문 제어와 부속 문서는 처음부터 거부한다.
    refused = {'altChunk', 'fldSimple', 'fldChar', 'instrText', 'footnoteReference', 'endnoteReference',
               'commentReference', 'ins', 'del', 'hyperlink', 'object', 'pict', 'sdt', 'oMath', 'oMathPara',
               'headerReference', 'footerReference', 'anchor', 'gridSpan', 'vMerge', 'trackRevisions'}
    for root_name in ('word/document.xml', 'word/settings.xml'):
        if root_name in parts:
            root = _xml(parts[root_name], root_name)
            if any(isinstance(n.tag, str) and n.tag.rsplit('}', 1)[-1] in refused for n in root.iter()):
                raise ValueError('이 DOCX의 제어·병합·주석·수식은 아직 저장하지 않습니다.')

    def paragraph(block, destination):
        for child in block._p:
            if child.tag == qn('w:pPr'):
                continue
            if child.tag != qn('w:r'):
                raise ValueError('지원하지 않는 문단 자식입니다.')
            from docx.text.run import Run
            run = Run(child, block)
            for node in child:
                if node.tag == qn('w:rPr'):
                    continue
                if node.tag in {qn('w:t'), qn('w:tab'), qn('w:br'), qn('w:cr')}:
                    text = node.text or '' if node.tag == qn('w:t') else '\t' if node.tag == qn('w:tab') else '\n'
                    destination.add_run(text, bold=bool(run.bold), italic=bool(run.italic))
                elif node.tag == qn('w:drawing'):
                    drawings = node.xpath('.//wp:inline')
                    blips = node.xpath('.//a:blip')
                    if len(drawings) != 1 or len(blips) != 1 or node.xpath('.//a:srcRect'):
                        raise ValueError('떠 있는 그림·자르기는 아직 지원하지 않습니다.')
                    transforms = node.xpath('.//a:xfrm')
                    if any(n.get('rot', '0') != '0' or n.get('flipH') in ('1', 'true') or n.get('flipV') in ('1', 'true') for n in transforms):
                        raise ValueError('회전·반전된 그림은 아직 지원하지 않습니다.')
                    rid = blips[0].get(qn('r:embed'))
                    if not rid or rid not in block.part.rels or block.part.rels[rid].is_external:
                        raise ValueError('내부 그림 관계가 없습니다.')
                    data = block.part.related_parts[rid].blob
                    fmt, unused_size = _image(data)
                    extent = drawings[0].find(qn('wp:extent'))
                    if extent is None:
                        raise ValueError('그림 표시 크기가 없습니다.')
                    width, height = int(extent.get('cx')), int(extent.get('cy'))
                    if not 0 < width <= 100 * 914400 or not 0 < height <= 100 * 914400:
                        raise ValueError('그림 표시 크기가 안전 범위를 벗어났습니다.')
                    picture = out.add_picture(data, fmt, width=max(1, round(width / 127)), height=max(1, round(height / 127)))
                    # 공개 그림 API가 만든 개체를 원래 run 위치로 옮겨 본문 순서를 지킨다.
                    generated = picture.paragraph
                    for parent in generated.element.iter():
                        if picture.element in list(parent):
                            parent.remove(picture.element)
                            break
                    destination.add_run('').element.append(picture.element)
                    generated.section.element.remove(generated.element)
                else:
                    raise ValueError('지원하지 않는 DOCX run 제어입니다.')

    for block in doc.iter_inner_content():
        if isinstance(block, Paragraph):
            p = out.add_paragraph('', include_run=False)
            paragraph(block, p)
        elif isinstance(block, Table):
            rows, cols = len(block.rows), len(block.columns)
            if not rows or not cols or rows * cols > 100_000:
                raise ValueError('표 크기를 확인해 주세요.')
            table = out.add_table(rows, cols)
            for r, row in enumerate(block.rows):
                if len(row.cells) != cols:
                    raise ValueError('직사각형 표만 지원합니다.')
                for c, cell in enumerate(row.cells):
                    if cell.tables:
                        raise ValueError('중첩 표는 아직 지원하지 않습니다.')
                    table.set_cell_text(r, c, '')
                    target_cell = table.cell(r, c)
                    for index, p in enumerate(cell.paragraphs):
                        dest = target_cell.paragraphs[0] if index == 0 else target_cell.add_paragraph('')
                        paragraph(p, dest)
        else:
            raise ValueError('지원하지 않는 DOCX 본문 블록입니다.')
    return out


def convert_document(source: Path, target: str, output: Path) -> dict:
    source, output = require_regular(source), Path(output).absolute()
    extension = source.suffix.lower().lstrip('.')
    if extension not in NATIVE_INPUTS or target not in NATIVE_TARGETS or output.suffix != '.' + target:
        raise ValueError('새 저장 경로의 입력·출력 형식을 확인해 주세요.')
    if output.exists():
        raise FileExistsError('기존 결과를 덮어쓰지 않습니다.')
    if source == output or not output.parent.is_dir():
        raise ValueError('소유 출력 폴더가 필요합니다.')
    raw = bounded_read(source)
    source_hash = hashlib.sha256(raw).hexdigest()
    hwp_input_metadata = None
    from hwpx import HwpxDocument
    from hwpx.quality import QualityPolicy
    with tempfile.TemporaryDirectory(prefix='native-', dir=output.parent) as folder:
        owned = Path(folder)
        snapshot = owned / ('input.' + extension)
        snapshot.write_bytes(raw)
        if extension in {'hwpx', 'docx'}:
            parts = guard_package(snapshot)
            document_formats.validate_input(snapshot, extension)
            if extension == 'hwpx' and parts.get('mimetype', b'').strip() != b'application/hwp+zip':
                raise ValueError('실제 HWPX mimetype이 아닙니다.')
        elif extension == 'hwp':
            hwp_input_metadata = guard_hwp(raw)
            document_formats.validate_input(snapshot, extension)
        if extension == 'docx':
            document = _docx_document(snapshot, parts)
        elif extension == 'txt':
            text = raw.decode('utf-8-sig', errors='strict')
            document = HwpxDocument.new(inherit_style=False)
            for line in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
                document.add_paragraph(line)
        else:
            document = HwpxDocument.open(snapshot)
        loss = require_no_loss(document.conversion_report)
        policy = QualityPolicy(require_open_safety=True, require_reference_integrity=True,
            require_visual_complete=False, render_check='off', overflow_policy='fail',
            layout_lint='strict', xsd_mode='lint', preserve_unmodified_parts=True, allow_expert_unsafe=False)
        pending = owned / ('output.' + target)
        quality = require_quality(document.save_report(pending, quality=policy))
        result_raw = bounded_read(pending)
        if target == 'hwp':
            guard_hwp(result_raw)
        else:
            guard_package(pending)
        reopened = HwpxDocument.open(pending)
        require_no_loss(reopened.conversion_report)
        if hashlib.sha256(bounded_read(source)).hexdigest() != source_hash:
            raise ValueError('변환 중 원본이 변경되어 결과를 승격하지 않았습니다.')
        # Windows rename은 덮어쓰지 않는다. 다른 플랫폼에서도 기존 파일을 보존한다.
        with output.open('xb') as destination:
            try:
                destination.write(result_raw)
            except BaseException:
                destination.close()
                output.unlink()
                raise
        return {'version': 1, 'ok': True, 'format': target, 'source_sha256': source_hash,
                'output_sha256': hashlib.sha256(result_raw).hexdigest(), 'conversion_report': loss,
                'hwp_input_metadata': hwp_input_metadata,
                'quality': quality, 'render_checked': False, 'visual_complete': False,
                'visual_complete_status': 'unverified',
                'limitations': ['실험적 HWP5 저장·제한된 DOCX 문자/표/PNG/JPEG 매핑',
                    '원문 전체 배치·글꼴 보존과 시각 호환 미검증', '미리보기 등 파생 메타데이터는 재생성·생략될 수 있음']}
