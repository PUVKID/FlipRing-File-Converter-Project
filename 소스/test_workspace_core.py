"""새 작업 공간의 실제 생성물과 원본 보존 경계를 검증한다."""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
import warnings
from unittest.mock import patch

from PIL import Image, ImageSequence
from PIL import ImageChops
from pypdf import PdfReader, PdfWriter
from openpyxl import load_workbook
from reportlab.pdfgen import canvas
from PIL import ImageDraw, ImageFont


class WorkspaceCoreTests(unittest.TestCase):
    def setUp(self):
        self.core = importlib.import_module("workspace_core")
        self.temp = tempfile.TemporaryDirectory(prefix="flipring-core-")
        self.root = Path(self.temp.name)
        self.out = self.root / "결과"
        self.out.mkdir()
        self.a = self.root / "가.png"
        self.b = self.root / "나.png"
        Image.new("RGB", (160, 100), "red").save(self.a)
        Image.new("RGB", (100, 160), "blue").save(self.b)
        self.baseline = {p: self.digest(p) for p in (self.a, self.b)}

    def tearDown(self):
        if hasattr(self, "baseline"):
            for path, digest in self.baseline.items():
                self.assertEqual(self.digest(path), digest)
        if hasattr(self, "temp"):
            self.temp.cleanup()

    @staticmethod
    def digest(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def run_recipe(self, steps, paths=None, **kwargs):
        return self.core.execute_workspace(
            [str(p) for p in (paths or [self.a])],
            {"version": 1, "name": "시험", "steps": steps},
            output_dir=str(self.out), **kwargs)

    def test_01_module_and_recipe_whitelist(self):
        recipe = self.core.validate_recipe({"version": 1, "name": "기본", "steps": [{"op": "audit"}]})
        self.assertEqual(recipe["steps"][0]["op"], "audit")
        for value in ({"op": "shell", "command": "whoami"}, {"op": "resize", "width": float("nan")},
                      {"op": "convert", "format": "../exe"}, {"op": "audit", "script": "x"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.core.validate_recipe({"version": 1, "name": "잘못됨", "steps": [value]})

    def test_02_names_and_windows_reserved_paths(self):
        names = self.core.preview_names([self.a, self.b], "{date}_{index:03d}_{name}", start=4)
        self.assertTrue(names[0]["name"].endswith("004_가.png"))
        for template in ("../{name}", "C:\\{name}", "CON", "LPT1.txt", "{name}.", "{unknown}", "{name.__class__}"):
            with self.subTest(template=template), self.assertRaises(ValueError):
                self.core.preview_names([self.a], template)

    def test_03_rename_copies_collisions(self):
        existing = self.out / "복사.png"
        existing.write_bytes("기존".encode("utf-8"))
        result = self.core.rename_copies([self.a, self.b], "복사", output_dir=self.out)
        self.assertEqual(len(result), 2)
        self.assertEqual(existing.read_bytes(), "기존".encode("utf-8"))
        self.assertEqual(self.digest(result[0]), self.digest(self.a))
        self.assertEqual(len(set(result)), 2)

    def test_04_recipe_store_crud_and_corruption(self):
        store = self.core.RecipeStore(self.root / "recipes.json")
        self.assertEqual(store.load(), [])
        recipe = {"version": 1, "name": "일괄", "steps": [{"op": "rename", "template": "{name}_{index}"}]}
        store.save(recipe)
        store.save(recipe)
        self.assertEqual(len(store.load()), 1)
        store.delete("일괄")
        self.assertEqual(store.load(), [])
        store.path.write_text("{손상", encoding="utf-8")
        before = store.path.read_bytes()
        with self.assertRaises(ValueError):
            store.load()
        with self.assertRaises(ValueError):
            store.save(recipe)
        self.assertEqual(store.path.read_bytes(), before)

    def test_05_resize_then_convert_real_files(self):
        events = []
        result = self.run_recipe([{"op": "resize", "width": 80, "height": 50},
                                  {"op": "convert", "format": "jpg"}], on_event=events.append)
        self.assertEqual(result["status"], "completed", result)
        self.assertTrue(result["constraints_met"])
        with Image.open(result["outputs"][0]) as image:
            self.assertEqual(image.size, (80, 50))
            self.assertEqual(image.format, "JPEG")
        self.assertTrue(all({"state", "step", "total", "label"} <= e.keys() for e in events))
        self.assertEqual(events[-1]["state"], "completed")

    def test_06_combine_mixed_pdf_images_order(self):
        pdf = self.root / "원본.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=300)
        writer.write(pdf)
        writer.close()
        result = self.run_recipe([{"op": "combine_pdf"}], paths=[self.a, pdf, self.b])
        self.assertEqual(result["status"], "completed", result)
        pages = PdfReader(result["outputs"][0]).pages
        self.assertEqual(len(pages), 3)
        self.assertEqual(float(pages[1].mediabox.width), 200)

    def test_07_collage_actual_dimensions(self):
        result = self.run_recipe([{"op": "collage", "columns": 2, "cell_width": 60,
                                   "cell_height": 40, "padding": 4}], paths=[self.a, self.b])
        self.assertEqual(result["status"], "completed", result)
        with Image.open(result["outputs"][0]) as image:
            self.assertEqual(image.size, (132, 48))
            self.assertNotEqual(image.getpixel((30, 24)), image.getpixel((96, 24)))

    def test_08_gif_contains_ordered_frames(self):
        result = self.run_recipe([{"op": "gif", "width": 80, "height": 60,
                                   "duration": 200, "loop": 2}], paths=[self.a, self.b])
        self.assertEqual(result["status"], "completed", result)
        with Image.open(result["outputs"][0]) as image:
            self.assertEqual(image.n_frames, 2)
            self.assertEqual(image.size, (80, 60))
            self.assertEqual(image.info["loop"], 2)
            self.assertEqual(image.info["duration"], 200)

    def test_09_image_and_text_watermarks_change_pixels(self):
        for step in ({"op": "watermark", "text": "PUVKID", "opacity": 0.8},
                     {"op": "watermark", "image": str(self.b), "opacity": 0.5}):
            result = self.run_recipe([step])
            self.assertEqual(result["status"], "completed", result)
            with Image.open(result["outputs"][0]) as image, Image.open(self.a) as original:
                self.assertNotEqual(image.convert("RGB").tobytes(), original.tobytes())

    def test_10_target_a4_and_impossible_size_report(self):
        result = self.run_recipe([], target={"format": "pdf", "page_size": "A4", "max_bytes": 1})
        self.assertEqual(result["status"], "completed", result)
        self.assertFalse(result["constraints_met"])
        self.assertTrue(result["warnings"])
        page = PdfReader(result["outputs"][0]).pages[0]
        self.assertAlmostEqual(float(page.mediabox.width), 595.2756, places=2)
        self.assertAlmostEqual(float(page.mediabox.height), 841.8898, places=2)
        self.assertGreater(Path(result["outputs"][0]).stat().st_size, 1)

    def test_11_pdf_compression_is_readable(self):
        combined = self.run_recipe([{"op": "combine_pdf"}], paths=[self.a, self.b])["outputs"][0]
        result = self.run_recipe([{"op": "compress_pdf", "mode": "lossless"}], paths=[combined])
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(len(PdfReader(result["outputs"][0]).pages), 2)

    def test_12_cancel_before_start_creates_nothing(self):
        cancel = threading.Event()
        cancel.set()
        result = self.run_recipe([{"op": "rename"}], cancel=cancel)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["outputs"], [])
        self.assertEqual(list(self.out.iterdir()), [])

    def test_13_cancel_preserves_completed_outputs(self):
        cancel = threading.Event()
        def progress(event):
            if event["state"] == "file_completed":
                cancel.set()
        result = self.run_recipe([{"op": "resize", "width": 80, "height": 50}],
                                 paths=[self.a, self.b], cancel=cancel, on_event=progress)
        self.assertEqual(result["status"], "cancelled", result)
        self.assertEqual(len(result["outputs"]), 1)
        self.assertTrue(Path(result["outputs"][0]).is_file())

    def test_14_middle_failure_keeps_first_result(self):
        bad = self.root / "손상.png"
        bad.write_bytes(b"not an image")
        result = self.run_recipe([{"op": "resize", "width": 80, "height": 50}], paths=[self.a, bad])
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(len(result["outputs"]), 1)
        self.assertTrue(Path(result["outputs"][0]).is_file())
        self.assertTrue(result["error"])

    def test_15_target_nan_unknown_and_source_directory_rejected(self):
        for target in ({"dpi": float("nan")}, {"max_bytes": -1}, {"page_size": "letter"}, {"command": "x"}):
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.run_recipe([], target=target)
        with self.assertRaises(ValueError):
            self.run_recipe([{"op": "rename"}], paths=[self.root])

    def test_16_receipts_real_xlsx_formula_is_plain_text(self):
        recognized = {"text": "=HYPERLINK(\"x\")\t1200\n품목\t3000", "words": [], "pages": []}
        # OCR 엔진은 별도 담당 모듈이며 표 저장 경계는 실제 XLSX로 검사한다.
        with patch("workspace_core._recognize", return_value=recognized):
            result = self.run_recipe([{"op": "receipts_xlsx"}])
        self.assertEqual(result["status"], "completed", result)
        book = load_workbook(result["outputs"][0], data_only=False)
        try:
            sheet = book.worksheets[0]
            self.assertTrue(any(cell.value == "=HYPERLINK(\"x\")" and cell.data_type != "f"
                                for row in sheet for cell in row))
            self.assertTrue(any(cell.value == "3000" for row in sheet for cell in row))
        finally:
            book.close()

    def test_17_unknown_recipe_envelope_and_placeholder_format(self):
        for recipe in ({"version": True, "name": "x", "steps": []},
                       {"version": 1, "name": "x", "steps": [], "command": "x"},
                       {"version": 1, "name": "x", "steps": [{"op": "rename", "template": "{index:999999999d}"}]}):
            with self.subTest(recipe=recipe), self.assertRaises(ValueError):
                self.core.validate_recipe(recipe)

    def test_18_same_name_copy_is_new_and_threads_do_not_overwrite(self):
        results = []
        def copy():
            results.extend(self.core.rename_copies([self.a], "{name}", output_dir=self.root))
        threads = [threading.Thread(target=copy) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(results), 4)
        self.assertEqual(len(set(results)), 4)
        self.assertTrue(all(self.digest(path) == self.digest(self.a) for path in results))

    def text_pdf(self):
        path = self.root / "문자.pdf"
        document = canvas.Canvas(str(path), pagesize=(300, 200))
        document.drawString(20, 90, "Original text preserved")
        document.save()
        self.baseline[path] = self.digest(path)
        return path

    def test_19_normalize_keeps_text_without_deprecated_mutation(self):
        path = self.text_pdf()
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            result = self.run_recipe([{"op": "normalize_pages"}], paths=[path])
        self.assertEqual(result["status"], "completed", result)
        reader = PdfReader(result["outputs"][0])
        self.assertIn("Original text preserved", reader.pages[0].extract_text())

    def test_20_pdf_watermark_preserves_original_text(self):
        path = self.text_pdf()
        result = self.run_recipe([{"op": "watermark", "text": "확인 PUVKID", "image": str(self.a)}], paths=[path])
        self.assertEqual(result["status"], "completed", result)
        text = PdfReader(result["outputs"][0]).pages[0].extract_text()
        self.assertIn("Original text preserved", text)
        self.assertIn("PUVKID", text)

    def test_21_target_dpi_without_format_is_applied(self):
        result = self.run_recipe([], target={"dpi": 300, "quality": 75})
        self.assertEqual(result["status"], "completed", result)
        with Image.open(result["outputs"][0]) as image:
            self.assertAlmostEqual(image.info["dpi"][0], 300, delta=1)

    def test_22_redact_real_image_removes_selected_pixels(self):
        result = self.run_recipe([{"op": "redact", "rectangles": [{"page": 0, "rect": [0, 0, 0.5, 1]}]}])
        self.assertEqual(result["status"], "completed", result)
        with Image.open(result["outputs"][0]) as image:
            image = image.convert("RGB")
            self.assertEqual(image.getpixel((20, 50)), (0, 0, 0))
            self.assertEqual(image.getpixel((140, 50)), (255, 0, 0))

    def test_23_redact_out_of_range_page_does_not_publish(self):
        result = self.run_recipe([{"op": "redact", "rectangles": [{"page": 1, "rect": [0, 0, 1, 1]}]}])
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["outputs"], [])
        self.assertEqual(list(self.out.iterdir()), [])

    def test_24_real_ocr_and_receipts_xlsx(self):
        image = Image.new("RGB", (1100, 400), "white")
        font = ImageFont.truetype(str(self.core.engine.asset("NanumGothicBold.ttf")), 56)
        ImageDraw.Draw(image).text((30, 60), "PUVKID 1200\nTOTAL 3000", font=font, fill="black", spacing=35)
        path = self.root / "receipt.png"
        image.save(path)
        result = self.run_recipe([{"op": "ocr", "format": "txt", "language": "eng"}], paths=[path])
        self.assertEqual(result["status"], "completed", result)
        self.assertIn("3000", Path(result["outputs"][0]).read_text(encoding="utf-8"))
        result = self.run_recipe([{"op": "receipts_xlsx", "language": "eng"}], paths=[path])
        self.assertEqual(result["status"], "completed", result)
        book = load_workbook(result["outputs"][0])
        try:
            values = [str(cell.value) for row in book.active for cell in row]
            self.assertTrue(any("3000" in value for value in values))
        finally:
            book.close()

    def test_25_audit_is_candidate_and_preserves_pdf(self):
        path = self.root / "빈페이지.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=300)
        writer.add_blank_page(width=200, height=300)
        writer.write(path)
        writer.close()
        self.baseline[path] = self.digest(path)
        result = self.run_recipe([{"op": "audit"}], paths=[path])
        self.assertEqual(result["status"], "completed", result)
        kinds = {check["kind"] for check in result["checks"]}
        self.assertIn("blank", kinds)
        self.assertIn("duplicate", kinds)
        self.assertEqual(len(PdfReader(path).pages), 2)

    def test_26_write_denied_reports_failure_and_keeps_source(self):
        with patch("workspace_core._publish", side_effect=PermissionError("쓰기 거부")):
            result = self.run_recipe([{"op": "rename"}])
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["outputs"], [])
        self.assertIn("쓰기 거부", result["error"])

    def test_27_invalid_rectangles_and_encrypted_pdf_rejected(self):
        for rect in ([0, 0, float("nan"), 1], [0.5, 0, 0.6, 1], [0, 0, 0, 1]):
            with self.subTest(rect=rect), self.assertRaises(ValueError):
                self.run_recipe([{"op": "redact", "rectangles": [{"page": 0, "rect": rect}]}])
        path = self.root / "암호.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=300)
        writer.encrypt("secret")
        writer.write(path)
        writer.close()
        self.baseline[path] = self.digest(path)
        result = self.run_recipe([{"op": "normalize_pages"}], paths=[path])
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["outputs"], [])

    def test_28_cancel_after_first_step_keeps_finished_step(self):
        cancel = threading.Event()
        def progress(event):
            if event["state"] == "step_completed":
                cancel.set()
        result = self.run_recipe([{"op": "resize", "width": 80}, {"op": "convert", "format": "jpg"}],
                                 cancel=cancel, on_event=progress)
        self.assertEqual(result["status"], "cancelled", result)
        self.assertEqual(len(result["outputs"]), 1)
        self.assertEqual(result["steps"][0]["state"], "completed")
        self.assertTrue(Path(result["outputs"][0]).is_file())

    def test_29_transparent_png_conversion_matches_white_background(self):
        path = self.root / "투명.png"
        Image.new("RGBA", (100, 100), (0, 0, 0, 0)).save(path)
        result = self.run_recipe([{"op": "convert", "format": "jpg"}], paths=[path])
        self.assertEqual(result["status"], "completed", result)
        with Image.open(result["outputs"][0]) as image:
            self.assertEqual(image.getpixel((50, 50)), (255, 255, 255))

    @unittest.skipUnless(__import__("os").name == "nt", "Windows 공유 잠금 검사")
    def test_30_locked_source_has_explicit_error_and_no_partial_copy(self):
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                      wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.CreateFileW(str(self.a), 0x80000000, 0, None, 3, 0x80, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        try:
            result = self.run_recipe([{"op": "rename"}])
            self.assertEqual(result["status"], "failed", result)
            self.assertTrue(result["error"])
            self.assertEqual(result["outputs"], [])
            self.assertEqual(list(self.out.iterdir()), [])
        finally:
            self.assertTrue(kernel.CloseHandle(handle))

    def test_31_resource_limits_and_invalid_store_preserve_files(self):
        for step in ({"op": "gif", "width": 12000, "height": 12000},
                     {"op": "collage", "columns": 100, "cell_width": 12000, "cell_height": 12000},
                     {"op": "resize", "width": 12000, "height": 12000}):
            result = self.run_recipe([step])
            self.assertEqual(result["status"], "failed", result)
            self.assertEqual(result["outputs"], [])
        store = self.core.RecipeStore(self.root / "recipes.json")
        store.save({"version": 1, "name": "기존", "steps": []})
        before = store.path.read_bytes()
        with self.assertRaises(ValueError):
            store.save({"version": 1, "name": "위험", "steps": [{"op": "eval"}]})
        self.assertEqual(store.path.read_bytes(), before)

    def test_32_target_pdf_dpi_resamples_embedded_images(self):
        image = self.root / "큰이미지.png"
        Image.new("RGB", (1000, 1000), "green").save(image)
        source = self.root / "이미지문서.pdf"
        document = canvas.Canvas(str(source), pagesize=(144, 144))
        document.drawImage(str(image), 0, 0, width=144, height=144)
        document.save()
        self.baseline[source] = self.digest(source)
        result = self.run_recipe([], paths=[source], target={"dpi": 100, "quality": 70})
        self.assertEqual(result["status"], "completed", result)
        embedded = PdfReader(result["outputs"][0]).pages[0].images[0].image
        self.assertEqual(embedded.size, (200, 200))

    def test_33_combined_pixel_total_is_checked_before_decode(self):
        source = self.root / "합계검사.png"
        Image.new("RGB", (1000, 1000), "white").save(source)
        # 대량 디코딩을 차단하되 실제 이미지 헤더 41개와 실행 결과를 검사한다.
        with patch("workspace_core._image", side_effect=AssertionError("디코딩이 먼저 시작됨")):
            result = self.run_recipe([{"op": "gif"}], paths=[source] * 41)
        self.assertEqual(result["status"], "failed", result)
        self.assertIn("합계", result["error"])
        self.assertEqual(result["outputs"], [])
        self.assertEqual(list(self.out.iterdir()), [])

    def test_34_resize_preserves_transparency_in_png(self):
        path = self.root / "투명원본.png"
        Image.new("RGBA", (100, 100), (200, 30, 90, 0)).save(path)
        result = self.run_recipe([{"op": "resize", "width": 50, "height": 50}], paths=[path])
        self.assertEqual(result["status"], "completed", result)
        with Image.open(result["outputs"][0]) as image:
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.getpixel((20, 20))[3], 0)

    def test_35_jpeg_tif_aliases_apply_dpi_and_preserve_originals(self):
        for extension, format_name in (("jpeg", "JPEG"), ("tif", "TIFF")):
            path = self.root / ("별칭." + extension)
            Image.new("RGB", (80, 60), "purple").save(path, format=format_name)
            self.baseline[path] = self.digest(path)
            result = self.run_recipe([], paths=[path], target={"dpi": 300, "quality": 75, "max_bytes": 1})
            self.assertEqual(result["status"], "completed", result)
            self.assertFalse(result["constraints_met"])
            with Image.open(result["outputs"][0]) as image:
                self.assertEqual(image.format, format_name)
                self.assertEqual(image.size, (80, 60))
                self.assertAlmostEqual(image.info["dpi"][0], 300, delta=1)

    def animation(self, extension, *, poster=False, loop=2):
        path = self.root / ("움직이는원본." + extension)
        frames = [Image.new("RGBA", (64, 48), color) for color in ("red", "blue", "green")]
        options = {"save_all": True, "append_images": frames[1:], "duration": [120, 230, 340], "loop": loop}
        if extension == "png" and poster:
            options.update(default_image=True, duration=[230, 340])
        if extension == "webp":
            options["lossless"] = True
        frames[0].save(path, **options)
        self.baseline[path] = self.digest(path)
        return path

    @staticmethod
    def animation_info(path):
        with Image.open(path) as image:
            result = {"count": image.n_frames, "loop": image.info.get("loop"),
                      "poster": image.info.get("default_image", False), "durations": [], "colors": []}
            for index in range(image.n_frames):
                image.seek(index)
                image.load()
                result["durations"].append(image.info.get("duration"))
                result["colors"].append(image.convert("RGB").getpixel((32, 24)))
            return result

    def test_36_gif_quality_and_size_keep_frames_timing_and_loop(self):
        path = self.animation("gif")
        before = self.animation_info(path)
        for target in ({"quality": 75}, {"max_bytes": 1}, {"format": "gif", "quality": 70}):
            with self.subTest(target=target):
                result = self.run_recipe([], paths=[path], target=target)
                self.assertEqual(result["status"], "completed", result)
                after = self.animation_info(result["outputs"][0])
                self.assertEqual(after, before)
                if "max_bytes" in target:
                    self.assertFalse(result["constraints_met"])

    def test_37_webp_and_apng_quality_and_size_preserve_animation(self):
        for extension, poster in (("webp", False), ("png", False), ("png", True)):
            path = self.animation(extension, poster=poster)
            before = self.animation_info(path)
            for target in ({"quality": 75}, {"max_bytes": 1}):
                with self.subTest(extension=extension, poster=poster, target=target):
                    result = self.run_recipe([], paths=[path], target=target)
                    self.assertEqual(result["status"], "completed", result)
                    after = self.animation_info(result["outputs"][0])
                    self.assertEqual(after["count"], before["count"])
                    self.assertEqual(after["loop"], before["loop"])
                    self.assertEqual(after["poster"], before["poster"])
                    self.assertEqual(after["durations"], before["durations"])
                    for actual, expected in zip(after["colors"], before["colors"]):
                        self.assertTrue(all(abs(a - b) <= 20 for a, b in zip(actual, expected)))

    def test_38_unsupported_animation_conversion_is_explicit_failure(self):
        path = self.animation("gif")
        result = self.run_recipe([{"op": "convert", "format": "jpg"}], paths=[path])
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["outputs"], [])
        self.assertIn("프레임", result["error"])

    def test_39_animation_frame_count_and_pixel_limits_precede_decode(self):
        path = self.animation("gif")
        for field, limit in (("_MAX_FRAMES", 2), ("_MAX_PIXELS", 100)):
            with self.subTest(field=field), patch("workspace_core." + field, limit, create=True):
                result = self.run_recipe([], paths=[path], target={"quality": 75})
                self.assertEqual(result["status"], "failed", result)
                self.assertEqual(result["outputs"], [])
                self.assertTrue("프레임" in result["error"] or "픽셀" in result["error"])

    def test_40_cancel_during_animation_keeps_original_and_no_partial_output(self):
        path = self.animation("gif")
        cancel = threading.Event()
        original = ImageSequence.Iterator.__next__
        count = 0
        def next_frame(iterator):
            nonlocal count
            frame = original(iterator)
            count += 1
            if count == 2:
                cancel.set()
            return frame
        # 두 번째 실제 프레임을 읽은 순간 취소 신호를 주입한다.
        with patch.object(ImageSequence.Iterator, "__next__", next_frame):
            result = self.run_recipe([], paths=[path], target={"quality": 75}, cancel=cancel)
        self.assertEqual(result["status"], "cancelled", result)
        self.assertEqual(result["outputs"], [])
        self.assertEqual(list(self.out.iterdir()), [])

    def test_41_animated_resize_changes_each_frame_and_preserves_timing(self):
        for extension, poster in (("gif", False), ("webp", False), ("png", False), ("png", True)):
            path = self.animation(extension, poster=poster)
            before = self.animation_info(path)
            with self.subTest(extension=extension, poster=poster):
                result = self.run_recipe([{"op": "resize", "width": 40}], paths=[path])
                self.assertEqual(result["status"], "completed", result)
                after = self.animation_info(result["outputs"][0])
                for field in ("count", "loop", "poster", "durations"):
                    self.assertEqual(after[field], before[field])
                with Image.open(result["outputs"][0]) as image:
                    for index in range(image.n_frames):
                        image.seek(index)
                        self.assertEqual(image.size, (40, 30))
                for actual, expected in zip(after["colors"], before["colors"]):
                    self.assertTrue(all(abs(a - b) <= 20 for a, b in zip(actual, expected)))

    def test_42_animated_watermark_changes_all_frames_and_keeps_timing(self):
        mark = self.root / "표시.png"
        Image.new("RGB", (8, 8), "black").save(mark)
        for extension, poster in (("gif", False), ("webp", False), ("png", False), ("png", True)):
            path = self.animation(extension, poster=poster)
            before = self.animation_info(path)
            for step in ({"op": "watermark", "text": "MARK", "font_size": 12, "opacity": 0.9},
                         {"op": "watermark", "image": str(mark), "position": "center", "opacity": 0.9}):
                with self.subTest(extension=extension, poster=poster, step=step):
                    result = self.run_recipe([step], paths=[path])
                    self.assertEqual(result["status"], "completed", result)
                    after = self.animation_info(result["outputs"][0])
                    for field in ("count", "loop", "poster", "durations"):
                        self.assertEqual(after[field], before[field])
                    with Image.open(path) as original, Image.open(result["outputs"][0]) as output:
                        for index in range(original.n_frames):
                            original.seek(index)
                            output.seek(index)
                            difference = ImageChops.difference(original.convert("RGB"), output.convert("RGB"))
                            self.assertIsNotNone(difference.getbbox())

    def test_43_cancel_during_animated_resize_and_watermark_has_no_output(self):
        path = self.animation("gif")
        for step in ({"op": "resize", "width": 40}, {"op": "watermark", "text": "MARK", "font_size": 12}):
            cancel = threading.Event()
            original = ImageSequence.Iterator.__next__
            count = 0
            def next_frame(iterator):
                nonlocal count
                frame = original(iterator)
                count += 1
                if count == 2:
                    cancel.set()
                return frame
            with self.subTest(step=step), patch.object(ImageSequence.Iterator, "__next__", next_frame):
                result = self.run_recipe([step], paths=[path], cancel=cancel)
            self.assertEqual(result["status"], "cancelled", result)
            self.assertEqual(result["outputs"], [])
            self.assertEqual(list(self.out.iterdir()), [])

    def test_44_animated_transform_checks_output_total_and_frame_limit(self):
        path = self.animation("gif")
        result = self.run_recipe([{"op": "resize", "width": 5000, "height": 3000}], paths=[path])
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["outputs"], [])
        self.assertIn("픽셀", result["error"])
        for step in ({"op": "resize", "width": 40}, {"op": "watermark", "text": "MARK"}):
            for field, value in (("_MAX_FRAMES", 2), ("_MAX_PIXELS", 6144)):
                with self.subTest(step=step, field=field), patch("workspace_core." + field, value):
                    result = self.run_recipe([step], paths=[path])
                    self.assertEqual(result["status"], "failed", result)
                    self.assertEqual(result["outputs"], [])
        self.assertEqual(list(self.out.iterdir()), [])

    def test_45_store_count_limit_rejects_new_but_accepts_replacement(self):
        path = self.root / "1000개레시피.json"
        recipes = [{"version": 1, "name": f"레시피{index}", "steps": []} for index in range(1000)]
        path.write_text(json.dumps(recipes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        store = self.core.RecipeStore(path)
        self.assertEqual(len(store.load()), 1000)
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            store.save({"version": 1, "name": "1001번째", "steps": []})
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(store.load()), 1000)
        store.save({"version": 1, "name": "레시피0", "steps": [{"op": "rename", "template": "{name}_{index}"}]})
        after = store.load()
        self.assertEqual(len(after), 1000)
        self.assertEqual(after[0]["steps"][0]["op"], "rename")

    def test_46_store_serialized_byte_limit_preserves_valid_original(self):
        path = self.root / "바이트한도.json"
        store = self.core.RecipeStore(path)
        store.save({"version": 1, "name": "기존", "steps": [{"op": "rename"}]})
        before = path.read_bytes()
        before_hash = self.digest(path)
        too_large = {"version": 1, "name": "큰설정", "steps": [{"op": "watermark", "text": "한" * 10000}] * 100}
        encoded = (json.dumps([too_large], ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        self.assertGreater(len(encoded), 2 * 1024 * 1024)
        with self.assertRaises(ValueError):
            store.save(too_large)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.digest(path), before_hash)
        self.assertEqual(store.load()[0]["name"], "기존")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))[0]["name"], "기존")
        self.assertFalse(any(item.name.startswith(".flipring-recipes-") for item in self.root.iterdir()))


if __name__ == "__main__":
    unittest.main()
