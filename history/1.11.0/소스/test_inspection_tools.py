"""실제 OCR·교정 출력·위치 후보·내용 가림과 창 수명을 검사한다."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest

from PIL import Image, ImageDraw, ImageFont, ImageFilter
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from docx import Document
from openpyxl import load_workbook

import inspection_tools as tools
from pdf_tools import Cancelled, PdfToolError


class InspectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        location = Path(__file__).resolve().parent.parent / 'work' / 'expansion-inspection'
        location.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(prefix='real-files-', dir=location)
        cls.root = Path(cls.temporary.name)
        cls.pdf = cls.root / '원본.pdf'
        pdf = canvas.Canvas(str(cls.pdf), pagesize=(400, 500))
        pdf.drawString(40, 420, 'SECRET alice@example.com 010-1234-5678')
        pdf.showPage()
        pdf.showPage()
        pdf.showPage()
        pdf.save()
        cls.other = cls.root / '비교.pdf'
        pdf = canvas.Canvas(str(cls.other), pagesize=(400, 500))
        pdf.drawString(40, 420, 'CHANGED TEXT')
        pdf.showPage()
        pdf.save()
        cls.image = cls.root / '한영스캔.png'
        image = Image.new('RGB', (1600, 650), 'white')
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(str(Path(__file__).resolve().parent / 'assets/NanumGothicBold.ttf'), 62)
        draw.text((80, 90), '한글 문서 검사', font=font, fill='black')
        draw.text((80, 220), 'FlipRing OCR 2026', font=font, fill='black')
        image.save(cls.image, dpi=(200, 200))
        cls.originals = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (cls.pdf, cls.other, cls.image)}

    @classmethod
    def tearDownClass(cls):
        for path, expected in cls.originals.items():
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise AssertionError('원본 변경: ' + str(path))
        cls.temporary.cleanup()

    def test_01_real_ocr_confidence_and_rectangles(self):
        result = tools.recognize_editable(self.image)
        self.assertIn('한글', result['text'])
        self.assertIn('FlipRing', result['text'])
        self.assertTrue(result['words'])
        self.assertEqual(len(result['pages']), 1)
        for word in result['words']:
            self.assertIsInstance(word['confidence'], float)
            self.assertTrue(0 <= word['confidence'] <= 100)
            x, y, width, height = word['rect']
            self.assertTrue(0 <= x < x + width <= 1.000001)
            self.assertTrue(0 <= y < y + height <= 1.000001)
            self.assertEqual(word['page'], 0)

    def test_02_korean_exports_and_safe_duplicate(self):
        content = '한글 교정 내용\n=1+2\t전자 우편'
        paths = [Path(tools.export_edited_text(content, self.root, '교정', kind))
                 for kind in ('txt', 'pdf', 'docx', 'xlsx')]
        self.assertEqual(paths[0].read_text(encoding='utf-8'), content)
        paged = tools.export_edited_text('첫째 페이지\n\f\n둘째 페이지', self.root, '다중페이지', 'docx')
        paragraphs = Document(paged).paragraphs
        self.assertIn('첫째 페이지', '\n'.join(p.text for p in paragraphs))
        self.assertIn('둘째 페이지', '\n'.join(p.text for p in paragraphs))
        self.assertIn('w:type="page"', Document(paged)._element.xml)
        self.assertIn('한글 교정 내용', PdfReader(paths[1]).pages[0].extract_text())
        self.assertIn('한글 교정 내용', '\n'.join(p.text for p in Document(paths[2]).paragraphs))
        book = load_workbook(paths[3], data_only=False)
        self.assertEqual(book.active['A2'].value, '=1+2')
        self.assertEqual(book.active['A2'].data_type, 's')
        book.close()
        again = Path(tools.export_edited_text('두번째', self.root, '교정'))
        self.assertNotEqual(paths[0], again)
        self.assertEqual(paths[0].read_text(encoding='utf-8'), content)

    def test_03_render_compare_real_metadata(self):
        result = tools.compare_files(self.pdf, self.other)
        self.assertEqual(result['left']['page_count'], 3)
        self.assertEqual(result['left']['bytes'], self.pdf.stat().st_size)
        self.assertEqual(result['left']['pages'][0]['width'], 400)
        self.assertIn('SECRET', result['text_diff'])
        self.assertIn('CHANGED', result['text_diff'])
        self.assertFalse(result['text_equal'])
        self.assertTrue(tools.compare_files(self.image, self.image)['text_equal'])
        image = tools.render_page(self.pdf, 0, 144)
        self.assertEqual(image.mode, 'RGB')
        self.assertEqual(image.size, (800, 1000))
        with self.assertRaises(PdfToolError):
            tools.render_page(self.pdf, 3)

    def test_04_pdf_redaction_removes_original_text_and_pixels(self):
        rectangles = [{'page': 0, 'rect': [0, 0, 1, 0.3]}]
        output = Path(tools.redact_file(self.pdf, rectangles, self.root))
        self.assertNotEqual(output, self.pdf)
        pdf = PdfReader(output)
        self.assertEqual(len(pdf.pages), 3)
        self.assertNotIn('SECRET', ''.join(p.extract_text() or '' for p in pdf.pages))
        raster = tools.render_page(output, dpi=144)
        self.assertEqual(raster.getpixel((200, 100)), (0, 0, 0))
        self.assertEqual(raster.getpixel((200, 700)), (255, 255, 255))
        second = tools.redact_file(self.pdf, rectangles, self.root)
        self.assertNotEqual(str(output), second)

    def test_05_image_redaction_preserves_dimensions(self):
        output = tools.redact_file(self.image, [{'page': 0, 'rect': [0, 0, 1, 0.5]}], self.root)
        with Image.open(output) as image:
            self.assertEqual(image.size, (1600, 650))
            self.assertEqual(image.convert('RGB').getpixel((100, 100)), (0, 0, 0))

    def test_06_invalid_rectangle_boundary_is_atomic(self):
        bad = [[-0.1, 0, 0.1, 0.1], [0, 0, 0, 1], [0.9, 0, 0.2, 1],
               [float('nan'), 0, 1, 1], [True, 0, 1, 1], [0, 0, 1], 'bad']
        before = set(self.root.iterdir())
        for rect in bad:
            with self.subTest(rect=rect), self.assertRaises(PdfToolError):
                tools.redact_file(self.pdf, [{'page': 0, 'rect': rect}], self.root)
        for page in (-1, 3, True, '0'):
            with self.subTest(page=page), self.assertRaises(PdfToolError):
                tools.redact_file(self.pdf, [{'page': page, 'rect': [0, 0, 1, 1]}], self.root)
        with self.assertRaises(PdfToolError):
            tools.redact_file(self.pdf, [], self.root)
        self.assertEqual(set(self.root.iterdir()), before)

    def test_07_cancelled_and_damaged_inputs(self):
        event = threading.Event()
        event.set()
        for function, args in ((tools.recognize_editable, (self.image,)),
                               (tools.audit_file, (self.pdf,)),
                               (tools.compare_files, (self.pdf, self.other)),
                               (tools.redact_file, (self.pdf, [{'page': 0, 'rect': [0, 0, 1, 1]}], self.root))):
            with self.subTest(function=function.__name__), self.assertRaises(Cancelled):
                function(*args, cancel=event)
        damaged = self.root / '손상.pdf'
        damaged.write_bytes(b'not a PDF')
        for function in (tools.render_page, tools.recognize_editable, tools.audit_file):
            with self.subTest(function=function.__name__), self.assertRaises(PdfToolError):
                function(damaged)

    def test_08_audit_located_candidates_and_duplicates(self):
        findings = tools.audit_file(self.pdf)
        kinds = {f['kind'] for f in findings}
        self.assertIn('blank', kinds)
        self.assertIn('duplicate', kinds)
        self.assertIn('email', kinds)
        self.assertIn('phone', kinds)
        for finding in findings:
            self.assertIn('page', finding)
            self.assertIn('message', finding)
        self.assertTrue(all('rect' in f for f in findings if f['kind'] in ('email', 'phone')))

    def test_09_export_path_and_format_validation(self):
        for stem in ('../escape', 'C:/escape', 'CON', 'NUL.txt', '', 'name.', 'bad\x00name'):
            with self.subTest(stem=stem), self.assertRaises(PdfToolError):
                tools.export_edited_text('내용', self.root, stem)
        with self.assertRaises(PdfToolError):
            tools.export_edited_text('내용', self.root, '정상', 'exe')
        with self.assertRaises(PdfToolError):
            tools.export_edited_text('내용', self.root / 'missing', '정상')

    def test_09b_real_blur_edge_and_multiframe_preservation(self):
        image = Image.new('RGB', (700, 600), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 100, 180, 400), fill='black')
        blurred = image.filter(ImageFilter.GaussianBlur(18))
        path = self.root / '흐림가장자리.png'
        blurred.save(path)
        findings = tools.audit_file(path)
        self.assertIn('blur', {f['kind'] for f in findings})
        self.assertTrue(any(f['kind'] == 'edge' and f['rect'][0] == 0 for f in findings))
        multi = self.root / '여러프레임.tiff'
        image.save(multi, save_all=True, append_images=[Image.new('RGB', (300, 200), 'white')])
        before = hashlib.sha256(multi.read_bytes()).hexdigest()
        result = tools.redact_file(multi, [{'page': 1, 'rect': [0, 0, 1, 1]}], self.root)
        with Image.open(result) as opened:
            self.assertEqual(opened.n_frames, 2)
            opened.seek(1)
            self.assertEqual(opened.size, (300, 200))
            self.assertEqual(opened.convert('RGB').getpixel((100, 100)), (0, 0, 0))
        self.assertEqual(hashlib.sha256(multi.read_bytes()).hexdigest(), before)


class InspectionUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        from app import apply_application_style
        cls.application = QApplication.instance() or QApplication([])
        apply_application_style(cls.application)

    def test_10_dialog_language_and_draw_selection(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from inspection_ui import InspectionDialog
        dialog = InspectionDialog(mode='redact')
        dialog.show()
        dialog.left_canvas.set_image(Image.new('RGB', (400, 500), 'white'))
        dialog.left_canvas.set_draw_enabled(True)
        self.application.processEvents()
        canvas = dialog.left_canvas
        box = canvas.image_rect()
        QTest.mousePress(canvas, Qt.LeftButton, pos=QPoint(int(box.x() + 20), int(box.y() + 20)))
        QTest.mouseRelease(canvas, Qt.LeftButton, pos=QPoint(int(box.x() + 100), int(box.y() + 100)))
        self.assertEqual(len(dialog.rectangles), 1)
        dialog.candidate_list.setCurrentRow(0)
        dialog.region_fields[0].setText('0.2')
        dialog._update_region_fields()
        self.assertEqual(dialog.rectangles[0]['rect'][0], 0.2)
        dialog._remove_region()
        self.assertEqual(dialog.rectangles, [])
        dialog.set_language('en')
        self.assertEqual(dialog.run_button.text(), 'Save redacted copy')
        dialog.set_reduced_motion(True)
        self.assertFalse(dialog.is_busy())
        self.assertTrue(dialog.shutdown())
        dialog.close()

    def test_11_dialog_background_cancel_and_lifetime(self):
        from PySide6.QtTest import QTest
        from inspection_ui import InspectionDialog
        dialog = InspectionDialog()
        dialog.show()
        def operation(cancel):
            while not cancel.wait(0.01):
                pass
            raise Cancelled()
        dialog._start(operation, 'ocr')
        self.assertTrue(dialog.is_busy())
        dialog.close()
        deadline = time.monotonic() + 5
        while dialog.is_busy() and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertFalse(dialog.is_busy())
        self.application.processEvents()
        self.assertFalse(dialog.isVisible())

    def test_12_real_dialog_ocr_export_compare_and_shared_zoom(self):
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QWidget
        from inspection_ui import InspectionDialog
        root = Path(__file__).resolve().parent.parent / 'work/expansion-inspection'
        with tempfile.TemporaryDirectory(prefix='dialog-', dir=root) as directory:
            source, second = Path(directory) / '실제문서.png', Path(directory) / '다른문서.png'
            image = Image.new('RGB', (900, 700), 'white')
            font = ImageFont.truetype(str(Path(__file__).resolve().parent / 'assets/NanumGothicBold.ttf'), 48)
            ImageDraw.Draw(image).text((60, 80), '한글 FlipRing 2026', font=font, fill='black')
            image.save(source)
            image.save(second)
            owner = QWidget()
            owner.pending = 0
            dialog = InspectionDialog(owner, paths=[source, second])
            outputs = []
            dialog.result_ready.connect(lambda *result: outputs.append(result))
            def wait_idle():
                from PySide6.QtCore import QAbstractEventDispatcher, QEventLoop, QObject, QTimer, Qt
                # 기존 완료 조건과 12초 상한을 실제 이벤트 루프에서 관찰한다.
                loop = QEventLoop()
                timer = QTimer(loop)
                timer.setSingleShot(True)
                timer.setTimerType(Qt.PreciseTimer)
                dispatcher = QAbstractEventDispatcher.instance()
                active = [True]
                expired = [False]
                observed_jobs = set()
                job_connections = []

                def completion_gate(*unused):
                    if not active[0]:
                        return
                    job = dialog.job
                    if job is not None and job not in observed_jobs:
                        observed_jobs.add(job)
                        job_connections.append(job.finished.connect(completion_gate, Qt.QueuedConnection))
                    if not (dialog.is_busy() or dialog.preview_timer.isActive()):
                        loop.quit()

                def timeout():
                    if active[0]:
                        expired[0] = True
                        loop.quit()

                preview_connection = dialog.preview_timer.timeout.connect(completion_gate, Qt.QueuedConnection)
                dispatcher_connection = dispatcher.aboutToBlock.connect(completion_gate)
                timer.timeout.connect(timeout)
                try:
                    timer.start(12000)
                    completion_gate()
                    if dialog.is_busy() or dialog.preview_timer.isActive():
                        loop.exec()
                finally:
                    # 종료된 작업의 연결도 연결 핸들로 안전하게 정리한다.
                    active[0] = False
                    timer.stop()
                    timer.timeout.disconnect(timeout)
                    QObject.disconnect(preview_connection)
                    QObject.disconnect(dispatcher_connection)
                    for connection in job_connections:
                        QObject.disconnect(connection)
                self.assertFalse(expired[0], '작업이 12초 안에 종료되지 않았습니다')
                self.assertFalse(dialog.is_busy())
                self.assertEqual(owner.pending, 0)
            dialog.show()
            wait_idle()
            self.assertFalse(dialog.left_canvas.image.isNull())
            self.assertEqual(dialog.left_canvas.zoom, 50)
            dialog._run()
            self.assertEqual(owner.pending, 1)
            wait_idle()
            self.assertIn('한글', dialog.editor.toPlainText())
            dialog.editor.setPlainText('한글 교정 결과')
            dialog.output_edit.setText(directory)
            dialog._export()
            wait_idle()
            self.assertEqual(len(outputs), 1)
            self.assertEqual(Path(outputs[0][1]).read_text(encoding='utf-8'), '한글 교정 결과')
            dialog.mode_combo.setCurrentIndex(1)
            wait_idle()
            dialog.zoom_spin.setValue(150)
            self.application.processEvents()
            self.assertEqual(dialog.left_canvas.zoom, dialog.right_canvas.zoom)
            bars = [scroll.horizontalScrollBar() for scroll in dialog.canvas_scrolls]
            bars[0].setValue(min(100, bars[0].maximum()))
            self.assertEqual(bars[0].value(), bars[1].value())
            dialog._run()
            wait_idle()
            self.assertIn('같습니다', dialog.editor.toPlainText())
            self.assertIn('900', dialog.metadata.text())
            dialog.second_combo.setCurrentIndex(0)
            self.assertEqual(dialog.editor.toPlainText(), '')
            self.assertIn('비교', dialog.status.text())
            wait_idle()
            self.assertEqual(dialog.editor.toPlainText(), '')
            dialog.second_combo.setCurrentIndex(1)
            wait_idle()
            dialog._run()
            wait_idle()
            self.assertIn('같습니다', dialog.editor.toPlainText())
            dialog.set_language('en')
            self.assertIn('pages', dialog.metadata.text())
            dialog.set_reduced_motion(True)
            dialog.grab().save(str(root / 'inspection-compare-en-styled.png'))
            dialog.mode_combo.setCurrentIndex(3)
            wait_idle()
            dialog._add_region([0.05, 0.05, 0.5, 0.25])
            dialog.set_language('ko')
            self.assertIn('페이지', dialog.metadata.text())
            self.assertIn('바이트', dialog.metadata.text())
            self.assertNotIn('pages', dialog.metadata.text())
            dialog.grab().save(str(root / 'inspection-redact-ko-styled.png'))
            dialog.close()
            owner.close()


if __name__ == '__main__':
    unittest.main()
