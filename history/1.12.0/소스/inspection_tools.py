"""로컬 OCR 교정·실제 파일 비교·검토 후보와 비가역 픽셀 가림 도구."""
from __future__ import annotations

from collections import defaultdict
import csv
import difflib
import hashlib
import math
from pathlib import Path
import re
import tempfile

from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageStat
import pypdfium2 as pdfium
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

import engine
from pdf_lock import PDFIUM_LOCK
from pdf_tools import (PdfToolError, Request, check_cancel, image_ocr, pdf_text_pages,
                       preflight_output, publish, reader_for, source_context)


def _source(path):
    try:
        source = Path(path).resolve(strict=True)
        if not source.is_file():
            raise OSError('입력 파일이 아닙니다.')
        with source.open('rb') as stream:
            stream.read(1)
        return source
    except (OSError, TypeError, ValueError) as error:
        raise PdfToolError('input_files', str(error), source=str(path)) from error


def _output(directory):
    try:
        output = Path(directory).resolve(strict=True)
        if not output.is_dir():
            raise OSError('출력 폴더가 아닙니다.')
        return output
    except (OSError, TypeError, ValueError) as error:
        raise PdfToolError('output_write', str(error), source=str(directory)) from error


def _stem(value):
    if (not isinstance(value, str) or not value or len(value) > 160 or
            re.search(r'[<>:"/\\|?*\x00-\x1f]', value) or value[-1] in '. ' or
            value in {'.', '..'} or
            re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', value, re.I)):
        raise PdfToolError('output_name')
    return value


def _info(path, cancel=None):
    check_cancel(cancel)
    source = _source(path)
    with source_context(source):
        pages = []
        if source.suffix.lower() == '.pdf':
            reader = reader_for(source)
            for index, page in enumerate(reader.pages):
                check_cancel(cancel)
                box = page.cropbox
                width, height = float(box.width), float(box.height)
                if int(page.get('/Rotate', 0)) % 180:
                    width, height = height, width
                pages.append({'page': index, 'width': width, 'height': height, 'unit': 'pt'})
        else:
            with Image.open(source) as opened:
                for index in range(getattr(opened, 'n_frames', 1)):
                    check_cancel(cancel)
                    opened.seek(index)
                    image = ImageOps.exif_transpose(opened)
                    pages.append({'page': index, 'width': image.width, 'height': image.height, 'unit': 'px'})
        return {'path': str(source), 'bytes': source.stat().st_size,
                'page_count': len(pages), 'pages': pages}


def render_page(path, page=0, dpi=120):
    """독립 RGB 사본을 반환하고 PDFium 객체는 공용 잠금 안에서 모두 닫는다."""
    source = _source(path)
    if type(page) is not int or page < 0 or type(dpi) is not int or not 60 <= dpi <= 600:
        raise PdfToolError('page_range')
    with source_context(source):
        if source.suffix.lower() == '.pdf':
            reader_for(source)
            with PDFIUM_LOCK:
                document = pdfium.PdfDocument(str(source))
                try:
                    if page >= len(document):
                        raise PdfToolError('page_range')
                    item = document[page]
                    bitmap = None
                    try:
                        if item.get_width() * item.get_height() * (dpi / 72) ** 2 > 100_000_000:
                            raise PdfToolError('page_too_large')
                        bitmap = item.render(scale=dpi / 72)
                        return bitmap.to_pil().convert('RGB').copy()
                    finally:
                        if bitmap is not None:
                            bitmap.close()
                        item.close()
                finally:
                    document.close()
        with Image.open(source) as image:
            if page >= getattr(image, 'n_frames', 1):
                raise PdfToolError('page_range')
            image.seek(page)
            converted = ImageOps.exif_transpose(image).convert('RGBA')
            if converted.width * converted.height > 100_000_000:
                raise PdfToolError('page_too_large')
            background = Image.new('RGBA', converted.size, 'white')
            background.alpha_composite(converted)
            return background.convert('RGB')


def recognize_editable(path, language='kor+eng', cancel=None):
    """확신도는 실제 Tesseract TSV의 conf 값만 사용한다."""
    check_cancel(cancel)
    source = _source(path)
    if language not in {'kor+eng', 'kor', 'eng'}:
        raise PdfToolError('ocr_language')
    info = _info(source, cancel)
    words, pages = [], []
    with source_context(source), tempfile.TemporaryDirectory(prefix='.flipring-inspection-') as temporary:
        root = Path(temporary)
        for index in range(info['page_count']):
            check_cancel(cancel)
            work = root / f'page-{index}'
            work.mkdir()
            image = render_page(source, index, 200)
            raster = work / 'input.png'
            image.save(raster, dpi=(200, 200))
            width, height = image.size
            content, _ = image_ocr(raster, work, Request('recognize', [str(source)], ocr_language=language,
                                                       dpi=200), cancel, staged_data=root / 'tessdata')
            with (work / 'recognized.tsv').open(encoding='utf-8-sig', newline='') as stream:
                for row in csv.DictReader(stream, delimiter='\t'):
                    check_cancel(cancel)
                    value = row.get('text', '').strip()
                    if row.get('level') != '5' or not value:
                        continue
                    confidence = float(row['conf'])
                    if not math.isfinite(confidence) or not 0 <= confidence <= 100:
                        continue
                    x, y, w, h = (float(row[key]) for key in ('left', 'top', 'width', 'height'))
                    left, top = max(0, x / width), max(0, y / height)
                    right, bottom = min(1, (x + w) / width), min(1, (y + h) / height)
                    if right > left and bottom > top:
                        words.append({'text': value, 'confidence': confidence, 'page': index,
                                      'rect': [left, top, right - left, bottom - top]})
            pages.append({'page': index, 'width': width, 'height': height, 'unit': 'px', 'text': content.text})
    check_cancel(cancel)
    return {'text': '\n\f\n'.join(page['text'] for page in pages), 'words': words, 'pages': pages}


def export_edited_text(text, output_dir, stem, format='txt'):
    """교정 문자열은 번역하지 않으며 수식으로 실행하지 않는 새 문서로 저장한다."""
    if not isinstance(text, str) or any(ord(char) < 32 and char not in '\t\n\r\f' for char in text):
        raise PdfToolError('text_input')
    if format not in {'txt', 'pdf', 'docx', 'xlsx'}:
        raise PdfToolError('output_format')
    output, name = _output(output_dir), _stem(stem)
    preflight_output(output, len(text.encode('utf-8')) * 4 + 4 * 1024 * 1024)
    with tempfile.TemporaryDirectory(prefix='.flipring-edited-', dir=output) as temporary:
        destination = Path(temporary) / ('edited.' + format)
        with source_context(output):
            if format == 'txt':
                destination.write_text(text, encoding='utf-8')
            elif format == 'pdf':
                engine.write_text_pdf(text, destination)
            elif format == 'docx':
                from docx import Document
                document = Document()
                for page_index, page_text in enumerate(text.split('\f')):
                    if page_index:
                        document.add_page_break()
                    for line in page_text.split('\n'):
                        document.add_paragraph(line)
                document.save(destination)
            else:
                import xlsxwriter
                workbook = xlsxwriter.Workbook(str(destination), {'strings_to_formulas': False, 'strings_to_urls': False})
                try:
                    sheet = workbook.add_worksheet('Text')
                    sheet.set_column(0, 20, 26)
                    for row, line in enumerate(text.split('\n')):
                        for column, value in enumerate(line.split('\t')):
                            status = sheet.write_string(row, column, value)
                            if status:
                                raise PdfToolError('text_too_large', str(status))
                finally:
                    workbook.close()
            return publish(destination, output / name, 'edited')


def _native_or_ocr(path, cancel=None):
    source = _source(path)
    if source.suffix.lower() != '.pdf':
        return recognize_editable(source, cancel=cancel)
    contents = pdf_text_pages(source, cancel)
    # 스캔 페이지가 섞인 PDF도 빠뜨리지 않도록 없는 페이지만 실제 OCR로 보충한다.
    result = {'text': '', 'words': [], 'pages': []}
    ocr = None
    for index, content in enumerate(contents):
        check_cancel(cancel)
        if content.text.strip():
            result['pages'].append({'page': index, 'text': content.text})
            for word in content.words:
                result['words'].append({'text': word.text, 'page': index, 'confidence': None,
                                        'rect': [word.left / content.width, word.top / content.height,
                                                 (word.right - word.left) / content.width,
                                                 (word.bottom - word.top) / content.height]})
        else:
            # 빈 페이지는 먼저 픽셀을 확인해 불필요한 OCR을 피한다.
            raster = render_page(source, index, 120).convert('L')
            if raster.getextrema()[0] >= 245:
                result['pages'].append({'page': index, 'text': ''})
                continue
            if ocr is None:
                ocr = recognize_editable(source, cancel=cancel)
            result['pages'].append(ocr['pages'][index])
            result['words'].extend(w for w in ocr['words'] if w['page'] == index)
    result['text'] = '\n\f\n'.join(p['text'] for p in result['pages'])
    return result


def compare_files(left, right, cancel=None):
    check_cancel(cancel)
    infos = [_info(left, cancel), _info(right, cancel)]
    texts = [_native_or_ocr(path, cancel)['text'] for path in (left, right)]
    check_cancel(cancel)
    return {'left': infos[0], 'right': infos[1], 'text_equal': texts[0] == texts[1],
            'text_diff': '\n'.join(difflib.unified_diff(texts[0].splitlines(), texts[1].splitlines(),
                                                     fromfile=Path(left).name, tofile=Path(right).name, lineterm=''))}


def _privacy(words, pages=None):
    findings = []
    groups = defaultdict(list)
    for word in words:
        groups[word['page']].append(word)
    patterns = [('email', re.compile(r'[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}', re.I)),
                ('phone', re.compile(r'(?<!\d)(?:\+82[ \-]?)?0?1[016789][ \-]?\d{3,4}[ \-]?\d{4}(?!\d)'))]
    page_texts = {page['page']: page['text'] for page in (pages or [])}
    for page, values in groups.items():
        text, spans, cursor = page_texts.get(page, ''), [], 0
        if not text:
            text = ' '.join(word['text'] for word in values)
        for word in values:
            # PDF 글자 상자는 마침표·하이픈을 따로 나눌 수 있으므로 원문의 공백을 보존한다.
            start = text.find(word['text'], cursor)
            if start < 0:
                continue
            end = start + len(word['text'])
            spans.append((start, end, word['rect']))
            cursor = end
        for kind, pattern in patterns:
            for match in pattern.finditer(text):
                boxes = [box for start, end, box in spans if start < match.end() and end > match.start()]
                if not boxes:
                    continue
                x, y = min(b[0] for b in boxes), min(b[1] for b in boxes)
                right, bottom = max(b[0] + b[2] for b in boxes), max(b[1] + b[3] for b in boxes)
                findings.append({'kind': kind, 'page': page, 'rect': [x, y, right - x, bottom - y],
                                 'message': '이메일 검토 후보' if kind == 'email' else '전화번호 검토 후보'})
    return findings


def audit_file(path, cancel=None):
    check_cancel(cancel)
    source, findings, seen = _source(path), [], {}
    info = _info(source, cancel)
    for index in range(info['page_count']):
        check_cancel(cancel)
        image = render_page(source, index, 120)
        normalized = image.copy()
        normalized.thumbnail((900, 900))
        fingerprint = hashlib.sha256(str(image.size).encode() + normalized.tobytes()).hexdigest()
        if fingerprint in seen:
            findings.append({'kind': 'duplicate', 'page': index, 'score': 1.0,
                             'message': f'동일 렌더 페이지 후보 · {seen[fingerprint] + 1}',
                             'duplicate_of': seen[fingerprint]})
        else:
            seen[fingerprint] = index
        gray = normalized.convert('L')
        histogram = gray.histogram()
        ink_fraction = sum(histogram[:245]) / (gray.width * gray.height)
        if ink_fraction < 0.0005:
            findings.append({'kind': 'blank', 'page': index, 'score': 1 - ink_fraction,
                             'message': '빈 페이지 검토 후보'})
            continue
        if min(gray.size) > 10:
            center = gray.crop((2, 2, gray.width - 2, gray.height - 2))
            laplacian = center.filter(ImageFilter.Kernel((3, 3), (0, 1, 0, 1, -4, 1, 0, 1, 0), 1, 128))
            # Pillow가 계산하지 않고 남기는 바깥 1픽셀을 제외한 유효 응답만 측정한다.
            response = laplacian.crop((1, 1, laplacian.width - 1, laplacian.height - 1))
            score = float(ImageStat.Stat(response).var[0])
            if score < 25:
                findings.append({'kind': 'blur', 'page': index, 'score': score,
                                 'message': '낮은 가장자리 선명도 · 흐림 검토 후보'})
        bands = ([0, 0, 1, 0.015], [0, 0.985, 1, 0.015], [0, 0, 0.015, 1], [0.985, 0, 0.015, 1])
        for rect in bands:
            x, y, w, h = rect
            strip = gray.crop((int(x * gray.width), int(y * gray.height),
                               max(int((x + w) * gray.width), int(x * gray.width) + 1),
                               max(int((y + h) * gray.height), int(y * gray.height) + 1)))
            fraction = sum(strip.histogram()[:150]) / max(1, strip.width * strip.height)
            if fraction > 0.01:
                findings.append({'kind': 'edge', 'page': index, 'rect': rect, 'score': fraction,
                                 'message': '가장자리 내용 · 잘림 검토 후보'})
    content = _native_or_ocr(source, cancel)
    findings.extend(_privacy(content['words'], content['pages']))
    check_cancel(cancel)
    return findings


def _rectangles(values, count):
    if not isinstance(values, (list, tuple)) or not values:
        raise PdfToolError('redaction_rect')
    result = defaultdict(list)
    for value in values:
        if not isinstance(value, dict) or set(value) != {'page', 'rect'}:
            raise PdfToolError('redaction_rect')
        page, rect = value['page'], value['rect']
        if type(page) is not int or not 0 <= page < count or not isinstance(rect, (tuple, list)) or len(rect) != 4:
            raise PdfToolError('redaction_rect')
        if any(type(n) not in (int, float) or not math.isfinite(n) for n in rect):
            raise PdfToolError('redaction_rect')
        x, y, width, height = rect
        if not (0 <= x < 1 and 0 <= y < 1 and width > 0 and height > 0 and x + width <= 1 and y + height <= 1):
            raise PdfToolError('redaction_rect')
        result[page].append(tuple(rect))
    return result


def redact_file(path, rectangles, output_dir, cancel=None):
    """원본 객체를 복사하지 않고 모든 페이지를 래스터화하여 새 결과만 만든다."""
    check_cancel(cancel)
    source, output = _source(path), _output(output_dir)
    info = _info(source, cancel)
    selections = _rectangles(rectangles, info['page_count'])
    preflight_output(output, source.stat().st_size * 8 + 64 * 1024 * 1024, cancel)
    is_pdf = source.suffix.lower() == '.pdf'
    # 여러 프레임은 손실 없이 TIFF로 보존하고 단일 이미지는 PNG로 저장한다.
    extension = '.pdf' if is_pdf else '.tiff' if info['page_count'] > 1 else '.png'
    with source_context(source), tempfile.TemporaryDirectory(prefix='.flipring-redact-', dir=output) as temporary:
        destination = Path(temporary) / ('redacted' + extension)
        document = canvas.Canvas(str(destination)) if is_pdf else None
        images = []
        for index, metadata in enumerate(info['pages']):
            check_cancel(cancel)
            image = render_page(source, index, 200)
            draw = ImageDraw.Draw(image)
            for x, y, width, height in selections[index]:
                left, top = math.floor(x * image.width), math.floor(y * image.height)
                right = min(image.width, math.ceil((x + width) * image.width))
                bottom = min(image.height, math.ceil((y + height) * image.height))
                draw.rectangle((left, top, right - 1, bottom - 1), fill=(0, 0, 0))
            if document is not None:
                size = (metadata['width'], metadata['height'])
                document.setPageSize(size)
                document.drawImage(ImageReader(image), 0, 0, *size)
                document.showPage()
            else:
                images.append(image)
        check_cancel(cancel)
        if document is not None:
            document.save()
            if any((page.extract_text() or '').strip() for page in reader_for(destination).pages):
                raise PdfToolError('redaction_text_remaining')
        elif len(images) > 1:
            images[0].save(destination, save_all=True, append_images=images[1:], compression='tiff_deflate')
        else:
            images[0].save(destination)
        check_cancel(cancel)
        return publish(destination, output / source.stem, 'redacted', cancel)
