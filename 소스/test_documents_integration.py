"""합성 자료만 사용해 실제 LibreOffice의 문서·구엑셀 변환을 확인한다."""
from pathlib import Path
import hashlib
import tempfile
import threading
import unittest

from docx import Document
from openpyxl import Workbook, load_workbook
from pptx import Presentation

import engine


class ActualDocumentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="fr-docs110-")
        self.root = Path(self.temporary.name)
        self.originals = {}

    def tearDown(self):
        for path, digest in self.originals.items():
            self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest(), str(path))
        self.temporary.cleanup()

    def keep(self, path):
        self.originals[path] = hashlib.sha256(path.read_bytes()).hexdigest()
        return path

    def word(self):
        path = self.root / "한글 문서.docx"
        document = Document()
        document.add_heading("플립링 대표 문서", 0)
        document.add_paragraph("원본 보존 · 한글 Word 97 시험 · PUVKID")
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "품목"
        table.cell(1, 0).text = "시험표"
        table.cell(1, 1).text = "123.5"
        document.save(path)
        return self.keep(path)

    def workbook(self):
        path = self.root / "구엑셀 다중 시트.xlsx"
        book = Workbook()
        book.active.title = "첫째 한글"
        book.active.append(["한글 값", "소수", "수식"])
        book.active.append([12, 3.5, "=A2+B2"])
        book.create_sheet("두번째 시트").append(["다른 시트 보존", 9876, "=2*3"])
        book.save(path)
        return self.keep(path)

    def presentation(self):
        path = self.root / "파워포인트.pptx"
        deck = Presentation()
        for index in range(2):
            slide = deck.slides.add_slide(deck.slide_layouts[1])
            slide.shapes.title.text = f"발표 {index + 1} · PUVKID"
            slide.placeholders[1].text = "한글 발표 내용 보존"
        deck.save(path)
        return self.keep(path)

    def test_01_word97_roundtrip_preserves_korean_and_table(self):
        source = self.word()
        legacy = Path(engine.convert(source, "doc"))
        self.keep(legacy)
        self.assertTrue(legacy.read_bytes().startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"))
        returned = Path(engine.convert(legacy, "docx"))
        document = Document(returned)
        self.assertIn("한글 Word 97 시험", "\n".join(p.text for p in document.paragraphs))
        self.assertEqual("시험표", document.tables[0].cell(1, 0).text)
        self.assertEqual("123.5", document.tables[0].cell(1, 1).text)

    def test_02_excel97_roundtrip_preserves_two_sheets_cells_and_formulas(self):
        source = self.workbook()
        legacy = Path(engine.convert(source, "xls"))
        self.keep(legacy)
        self.assertTrue(legacy.read_bytes().startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"))
        returned = Path(engine.convert(legacy, "xlsx"))
        book = load_workbook(returned, data_only=False)
        self.assertEqual(["첫째 한글", "두번째 시트"], book.sheetnames)
        self.assertEqual("한글 값", book.worksheets[0]["A1"].value)
        self.assertEqual(12, book.worksheets[0]["A2"].value)
        self.assertEqual(3.5, book.worksheets[0]["B2"].value)
        self.assertEqual("=A2+B2", book.worksheets[0]["C2"].value)
        self.assertEqual("다른 시트 보존", book.worksheets[1]["A1"].value)
        self.assertEqual("=2*3", book.worksheets[1]["C1"].value)
        book.close()

    def test_03_powerpoint97_roundtrip_preserves_two_slides_and_text(self):
        source = self.presentation()
        legacy = Path(engine.convert(source, "ppt"))
        self.keep(legacy)
        returned = Path(engine.convert(legacy, "pptx"))
        deck = Presentation(returned)
        self.assertEqual(2, len(deck.slides))
        self.assertIn("발표 1", "\n".join(s.text for s in deck.slides[0].shapes if s.has_text_frame))
        plain = Path(engine.convert(legacy, "txt")).read_text(encoding="utf-8")
        self.assertIn("발표 2", plain)
        self.assertIn("한글 발표 내용 보존", plain)

    def test_04_writer_pdf_has_real_text_and_raster_output(self):
        source = self.word()
        pdf = Path(engine.convert(source, "pdf"))
        with engine.pdfium.PdfDocument(str(pdf)) as document:
            self.assertGreater(len(document), 0)
            page = document[0]
            text_page = page.get_textpage()
            try:
                self.assertIn("PUVKID", text_page.get_text_range())
            finally:
                text_page.close()
                page.close()
        png = Path(engine.convert(source, "png"))
        with engine.Image.open(png) as image:
            self.assertGreater(image.width, 200)
            self.assertGreater(image.height, 200)

    def test_05_ods_preserves_all_sheets_and_csv_exports_first_sheet(self):
        source = self.workbook()
        ods = Path(engine.convert(source, "ods"))
        back = Path(engine.convert(ods, "xlsx"))
        book = load_workbook(back)
        self.assertEqual(2, len(book.worksheets))
        self.assertEqual(9876, book.worksheets[1]["B1"].value)
        book.close()
        csv = Path(engine.convert(source, "csv")).read_text(encoding="utf-8-sig")
        self.assertIn("한글 값", csv)
        self.assertNotIn("다른 시트 보존", csv)

    def test_06_broken_or_renamed_documents_never_publish_output(self):
        for suffix in ("docx", "xls", "hwpx", "rtf", "pptx"):
            with self.subTest(suffix=suffix):
                path = self.root / ("손상." + suffix)
                path.write_bytes(b"not a real document")
                self.keep(path)
                before = set(self.root.iterdir())
                with self.assertRaises((ValueError, RuntimeError)):
                    engine.convert(path, "pdf")
                self.assertEqual(before, set(self.root.iterdir()))

    def test_07_cancel_during_actual_office_keeps_original(self):
        source = self.word()
        event = threading.Event()
        timer = threading.Timer(0.3, event.set)
        timer.start()
        try:
            with self.assertRaises(engine.Cancelled):
                engine.convert(source, "doc", cancel=event)
        finally:
            timer.cancel()
            timer.join()
        self.assertEqual([source], list(self.root.iterdir()))


if __name__ == "__main__":
    unittest.main()
