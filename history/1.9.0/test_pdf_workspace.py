"""실제 PDF 페이지 편집·새 파일 저장과 Qt 작업 흐름을 검증한다."""
from __future__ import annotations

import argparse
from concurrent.futures import Future
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from PySide6.QtCore import Qt, QTimer, QAbstractAnimation, QPointF
from PySide6.QtGui import QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import pdf_tools
from pdf_panel import PdfToolsPanel

OUTPUT = Path(tempfile.gettempdir()) / "flipring-pdf-workspace-tests"


def make_pdf(path):
    document = canvas.Canvas(str(path), pagesize=(300, 420))
    for index, label in enumerate(("FIRST PAGE", "SECOND PAGE", "THIRD PAGE")):
        document.setFillGray(0.2 + index * 0.25)
        document.rect(25 + index * 20, 35, 110, 100 + index * 35, fill=1)
        document.setFillGray(0)
        document.drawString(25, 380, label)
        document.showPage()
    document.save()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=OUTPUT)
        self.root = Path(self.folder.name)
        self.source = self.root / "한글 원본.pdf"
        make_pdf(self.source)
        self.original = self.source.read_bytes()

    def tearDown(self):
        self.assertEqual(self.source.read_bytes(), self.original)
        self.folder.cleanup()

    def workspace(self):
        from pdf_pages import PdfWorkspace
        return PdfWorkspace.open(self.source)

    def test_01_reorder_rotate_delete_and_original_hash(self):
        workspace = self.workspace()
        self.assertEqual(workspace.source_sha256, digest(self.source))
        workspace.reorder([2, 0, 1])
        workspace.rotate([0, 2], 90)
        workspace.delete([1])
        output = workspace.save(self.root / "편집.pdf")
        reader = PdfReader(output)
        self.assertEqual(len(reader.pages), 2)
        self.assertIn("THIRD PAGE", reader.pages[0].extract_text())
        self.assertIn("SECOND PAGE", reader.pages[1].extract_text())
        self.assertEqual([page.rotation for page in reader.pages], [90, 90])
        self.assertEqual(workspace.page_count, 2)

    def test_02_extract_current_order_without_modifying_editor(self):
        workspace = self.workspace()
        workspace.reorder([2, 0, 1])
        workspace.rotate([0], 270)
        output = workspace.save(self.root / "추출.pdf", selected=[0, 2])
        reader = PdfReader(output)
        self.assertEqual(len(reader.pages), 2)
        self.assertIn("THIRD PAGE", reader.pages[0].extract_text())
        self.assertIn("SECOND PAGE", reader.pages[1].extract_text())
        self.assertEqual([page.rotation for page in reader.pages], [270, 0])
        self.assertEqual(workspace.page_count, 3)

    def test_03_rejects_all_delete_and_invalid_indices_without_mutation(self):
        workspace = self.workspace()
        for action, code in ((lambda: workspace.delete([0, 1, 2]), "all_pages_removed"),
                             (lambda: workspace.reorder([1, 1, 2]), "page_range"),
                             (lambda: workspace.rotate([-1], 90), "page_range"),
                             (lambda: workspace.rotate([0], 45), "rotation"),
                             (lambda: workspace.save(selected=[]), "page_range")):
            with self.subTest(code=code), self.assertRaises(pdf_tools.PdfToolError) as caught:
                action()
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(workspace.page_count, 3)

    def test_04_new_name_collision_and_original_path_rejected(self):
        workspace = self.workspace()
        first = Path(workspace.save())
        first_bytes = first.read_bytes()
        second = Path(workspace.save())
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), first_bytes)
        for target in (self.source, first):
            with self.subTest(target=str(target)), self.assertRaises(pdf_tools.PdfToolError):
                workspace.save(target)
        self.assertEqual(first.read_bytes(), first_bytes)

    def test_05_cancel_before_and_during_save_removes_partial_output(self):
        workspace = self.workspace()
        cancelled = threading.Event()
        cancelled.set()
        target = self.root / "취소.pdf"
        with self.assertRaises(pdf_tools.Cancelled):
            workspace.save(target, cancel=cancelled)
        self.assertFalse(target.exists())
        cancelled.clear()

        def cancel_after_first(done, total, label):
            if done == 1:
                cancelled.set()

        with self.assertRaises(pdf_tools.Cancelled):
            workspace.save(target, cancel=cancelled, progress=cancel_after_first)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob(".flipring-pdf-*")))
        cancelled.clear()
        self.assertTrue(Path(workspace.save(target, cancel=cancelled)).is_file())

    def test_06_missing_corrupt_encrypted_and_empty_input(self):
        from pdf_pages import PdfWorkspace
        broken = self.root / "손상.pdf"
        broken.write_bytes(b"broken pdf")
        encrypted = self.root / "암호.pdf"
        writer = PdfWriter()
        writer.add_blank_page(100, 100)
        writer.encrypt("secret")
        writer.write(encrypted)
        writer.close()
        empty = self.root / "빈.pdf"
        writer = PdfWriter()
        writer.write(empty)
        writer.close()
        for path, code in ((self.root / "없음.pdf", "input_files"), (broken, "invalid_pdf"),
                           (encrypted, "encrypted_pdf"), (empty, "empty_pdf")):
            with self.subTest(path=str(path)), self.assertRaises(pdf_tools.PdfToolError) as caught:
                PdfWorkspace.open(path)
            self.assertEqual(caught.exception.code, code)

    def test_07_write_error_keeps_existing_files(self):
        workspace = self.workspace()
        with self.assertRaises(pdf_tools.PdfToolError):
            workspace.save(self.root / "없는 폴더" / "결과.pdf")
        existing = self.root / "기존.pdf"
        existing.write_bytes(b"keep this output")
        with self.assertRaises(pdf_tools.PdfToolError):
            workspace.save(existing)
        self.assertEqual(existing.read_bytes(), b"keep this output")

    def test_08_real_thumbnail_rotation_and_document_handles_released(self):
        workspace = self.workspace()
        first = workspace.render(0, 180)
        third = workspace.render(2, 180)
        self.assertEqual(first.size, (129, 180))
        self.assertNotEqual(first.tobytes(), third.tobytes())
        workspace.rotate([0], 90)
        rotated = workspace.render(0, 180)
        self.assertEqual(rotated.size, (180, 129))
        replacement = self.root / "이름변경.pdf"
        self.source.rename(replacement)
        replacement.rename(self.source)

    def test_09_pdfium_lock_is_shared_and_cancel_after_render_checked(self):
        from pdf_pages import PDFIUM_LOCK
        self.assertIs(PDFIUM_LOCK, pdf_tools.PDFIUM_LOCK)
        workspace = self.workspace()
        started, finished = threading.Event(), threading.Event()

        def render():
            started.set()
            workspace.render(0, 120)
            finished.set()

        with PDFIUM_LOCK:
            worker = threading.Thread(target=render)
            worker.start()
            self.assertTrue(started.wait(2))
            self.assertFalse(finished.wait(0.03))
        worker.join(5)
        self.assertTrue(finished.is_set())
        event = threading.Event()
        event.set()
        with self.assertRaises(pdf_tools.Cancelled):
            workspace.render(0, 180, cancel=event)


class WorkspacePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=OUTPUT)
        self.root = Path(self.folder.name)
        self.source = self.root / "긴 한글 파일 이름 페이지 편집 원본.pdf"
        make_pdf(self.source)
        self.before = digest(self.source)
        self.panel = PdfToolsPanel("ko")
        self.panel.resize(980, 740)
        self.panel.show()
        QTest.qWait(20)
        self.results = []
        self.panel.result_ready.connect(lambda *args: self.results.append(args))

    def tearDown(self):
        self.panel.cancel()
        self.wait_idle()
        self.panel.shutdown(wait=True)
        self.panel.close()
        self.panel.deleteLater()
        QTest.qWait(10)
        self.assertEqual(digest(self.source), self.before)
        self.folder.cleanup()

    def wait_idle(self):
        deadline = time.monotonic() + 10
        while (self.panel.is_busy() or getattr(self.panel, "_render_scheduled", False)) and time.monotonic() < deadline:
            QTest.qWait(5)
        self.assertFalse(self.panel.is_busy(), "PDF 작업 스레드가 제한 시간 안에 끝나야 합니다.")

    def load(self):
        self.panel.load_workspace(str(self.source))
        self.wait_idle()
        self.assertIsNotNone(self.panel.workspace)

    def test_10_load_real_thumbnails_preview_and_responsive_events(self):
        ticks = []
        timer = QTimer()
        timer.setInterval(1)
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start()
        self.load()
        timer.stop()
        self.assertTrue(ticks)
        self.assertEqual(self.panel.pages_list.count(), 3)
        self.assertFalse(self.panel.pages_list.item(0).icon().isNull())
        self.assertFalse(self.panel.page_preview.pixmap().isNull())
        self.assertEqual(self.panel.workspace.source_sha256, self.before)
        self.panel.grab().save(str(OUTPUT / "PDF-편집-한국어.png"))

    def test_11_multiselect_rotate_delete_extract_and_save(self):
        self.load()
        self.panel.pages_list.clearSelection()
        self.panel.pages_list.item(0).setSelected(True)
        self.panel.pages_list.item(2).setSelected(True)
        self.panel.rotate_selected_pages()
        self.wait_idle()
        target = self.root / "선택.pdf"
        self.panel.save_workspace(str(target), selected=True)
        self.wait_idle()
        reader = PdfReader(target)
        self.assertEqual(len(reader.pages), 2)
        self.assertEqual([page.rotation for page in reader.pages], [90, 90])
        self.assertEqual(self.panel.workspace.page_count, 3)
        self.panel.delete_selected_pages()
        self.wait_idle()
        self.assertEqual(self.panel.workspace.page_count, 1)
        output = self.root / "나머지.pdf"
        self.panel.save_workspace(str(output))
        self.wait_idle()
        self.assertIn("SECOND PAGE", PdfReader(output).pages[0].extract_text())

    def test_12_page_order_model_move_and_all_delete_guard(self):
        self.load()
        model = self.panel.pages_list.model()
        self.assertTrue(model.moveRow(model.index(-1, -1), 2, model.index(-1, -1), 0))
        self.wait_idle()
        self.panel.pages_list.selectAll()
        self.panel.delete_selected_pages()
        self.assertEqual(self.panel.workspace.page_count, 3)
        self.assertIn("모든 페이지", self.panel.status.text())
        target = self.root / "드래그 순서.pdf"
        self.panel.save_workspace(str(target))
        self.wait_idle()
        self.assertIn("THIRD PAGE", PdfReader(target).pages[0].extract_text())

    def test_13_language_and_reduced_motion_keep_selection_and_input(self):
        self.load()
        self.panel.set_reduced_motion(True)
        self.panel.set_language("en")
        self.assertIn("Save", self.panel.save_pages_button.text())
        self.assertIn("Page", self.panel.pages_list.item(0).text())
        self.panel.pages_list.setCurrentRow(1)
        self.wait_idle()
        self.panel.rotate_selected_pages()
        self.wait_idle()
        self.assertEqual(self.panel.workspace.pages[1].rotation, 90)
        self.assertEqual(self.panel.status_mark.animation.state(), QAbstractAnimation.Stopped)
        self.assertTrue(self.panel.save_pages_button.isEnabled())
        self.panel.grab().save(str(OUTPUT / "PDF-편집-영어-모션감소.png"))
        self.panel.set_language("ko")
        self.assertIn("저장", self.panel.save_pages_button.text())

    def test_14_preset_roundtrip_does_not_execute_or_reuse_paths(self):
        self.panel.operation.setCurrentIndex(self.panel.operation.findData("recognize"))
        self.panel.pages.setText("1,3")
        self.panel.dpi.setValue(300)
        self.panel.output.setCurrentIndex(self.panel.output.findData("txt"))
        self.panel.force.setChecked(True)
        received = []
        self.panel.preset_requested.connect(received.append)
        self.panel.save_preset_button.click()
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["kind"], "pdf")
        self.assertEqual(received[0]["format"], "pdf")
        saved = received[0]["options"]
        self.assertNotIn("paths", saved)
        self.panel.pages.clear()
        self.panel.dpi.setValue(100)
        self.panel.apply_preset(saved)
        self.assertEqual(self.panel.operation.currentData(), "recognize")
        self.assertEqual(self.panel.output.currentData(), "txt")
        self.assertEqual(self.panel.dpi.value(), 300)
        self.assertEqual(self.panel.pages.text(), "1,3")
        self.assertTrue(self.panel.force.isChecked())
        self.assertEqual(self.panel.input_paths(), [])
        self.assertFalse(self.panel.is_busy())
        self.assertEqual(self.results, [])

    def test_15_invalid_preset_is_atomic_and_busy_input_unchanged(self):
        self.panel.dpi.setValue(200)
        self.assertFalse(self.panel.apply_preset({"operation": "recognize", "dpi": 9999}))
        self.assertEqual(self.panel.dpi.value(), 200)
        self.assertEqual(self.panel.operation.currentData(), "merge")
        self.panel.pending = 1
        self.panel.load_workspace(str(self.source))
        self.assertIsNone(self.panel.workspace)
        self.assertIn("다른 변환", self.panel.status.text())

    def test_16_cancel_load_preserves_current_editor_and_retry(self):
        self.load()
        original_workspace = self.panel.workspace
        from pdf_pages import PdfWorkspace
        real_open = PdfWorkspace.open

        def slow_open(path, cancel=None):
            while not cancel.wait(0.01):
                pass
            pdf_tools.check_cancel(cancel)
            return real_open(path, cancel=cancel)

        with patch.object(PdfWorkspace, "open", slow_open):
            self.panel.load_workspace(str(self.source))
            QTest.qWait(15)
            self.panel.cancel()
            self.wait_idle()
        self.assertIs(self.panel.workspace, original_workspace)
        self.assertIn("취소", self.panel.status.text())
        self.load()
        self.assertTrue(self.panel.save_pages_button.isEnabled())

    def test_17_bad_input_translates_and_save_dialog_cancel_keeps_editor(self):
        self.load()
        original_workspace = self.panel.workspace
        self.panel.load_workspace(str(self.root / "없음.pdf"))
        self.wait_idle()
        self.assertIs(self.panel.workspace, original_workspace)
        self.panel.set_language("en")
        self.assertIn("input", self.panel.status.text().lower())
        with patch("pdf_panel.QFileDialog.getSaveFileName", return_value=("", "")):
            self.panel.choose_workspace_save()
        self.assertFalse(self.panel.is_busy())
        self.assertIs(self.panel.workspace, original_workspace)

    def test_18_actual_thumbnail_drop_saves_visible_order(self):
        self.load()
        page_list = self.panel.pages_list
        mime = page_list.mimeData([page_list.item(2)])
        rectangle = page_list.visualItemRect(page_list.item(0))
        event = QDropEvent(QPointF(rectangle.left() + 3, rectangle.top() + 3), Qt.MoveAction,
                           mime, Qt.LeftButton, Qt.NoModifier)
        page_list.dropEvent(event)
        self.assertTrue(event.isAccepted())
        self.wait_idle()
        target = self.root / "썸네일 드롭.pdf"
        self.panel.save_workspace(str(target))
        self.wait_idle()
        self.assertIn("THIRD PAGE", PdfReader(target).pages[0].extract_text())

    def test_19_enlarged_preview_zoom_and_editor_actions_are_clear(self):
        self.load()
        self.assertFalse(self.panel.options_card.isVisible())
        self.panel.open_page_preview()
        self.assertTrue(self.panel.preview_dialog.isVisible())
        before = self.panel.preview_dialog.zoom_factor
        self.panel.preview_dialog.zoom_in_button.click()
        self.assertGreater(self.panel.preview_dialog.zoom_factor, before)
        self.panel.set_language("en")
        self.assertIn("Page", self.panel.preview_dialog.windowTitle())
        self.panel.preview_dialog.close()
        QTest.qWait(10)

    def test_20_corrupt_preset_value_types_leave_options_unchanged(self):
        before = self.panel.snapshot_options()
        for options in ({"operation": []}, {"compression": {}}, {"ocr_language": []},
                        {"output_format": []}, {"pages": None}, {"force_ocr": 1}):
            with self.subTest(options=options):
                self.assertFalse(self.panel.apply_preset(options))
                self.assertEqual(self.panel.snapshot_options(), before)

    def test_21_cancel_after_committed_save_keeps_result_record(self):
        self.load()
        target = self.root / "이미 완성한 결과.pdf"
        self.panel.save_workspace(str(target))
        deadline = time.monotonic() + 5
        # GUI 완료 슬롯을 처리하기 전에 디스크 저장이 끝난 경우를 제어한다.
        while not self.panel._future.done() and time.monotonic() < deadline:
            time.sleep(0.001)
        self.assertTrue(self.panel._future.done())
        self.assertTrue(target.is_file())
        self.panel.cancel()
        self.wait_idle()
        self.assertEqual(len(self.results), 1)
        self.assertEqual(Path(self.results[0][1]), target)
        self.assertEqual(len(PdfReader(target).pages), 3)

    def test_22_all_pdf_operations_block_submission_when_disk_is_full(self):
        image = self.root / "이미지.png"
        from PIL import Image
        Image.new("RGB", (60, 80), "white").save(image)
        for operation in ("merge", "split", "extract", "delete", "rotate", "images_to_pdf",
                          "pdf_to_images", "compress", "recognize"):
            with self.subTest(operation=operation):
                self.panel.set_files([str(image if operation == "images_to_pdf" else self.source)])
                self.panel.operation.setCurrentIndex(self.panel.operation.findData(operation))
                future = Future()
                future.set_result(None)
                with patch.object(pdf_tools.shutil, "disk_usage", return_value=SimpleNamespace(free=0)) as usage, \
                     patch.object(self.panel._pool, "submit", return_value=future) as submit:
                    self.panel.start()
                    self.assertFalse(self.panel.is_busy())
                    self.assertTrue(usage.called)
                    submit.assert_not_called()
                    self.assertIn("여유 공간", self.panel.status.text())
                QTest.qWait(5)
        self.panel.set_language("en")
        self.assertIn("space", self.panel.status.text().lower())

    def test_23_missing_input_and_bundled_ocr_files_block_submission(self):
        future = Future()
        future.set_result(None)
        self.panel.set_files([str(self.root / "누락.pdf")])
        with patch.object(self.panel._pool, "submit", return_value=future) as submit:
            self.panel.start()
            self.assertFalse(self.panel.is_busy())
            submit.assert_not_called()
            self.assertIn("입력 파일", self.panel.status.text())
        QTest.qWait(5)
        self.panel.set_files([str(self.source)])
        self.panel.operation.setCurrentIndex(self.panel.operation.findData("recognize"))
        missing_runtime = self.root / "없는 OCR"
        with patch.object(pdf_tools, "tesseract_paths", return_value=(missing_runtime / "tesseract.exe", missing_runtime / "tessdata")), \
             patch.object(self.panel._pool, "submit", return_value=future) as submit:
            self.panel.start()
            self.assertFalse(self.panel.is_busy())
            submit.assert_not_called()
            self.assertIn("OCR", self.panel.status.text())
        data = self.root / "모델 점검"
        data.mkdir()
        required = [self.root / "동봉점검.exe", data / "pdf.ttf", data / "kor.traineddata", data / "eng.traineddata"]
        for path in required:
            path.write_bytes(b"controlled existing file; never executed")
        for missing in required:
            with self.subTest(missing=missing.name):
                content = missing.read_bytes()
                missing.unlink()
                try:
                    with patch.object(pdf_tools, "tesseract_paths", return_value=(required[0], data)), \
                         patch.object(self.panel._pool, "submit", return_value=future) as submit:
                        self.panel.start()
                        self.assertFalse(self.panel.is_busy())
                        submit.assert_not_called()
                        self.assertIn("OCR", self.panel.status.text())
                finally:
                    missing.write_bytes(content)

    def test_24_output_locations_follow_merge_and_per_input_publication(self):
        second_folder = self.root / "다른 출력 폴더"
        second_folder.mkdir()
        second = second_folder / "두번째.pdf"
        make_pdf(second)
        paths = [str(self.source), str(second)]
        merge = pdf_tools.preflight_request(pdf_tools.Request("merge", paths))
        split = pdf_tools.preflight_request(pdf_tools.Request("split", paths))
        self.assertEqual({Path(row["directory"]) for row in merge}, {self.source.parent})
        self.assertEqual({Path(row["directory"]) for row in split}, {self.source.parent, second_folder})
        self.assertTrue(all(row["free"] >= row["estimated"] > 0 for row in merge + split))
        self.assertFalse(list(self.root.rglob(".flipring-check-*")))

    def test_25_editor_save_blocks_full_disk_without_rereading_snapshot_source(self):
        self.load()
        target = self.root / "편집 저장.pdf"
        future = Future()
        future.set_result(str(target))
        with patch.object(pdf_tools.shutil, "disk_usage", return_value=SimpleNamespace(free=0)), \
             patch.object(self.panel._pool, "submit", return_value=future) as submit:
            self.panel.save_workspace(str(target))
            self.assertFalse(self.panel.is_busy())
            submit.assert_not_called()
            self.assertFalse(target.exists())
        moved = self.root / "외부에서 이동한 원본.pdf"
        self.source.rename(moved)
        try:
            self.panel.save_workspace(str(target))
            self.wait_idle()
            self.assertEqual(len(PdfReader(target).pages), 3)
        finally:
            moved.rename(self.source)

    def test_26_worker_preflight_rejects_space_before_pdf_processing(self):
        from pdf_pages import PdfWorkspace
        workspace = PdfWorkspace.open(self.source)
        target = self.root / "직접 저장.pdf"
        with patch.object(pdf_tools.shutil, "disk_usage", return_value=SimpleNamespace(free=0)):
            with self.assertRaises(pdf_tools.PdfToolError) as caught:
                pdf_tools.execute(pdf_tools.Request("split", [str(self.source)]))
            self.assertEqual(caught.exception.code, "disk_space")
            with self.assertRaises(pdf_tools.PdfToolError) as caught:
                workspace.save(target)
            self.assertEqual(caught.exception.code, "disk_space")
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob("*page-*.pdf")))

    def test_27_output_write_failure_is_translated_and_preserves_completed_file(self):
        self.load()
        completed = self.root / "이전 완성 결과.pdf"
        completed.write_bytes(b"previous completed output")
        target = self.root / "쓰기 거부.pdf"
        with patch.object(pdf_tools.tempfile, "TemporaryFile", side_effect=PermissionError("controlled write refusal")):
            self.panel.save_workspace(str(target))
            self.assertFalse(self.panel.is_busy())
            self.assertIn("쓰기", self.panel.status.text())
            self.panel.set_language("en")
            self.assertIn("writ", self.panel.status.text().lower())
        self.assertFalse(target.exists())
        self.assertEqual(completed.read_bytes(), b"previous completed output")

    def test_28_preflight_cancel_keeps_directory_and_avoids_probe(self):
        event = threading.Event()
        event.set()
        before = set(self.root.iterdir())
        with patch.object(pdf_tools.shutil, "disk_usage") as usage:
            with self.assertRaises(pdf_tools.Cancelled):
                pdf_tools.preflight_output(self.root, 64 * 1024 * 1024, cancel=event)
            usage.assert_not_called()
        self.assertEqual(set(self.root.iterdir()), before)

    def test_29_real_preflight_estimate_is_visible_and_retranslated(self):
        self.panel.set_files([str(self.source)])
        self.panel.start()
        self.wait_idle()
        self.assertEqual(len(self.results), 1)
        self.assertTrue(Path(self.results[0][1]).is_file())
        self.assertIn("준비 예상", self.panel.preflight_label.text())
        self.assertIn("보장", self.panel.preflight_label.text())
        self.panel.set_language("en")
        self.assertIn("Estimated", self.panel.preflight_label.text())
        self.assertIn("guarantee", self.panel.preflight_label.text())

    def test_30_worker_recheck_failure_replaces_old_space_summary(self):
        self.panel.set_files([str(self.source)])
        with patch.object(pdf_tools.shutil, "disk_usage", side_effect=[SimpleNamespace(free=10**12), SimpleNamespace(free=0)]):
            self.panel.start()
            self.wait_idle()
        self.assertIn("여유 공간", self.panel.status.text())
        self.assertIn("여유 공간 0 MiB", self.panel.preflight_label.text())
        self.assertEqual(len(self.results), 1)
        self.assertEqual(self.results[0][1], "")
        self.assertFalse(list(self.root.glob("*-merge.pdf")))


def main():
    global OUTPUT
    parser = argparse.ArgumentParser()
    parser.add_argument("output")
    args = parser.parse_args()
    OUTPUT = Path(args.output).resolve()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    report = {"tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
              "skipped": len(result.skipped), "success": result.wasSuccessful()}
    (OUTPUT / "PDF-페이지편집-검증.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return int(not result.wasSuccessful())


if __name__ == "__main__":
    sys.exit(main())
