"""실제 파일의 선택 제거·원본·본문·충돌·취소 및 대화상자 계약 검사."""
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile
import struct

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PIL import Image, PngImagePlugin
from docx import Document
from pypdf import PdfWriter, PdfReader
from pypdf.generic import (NameObject, DecodedStreamObject, DictionaryObject,
                           ArrayObject, TextStringObject, NumberObject)
from reportlab.pdfgen import canvas
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt

import delivery_tools as tools
from pdf_tools import Cancelled, PdfToolError


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def docx(self):
        source = self.root / '원본.docx'
        document = Document()
        document.add_paragraph('본문 보존 Actual body')
        document.core_properties.author = 'private author'
        document.core_properties.title = 'keep title'
        document.save(source)
        return source

    def test_docx_selected_preserves_parts_and_collision(self):
        source = self.docx()
        before = source.read_bytes()
        report = tools.metadata_report(source)
        key = next(e['key'] for e in report['entries'] if e['label'] == 'creator')
        first = Path(tools.strip_metadata(source, [key], self.root))
        second = Path(tools.strip_metadata(source, [key], self.root))
        self.assertNotEqual(first, second)
        self.assertEqual(before, source.read_bytes())
        self.assertEqual(Document(first).core_properties.title, 'keep title')
        self.assertEqual(Document(first).core_properties.author, '')
        self.assertEqual(Document(first).paragraphs[0].text, '본문 보존 Actual body')
        with zipfile.ZipFile(source) as left, zipfile.ZipFile(first) as right:
            for name in left.namelist():
                if name != 'docProps/core.xml':
                    self.assertEqual(left.read(name), right.read(name), name)

    def test_pdf_selected_preserves_content_attachment_annotation_xmp(self):
        source = self.root / '원본.pdf'
        c = canvas.Canvas(str(source))
        c.drawString(50, 700, 'Actual body')
        c.save()
        reader = PdfReader(source)
        writer = PdfWriter()
        writer.clone_document_from_reader(reader)
        writer.add_metadata({'/Author': 'private', '/Title': 'keep'})
        writer.add_attachment('keep.txt', b'attachment bytes')
        annotation = DictionaryObject({NameObject('/Type'): NameObject('/Annot'),
                                       NameObject('/Subtype'): NameObject('/Text'),
                                       NameObject('/Rect'): ArrayObject([NumberObject(x) for x in [0, 0, 20, 20]]),
                                       NameObject('/Contents'): TextStringObject('keep comment')})
        writer.pages[0][NameObject('/Annots')] = ArrayObject([writer._add_object(annotation)])
        xmp = DecodedStreamObject()
        xmp.set_data(b'<x:xmpmeta xmlns:x="adobe:ns:meta/">private xmp</x:xmpmeta>')
        writer._root_object[NameObject('/Metadata')] = writer._add_object(xmp)
        other = self.root / 'prepared.pdf'
        writer.write(other)
        writer.close()
        reader.close()
        source.write_bytes(other.read_bytes())
        before = source.read_bytes()
        result = Path(tools.strip_metadata(source, ['pdf:/Author', 'pdf:xmp'], self.root))
        with PdfReader(result) as cleaned:
            self.assertNotIn('/Author', cleaned.metadata)
            self.assertEqual(cleaned.metadata.title, 'keep')
            self.assertNotIn('/Metadata', cleaned.trailer['/Root'])
            self.assertEqual(cleaned.attachments['keep.txt'][0], b'attachment bytes')
            self.assertEqual(cleaned.pages[0]['/Annots'][0].get_object()['/Contents'], 'keep comment')
            self.assertIn('Actual body', cleaned.pages[0].extract_text())
        self.assertEqual(before, source.read_bytes())

    def test_jpeg_exif_selected_preserves_encoded_pixels(self):
        source = self.root / '원본.jpg'
        exif = Image.Exif()
        exif[315], exif[270] = 'private artist', 'keep description'
        exif[34853] = {1: 'N', 2: (1.0, 2.0, 3.0)}
        Image.new('RGB', (32, 32), 'red').save(source, exif=exif)
        before = source.read_bytes()
        keys = {e['key'] for e in tools.metadata_report(source)['entries']}
        self.assertIn('exif:34853', keys)
        result = Path(tools.strip_metadata(source, ['exif:315', 'exif:34853'], self.root))
        with Image.open(result) as image:
            self.assertNotIn(315, image.getexif())
            self.assertNotIn(34853, image.getexif())
            self.assertEqual(image.getexif()[270], 'keep description')
        def pixels(raw):
            return next(segment for marker, segment in tools._jpeg_segments(raw) if marker == 0xDA)
        self.assertEqual(pixels(before), pixels(result.read_bytes()))
        self.assertEqual(before, source.read_bytes())

    def test_png_text_and_exif_preserve_idat(self):
        source = self.root / '원본.png'
        exif = Image.Exif()
        exif[315], exif[270] = 'artist', 'keep'
        info = PngImagePlugin.PngInfo()
        info.add_text('Author', 'private')
        info.add_text('Title', 'keep title')
        Image.new('RGB', (20, 20), 'blue').save(source, exif=exif, pnginfo=info)
        report = tools.metadata_report(source)
        text_key = next(e['key'] for e in report['entries'] if e['label'] == 'tEXt: Author')
        result = Path(tools.strip_metadata(source, [text_key, 'exif:315'], self.root))
        with Image.open(result) as image:
            self.assertNotIn('Author', image.info)
            self.assertEqual(image.info['Title'], 'keep title')
            self.assertEqual(image.getexif()[270], 'keep')
            self.assertNotIn(315, image.getexif())
        def idat(path):
            return [raw for kind, _, raw in tools._png_chunks(path.read_bytes()) if kind == b'IDAT']
        self.assertEqual(idat(source), idat(result))

    def test_jpeg_padded_exif_preserves_unselected_segments_and_scan(self):
        source = self.root / '채움바이트.jpg'
        exif = Image.Exif()
        exif[315], exif[270] = 'private artist', 'keep description'
        Image.new('RGB', (24, 24), 'red').save(source, exif=exif)
        raw = source.read_bytes()
        marker = raw.index(b'\xff\xe1')
        # EXIF 앞의 실제 FF 채움 바이트 때문에 payload 시작은 고정 4가 아니다.
        source.write_bytes(raw[:marker] + b'\xff' + raw[marker:])
        before = source.read_bytes()
        report = tools.metadata_report(source)
        self.assertEqual({entry['key'] for entry in report['entries']}, {'exif:270', 'exif:315'})
        result = Path(tools.strip_metadata(source, ['exif:315'], self.root))
        with Image.open(result) as image:
            self.assertNotIn(315, image.getexif())
            self.assertEqual(image.getexif()[270], 'keep description')
        self.assertEqual(before[before.index(b'\xff\xda'):],
                         result.read_bytes()[result.read_bytes().index(b'\xff\xda'):])
        self.assertEqual(before, source.read_bytes())

    def test_jpeg_selected_comment_preserves_following_reindexed_comment(self):
        source = self.root / '주석.jpg'
        Image.new('RGB', (24, 24), 'blue').save(source)
        original = source.read_bytes()
        def comment(value):
            return b'\xff\xff\xfe' + struct.pack('>H', len(value) + 2) + value
        private, keep = comment(b'private comment'), comment(b'keep comment')
        source.write_bytes(original[:2] + private + keep + original[2:])
        before = source.read_bytes()
        key = next(entry['key'] for entry in tools.metadata_report(source)['entries']
                   if 'private comment' in entry['value'])
        result = Path(tools.strip_metadata(source, [key], self.root))
        self.assertEqual(result.read_bytes(), original[:2] + keep + original[2:])
        self.assertEqual(before, source.read_bytes())

    def test_selected_metadata_residue_is_rejected_for_all_supported_branches(self):
        document = self.docx()
        pdf = self.root / '사후검증.pdf'
        writer = PdfWriter()
        writer.add_blank_page(80, 80)
        writer.add_metadata({'/Author': 'private'})
        writer.write(pdf)
        writer.close()
        jpeg, png = self.root / '사후검증.jpg', self.root / '사후검증.png'
        exif = Image.Exif()
        exif[315] = 'private artist'
        for path in (jpeg, png):
            Image.new('RGB', (20, 20), 'blue').save(path, exif=exif)
        cases = [(document, next(entry['key'] for entry in tools.metadata_report(document)['entries']
                                 if entry['label'] == 'creator')),
                 (pdf, 'pdf:/Author'), (jpeg, 'exif:315'), (png, 'exif:315')]
        for source, key in cases:
            with self.subTest(extension=source.suffix):
                before, listing = source.read_bytes(), set(self.root.iterdir())
                actual_report = tools.metadata_report
                def report_with_residue(path, cancel=None):
                    # 발행 직전 사본에 선택 속성이 실제로 남은 결함을 주입한다.
                    if Path(path) != source:
                        Path(path).write_bytes(before)
                    return actual_report(path, cancel)
                with patch.object(tools, 'metadata_report', side_effect=report_with_residue):
                    with self.assertRaisesRegex(PdfToolError, '메타데이터'):
                        tools.strip_metadata(source, [key], self.root)
                self.assertEqual(source.read_bytes(), before)
                self.assertEqual(set(self.root.iterdir()), listing)

    def test_indexed_metadata_verification_checks_beyond_display_limit(self):
        common = 'same value ' * 500
        for extension in ('jpg', 'png'):
            with self.subTest(extension=extension):
                source = self.root / ('긴메타데이터.' + extension)
                if extension == 'jpg':
                    Image.new('RGB', (20, 20), 'blue').save(source)
                    original = source.read_bytes()
                    def comment(text):
                        data = text.encode('ascii')
                        return b'\xff\xfe' + struct.pack('>H', len(data) + 2) + data
                    private, keep = comment(common + 'private'), comment(common + 'keep')
                    source.write_bytes(original[:2] + private + keep + original[2:])
                    wrong_copy = original[:2] + private + original[2:]
                else:
                    info = PngImagePlugin.PngInfo()
                    info.add_text('Author', common + 'private')
                    info.add_text('Author', common + 'keep')
                    Image.new('RGB', (20, 20), 'blue').save(source, pnginfo=info)
                    # 같은 표시값의 두 청크 중 선택하지 않은 뒤쪽 청크만 지운 잘못된 사본이다.
                    chunks = list(tools._png_chunks(source.read_bytes()))
                    last_text = max(index for index, (kind, _, _) in enumerate(chunks) if kind == b'tEXt')
                    wrong_copy = source.read_bytes()[:8] + b''.join(
                        chunk for index, (_, _, chunk) in enumerate(chunks) if index != last_text)
                entries = tools.metadata_report(source)['entries']
                self.assertEqual(len(entries), 2)
                self.assertEqual(entries[0]['value'], entries[1]['value'])
                before, listing = source.read_bytes(), set(self.root.iterdir())
                actual_report = tools.metadata_report
                def report_with_wrong_copy(path, cancel=None):
                    if Path(path) != source:
                        Path(path).write_bytes(wrong_copy)
                    return actual_report(path, cancel)
                with patch.object(tools, 'metadata_report', side_effect=report_with_wrong_copy):
                    with self.assertRaisesRegex(PdfToolError, '메타데이터'):
                        tools.strip_metadata(source, [entries[0]['key']], self.root)
                self.assertEqual(source.read_bytes(), before)
                self.assertEqual(set(self.root.iterdir()), listing)

    def test_cancel_unsupported_invalid_selection_no_new_file(self):
        source = self.docx()
        before = sorted(self.root.iterdir())
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            tools.strip_metadata(source, ['invalid'], self.root, cancel)
        with self.assertRaises(tools.DeliveryError):
            tools.strip_metadata(source, ['invalid'], self.root)
        unsupported = self.root / '원본.txt'
        unsupported.write_text('private', encoding='utf-8')
        self.assertFalse(tools.metadata_report(unsupported)['supported'])
        with self.assertRaises(tools.DeliveryError):
            tools.strip_metadata(unsupported, ['whatever'], self.root)
        self.assertEqual(sorted(self.root.iterdir()), sorted(before + [unsupported]))

    def test_compatibility_real_xml_and_dtd_rejection(self):
        source = self.docx()
        with zipfile.ZipFile(source, 'a') as archive:
            archive.writestr('word/vbaProject.bin', b'macro evidence')
            archive.writestr('word/extra.xml', b'<root xmlns:w="urn:w"><w:rFonts w:ascii="MyFont"/><f>1+1</f><Relationship TargetMode="External" Target="https://example.com"/></root>')
        result = tools.compatibility_report(source, 'pdf')
        self.assertTrue(result['macros'])
        self.assertEqual(result['formulas'], 1)
        self.assertIn('MyFont', result['fonts'])
        self.assertGreaterEqual(result['external_links'], 1)
        self.assertTrue(result['local_only'])
        with zipfile.ZipFile(source, 'a') as archive:
            archive.writestr('bad.xml', b'<!DOCTYPE root [<!ENTITY x "evil">]><root>&x;</root>')
        with self.assertRaises(ValueError):
            tools.compatibility_report(source, 'pdf')

    def test_compare_actual_text_documents_renders_and_cleans(self):
        left, right = self.root / 'left.txt', self.root / 'right.txt'
        left.write_text('Actual alpha', encoding='utf-8')
        right.write_text('Actual beta', encoding='utf-8')
        before = {path: path.read_bytes() for path in (left, right)}
        result = tools.compare_documents(left, right)
        self.assertFalse(result['text_equal'])
        self.assertIn('Actual alpha', result['text_diff'])
        self.assertEqual(len(result['images']), 2)
        self.assertGreater(result['images'][0].width, 0)
        self.assertEqual(set(self.root.iterdir()), {left, right})
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data)

    def test_compare_multiframe_images_retains_each_page_and_original(self):
        for extension in ('tiff', 'gif'):
            with self.subTest(extension=extension):
                source = self.root / ('여러프레임.' + extension)
                Image.new('RGB', (24, 18), 'white').save(
                    source, save_all=True, append_images=[Image.new('RGB', (24, 18), 'black')])
                before, listing = source.read_bytes(), set(self.root.iterdir())
                result = tools.compare_documents(source, source, page=1)
                self.assertEqual(result['left']['page_count'], 2)
                self.assertEqual(result['right']['page_count'], 2)
                self.assertEqual(result['images'][0].size, (24, 18))
                self.assertEqual(result['images'][0].getpixel((0, 0)), (0, 0, 0))
                self.assertEqual(result['images'][1].tobytes(), result['images'][0].tobytes())
                self.assertEqual(source.read_bytes(), before)
                self.assertEqual(set(self.root.iterdir()), listing)


class DeliveryUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_language_theme_thread_cancel_reuse(self):
        from delivery_ui import DeliveryDialog
        from theme_manager import manager
        owner = QWidget()
        owner.pending = 0
        owner.work_busy = lambda: False
        dialog = DeliveryDialog(owner)
        dialog.set_language('en')
        self.assertEqual(dialog.compare_button.text(), 'Compare documents')
        manager().apply('dark')
        self.assertTrue(self.app.property('flipringDarkTheme'))
        def operation(cancel):
            cancel.wait(2)
            from pdf_tools import check_cancel
            check_cancel(cancel)
        dialog._start(operation, 'metadata')
        self.assertTrue(dialog.is_busy())
        self.assertEqual(owner.pending, 1)
        dialog.reject()
        for _ in range(100):
            self.app.processEvents()
            if not dialog.is_busy():
                break
            QTest.qWait(10)
        self.assertFalse(dialog.is_busy())
        self.assertEqual(owner.pending, 0)
        dialog.show()
        self.assertTrue(dialog.isVisible())
        self.assertFalse(dialog._closing)
        dialog.close()
        manager().apply('light')
        owner.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
