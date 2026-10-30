"""Qt 드롭·모션·키 상태 회귀 시험. 실제 탐색기/물리 Shift 시험과 구분한다."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import string
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt, QPoint, QPointF, QMimeData, QUrl, QEvent, QAbstractAnimation, QCoreApplication
from PySide6.QtGui import QFont, QFontDatabase, QFontInfo, QRawFont, QTextLayout, QPalette, QDragEnterEvent, QDragMoveEvent, QDropEvent, QMouseEvent
from PySide6.QtTest import QTest, QSignalSpy
from PySide6.QtWidgets import QApplication, QFileDialog, QDialogButtonBox, QMessageBox, QStyleOptionComboBox
from shiboken6 import isValid
import app
import i18n
from pdf_panel import ERRORS as PDF_ERRORS
from pdf_tools import PdfToolError


ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path("gui-test-output").resolve()
ROOT.mkdir(parents=True, exist_ok=True)
SOURCE = ROOT / "원본보존-드롭시험.png"
SOURCE2 = ROOT / "두번째.png"
app.engine.Image.new("RGBA", (48, 32), (30, 130, 240, 140)).save(SOURCE)
app.engine.Image.new("RGB", (32, 32), "orange").save(SOURCE2)
ORIGINAL_HASH = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
app.DATA = ROOT / "격리설정"
APPLICATION = QApplication([])
APPLICATION.setQuitOnLastWindowClosed(False)
REGISTERED_TEST_FONTS = {}
if APPLICATION.platformName() == "offscreen":
    # Windows의 offscreen 플러그인은 시스템 글꼴을 열거하지 않는다. 시험 프로세스에만 등록한다.
    for name in ("segoeui.ttf", "seguisb.ttf", "malgun.ttf", "malgunbd.ttf"):
        filename = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
        REGISTERED_TEST_FONTS[name] = QFontDatabase.addApplicationFont(str(filename))
app.apply_application_style(APPLICATION)


def mime_for(*urls):
    mime = QMimeData()
    mime.setUrls(list(urls) or [QUrl.fromLocalFile(str(SOURCE))])
    return mime


def drop_at(point, mime=None, actions=Qt.CopyAction | Qt.MoveAction):
    mime = mime if mime is not None else mime_for()
    event = QDropEvent(point, actions, mime, Qt.LeftButton, Qt.ShiftModifier)
    # QDropEvent는 MIME 객체를 소유하지 않으므로 모의 이벤트가 끝날 때까지 참조를 유지한다.
    event._mime_reference = mime
    return event


def settle(milliseconds=190):
    QTest.qWait(milliseconds)
    APPLICATION.processEvents()


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.window = app.MainWindow()
        cls.window.timer.stop()
        cls.window.notifications.setChecked(False)
        cls.window.reveal.setChecked(False)
        cls.wheel = cls.window.wheel
        cls.wheel.chosen.disconnect()
        cls.events = []
        cls.wheel.chosen.connect(lambda files, target: cls.events.append((files, target)))

    @classmethod
    def tearDownClass(cls):
        cls.window.timer.stop()
        cls.wheel.hide()
        cls.window.tray.hide()
        cls.window.hide()
        cls.window.pool.shutdown(wait=True)

    def setUp(self):
        self.events.clear()
        self.wheel.hide()
        self.window.start_point = None
        self.window.drag_fired = False
        self.window.explorer_drag = False
        self.window.release_time = None
        self.window.recording = False
        self.window.trigger.setCurrentIndex(0)
        self.window.set_language("ko")

    def show_wheel(self, paths=None, preview=False):
        self.wheel.display(QPoint(500, 380), paths or [str(SOURCE)], preview)
        APPLICATION.processEvents()

    def test_01_compact_settings_and_tray(self):
        self.assertEqual(self.window.tabs.count(), 5)
        self.assertEqual([self.window.tabs.tabText(i) for i in range(4)], ["설정", "도구", "기록", "정보"])
        self.assertIs(self.window.tabs.widget(4), self.window.pdf_panel)
        self.assertLessEqual(self.window.width(), 460)
        self.assertFalse(hasattr(self.window, "list"))
        self.window.update_tray_menu()
        texts = [action.text() for action in self.window.tray_menu.actions()]
        for text in ["파일 선택…", "폴더 선택…", "드래그 키", "로그인 시 시작", "결과 파일 선택", "변환 알림", "도우미 도구", "기록", "설정", "정보", "종료"]:
            self.assertIn(text, texts)
        self.window.show()
        APPLICATION.processEvents()
        self.assertTrue(self.window.grab().save(str(ROOT / "3차-간단설정.png")))
        self.window.hide()

    def test_02_common_formats_preserved(self):
        self.show_wheel([str(SOURCE), str(SOURCE2), str(SOURCE)])
        self.assertEqual(len(self.wheel.paths), 2)
        self.assertEqual(self.wheel.options, ["jpg", "webp", "tiff", "avif", "bmp", "pdf"])
        self.assertTrue(all(reason is None for reason in self.wheel.reasons.values()))
        text = ROOT / "별도.txt"
        text.write_text("한글", encoding="utf-8")
        self.wheel.set_paths([str(SOURCE), str(text)])
        self.assertEqual(self.wheel.options, ["jpg", "pdf"])

    def test_03_copy_overrides_shift_move(self):
        self.show_wheel()
        mime = mime_for()
        event = QDragEnterEvent(QPoint(170, 170), Qt.CopyAction | Qt.MoveAction,
                                mime, Qt.LeftButton, Qt.ShiftModifier)
        self.wheel.dragEnterEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertEqual(event.dropAction(), Qt.CopyAction)
        move = QDragMoveEvent(QPoint(220, 80), Qt.CopyAction | Qt.MoveAction,
                              mime, Qt.LeftButton, Qt.ShiftModifier)
        self.wheel.dragMoveEvent(move)
        self.assertTrue(move.isAccepted())
        self.assertEqual(move.dropAction(), Qt.CopyAction)

    def test_04_center_cancel_consumes_without_conversion(self):
        self.show_wheel()
        event = drop_at(QPointF(170, 170))
        self.wheel.dropEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertEqual(event.dropAction(), Qt.CopyAction)
        self.assertEqual(self.events, [])
        settle()
        self.assertFalse(self.wheel.isVisible())

    def test_05_valid_sector_drop_once(self):
        self.show_wheel()
        point = QPointF(220, 80)
        self.assertEqual(self.wheel.region(point), 0)
        event = drop_at(point)
        self.wheel.dropEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertEqual(self.events, [([str(SOURCE)], "jpg")])
        duplicate = drop_at(point)
        self.wheel.dropEvent(duplicate)
        self.assertFalse(duplicate.isAccepted())
        self.assertEqual(len(self.events), 1)

    def test_06_move_only_drag_is_rejected(self):
        self.show_wheel()
        mime = mime_for()
        event = QDragEnterEvent(QPoint(220, 80), Qt.MoveAction, mime, Qt.LeftButton, Qt.ShiftModifier)
        self.wheel.dragEnterEvent(event)
        self.assertFalse(event.isAccepted())
        drop = drop_at(QPointF(220, 80), mime, Qt.MoveAction)
        self.wheel.dropEvent(drop)
        self.assertFalse(drop.isAccepted())
        self.assertEqual(self.events, [])

    def test_07_remote_or_mixed_or_missing_urls_rejected(self):
        self.show_wheel()
        cases = [
            mime_for(QUrl("https://example.invalid/input.png")),
            mime_for(QUrl.fromLocalFile(str(SOURCE)), QUrl("https://example.invalid/input.png")),
            mime_for(QUrl.fromLocalFile(str(ROOT / "없는파일.png"))),
            QMimeData(),
        ]
        for mime in cases:
            with self.subTest(urls=[url.toString() for url in mime.urls()]):
                enter = QDragEnterEvent(QPoint(220, 80), Qt.CopyAction | Qt.MoveAction,
                                        mime, Qt.LeftButton, Qt.ShiftModifier)
                self.wheel.dragEnterEvent(enter)
                self.assertFalse(enter.isAccepted())
                event = drop_at(QPointF(220, 80), mime)
                self.wheel.dropEvent(event)
                self.assertFalse(event.isAccepted())
        self.assertEqual(self.events, [])

    def test_08_disabled_target_preserves_copy_and_no_job(self):
        self.show_wheel()
        audio = ROOT / "도구없는.wav"
        audio.write_bytes(b"RIFF-test")
        with patch.object(app.engine, "tool", return_value=None), patch.object(self.window, "notify") as notice:
            self.wheel.set_paths([str(audio)])
            event = drop_at(QPointF(220, 80), mime_for(QUrl.fromLocalFile(str(audio))))
            self.wheel.dropEvent(event)
            self.assertTrue(event.isAccepted())
            self.assertEqual(event.dropAction(), Qt.CopyAction)
            self.assertEqual(self.events, [])
            notice.assert_called_once_with("도우미 도구 필요", "FFmpeg를 설치해 주세요.")

    def test_09_outer_area_consumes_without_conversion(self):
        self.show_wheel()
        event = drop_at(QPointF(2, 2))
        self.wheel.dropEvent(event)
        self.assertEqual(event.dropAction(), Qt.CopyAction)
        self.assertTrue(event.isAccepted())
        self.assertEqual(self.events, [])

    def test_10_motion_has_intermediate_frames_fixed_geometry(self):
        self.show_wheel()
        geometry = self.wheel.geometry()
        settle(45)
        self.assertGreater(self.wheel.reveal, 0)
        self.assertLess(self.wheel.reveal, 1)
        self.assertEqual(self.wheel.geometry(), geometry)
        self.assertEqual(self.wheel.windowOpacity(), 1.0)
        self.assertTrue(self.wheel.acceptDrops())
        self.wheel.grab().save(str(ROOT / "3차-모션중간.png"))
        settle(235)
        self.assertAlmostEqual(self.wheel.reveal, 1)
        self.wheel.set_hover(0)
        settle(40)
        self.assertGreater(self.wheel.weights.get(0, 0), 0)
        self.assertLess(self.wheel.weights.get(0, 0), 1)
        settle(135)
        self.assertAlmostEqual(self.wheel.weights[0], 1)
        self.wheel.grab().save(str(ROOT / "3차-원본형메뉴.png"))
        self.wheel.dismiss()
        settle(40)
        self.assertTrue(self.wheel.isVisible())
        self.assertGreater(self.wheel.reveal, 0)
        self.assertLess(self.wheel.reveal, 1)
        self.assertFalse(self.wheel.acceptDrops())
        settle(170)
        self.assertFalse(self.wheel.isVisible())

    def test_11_reopen_interrupts_stale_close_animation(self):
        self.show_wheel()
        settle()
        self.wheel.dismiss()
        settle(35)
        self.wheel.display(QPoint(600, 400), [str(SOURCE2)], True)
        settle()
        self.assertTrue(self.wheel.isVisible())
        self.assertFalse(self.wheel._closing)
        self.assertTrue(self.wheel.acceptDrops())
        self.assertEqual(self.wheel.paths, [str(SOURCE2)])

    def test_12_fast_drop_during_entrance(self):
        self.show_wheel()
        event = drop_at(QPointF(220, 80))
        self.wheel.dropEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertEqual(self.events[-1][1], "jpg")
        settle()
        self.assertFalse(self.wheel.isVisible())

    def test_13_screen_edge_clamping(self):
        bounds = APPLICATION.primaryScreen().availableGeometry()
        for point in [bounds.topLeft(), bounds.bottomRight()]:
            self.wheel.display(point, [str(SOURCE)])
            self.assertTrue(bounds.contains(self.wheel.geometry()))

    def test_14_preview_click_selects_and_right_click_does_not(self):
        self.show_wheel(preview=True)
        event = QMouseEvent(QMouseEvent.MouseButtonRelease, QPointF(220, 80),
                            Qt.RightButton, Qt.NoButton, Qt.NoModifier)
        self.wheel.mouseReleaseEvent(event)
        self.assertEqual(self.events, [])
        self.assertFalse(self.wheel._closing)
        event = QMouseEvent(QMouseEvent.MouseButtonRelease, QPointF(220, 80),
                            Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
        self.wheel.mouseReleaseEvent(event)
        self.assertEqual(self.events, [([str(SOURCE)], "jpg")])

    def test_15_preview_escape_without_mouse_button(self):
        self.show_wheel(preview=True)
        settle()
        with patch.object(app, "down", side_effect=lambda vk: vk == 0x1B):
            self.window.poll()
        settle()
        self.assertFalse(self.wheel.isVisible())

    def test_16_explorer_trigger_after_real_threshold_model(self):
        class Native:
            @staticmethod
            def GetForegroundWindow():
                return 123

            @staticmethod
            def GetClassNameW(hwnd, buffer, length):
                buffer.value = "CabinetWClass"

        keys = {1, 0x10}
        with patch.object(app, "USER32", Native()), patch.object(app, "down", side_effect=lambda vk: vk in keys), \
                patch.object(app.QCursor, "pos", side_effect=[QPoint(100, 100), QPoint(104, 104), QPoint(140, 140), QPoint(180, 180)]):
            self.window.poll()
            self.assertFalse(self.window.drag_fired)
            self.window.poll()
            self.assertFalse(self.window.drag_fired)
            self.window.poll()
            self.assertTrue(self.window.drag_fired)
            geometry = self.wheel.geometry()
            self.window.poll()
            self.assertEqual(self.wheel.geometry(), geometry)
            self.assertTrue(self.wheel.isVisible())

    def test_17_non_explorer_does_not_trigger_model(self):
        class Native:
            @staticmethod
            def GetForegroundWindow():
                return 456

            @staticmethod
            def GetClassNameW(hwnd, buffer, length):
                buffer.value = "Notepad"

        with patch.object(app, "USER32", Native()), patch.object(app, "down", side_effect=lambda vk: vk in {1, 0x10}), \
                patch.object(app.QCursor, "pos", side_effect=[QPoint(100, 100), QPoint(180, 180)]):
            self.window.poll()
            self.window.poll()
        self.assertFalse(self.window.drag_fired)
        self.assertFalse(self.wheel.isVisible())

    def test_18_release_grace_allows_queued_drop_model(self):
        self.show_wheel()
        settle()
        self.window.start_point = QPoint(100, 100)
        with patch.object(app, "down", return_value=False), patch.object(app.time, "monotonic", return_value=100):
            self.window.poll()
        self.assertEqual(self.window.release_time, 100)
        self.assertFalse(self.wheel._closing)
        with patch.object(app, "down", return_value=False), patch.object(app.time, "monotonic", return_value=100.34):
            self.window.poll()
        self.assertFalse(self.wheel._closing)
        with patch.object(app, "down", return_value=False), patch.object(app.time, "monotonic", return_value=100.36):
            self.window.poll()
        self.assertTrue(self.wheel._closing)

    def test_19_custom_key_recording_and_hint_model(self):
        self.window.record_key()
        with patch.object(app, "down", side_effect=lambda vk: vk == 0x77):
            self.window.poll()
        self.assertFalse(self.window.recording)
        self.assertEqual(self.window.custom_vk, 0x77)
        self.assertEqual(self.window.trigger.currentData(), -1)
        self.assertIn("119", self.window.subtitle.text())
        self.window.record_key()
        with patch.object(app, "down", side_effect=lambda vk: vk == 0x1B):
            self.window.poll()
        self.assertFalse(self.window.recording)

    def test_20_conversion_queue_history_and_original_hash(self):
        self.window.enqueue([str(SOURCE)], "jpg")
        deadline = time.monotonic() + 10
        while self.window.pending and time.monotonic() < deadline:
            settle(25)
        self.assertEqual(self.window.pending, 0)
        row = self.window.records[-1]
        self.assertEqual(row["error"], "")
        output = Path(row["output"])
        self.assertTrue(output.is_file())
        self.assertNotEqual(output, SOURCE)
        self.assertEqual(output.parent, SOURCE.parent)
        with app.engine.Image.open(output) as image:
            image.verify()
        self.assertEqual(hashlib.sha256(SOURCE.read_bytes()).hexdigest(), ORIGINAL_HASH)
        self.assertTrue(self.window.history_path.is_file())
        self.assertFalse(self.window.progress.isVisible())

    def test_21_history_schema_error_preserves_bytes(self):
        before = self.window.history_path.read_bytes() if self.window.history_path.exists() else None
        broken = b'{"not":"a history list"}'
        self.window.history_path.write_bytes(broken)
        other = app.MainWindow()
        other.timer.stop()
        other.notifications.setChecked(False)
        self.assertTrue(hasattr(other, "history_error"))
        self.assertEqual(other.history_path.read_bytes(), broken)
        other.tray.hide()
        other.wheel.hide()
        other.hide()
        other.pool.shutdown(wait=True)
        if before is not None:
            self.window.history_path.write_bytes(before)

    def test_22_settings_drop_opens_manual_wheel(self):
        mime = mime_for()
        enter = QDragEnterEvent(QPoint(100, 100), Qt.CopyAction | Qt.MoveAction,
                                mime, Qt.LeftButton, Qt.ShiftModifier)
        self.window.dragEnterEvent(enter)
        self.assertTrue(enter.isAccepted())
        self.assertEqual(enter.dropAction(), Qt.CopyAction)
        event = drop_at(QPointF(100, 100), mime)
        self.window.dropEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertEqual(event.dropAction(), Qt.CopyAction)
        self.assertTrue(self.wheel.isVisible())
        self.assertTrue(self.wheel.preview)
        self.assertEqual(self.wheel.paths, [str(SOURCE)])
        self.assertEqual(self.events, [])
        rejected = drop_at(QPointF(100, 100), mime, Qt.MoveAction)
        self.window.dropEvent(rejected)
        self.assertFalse(rejected.isAccepted())

    def test_23_language_switch_preserves_trigger_and_wheel(self):
        self.window.custom_vk = 65
        self.window.settings.setValue("custom_vk", 65)
        self.window.trigger.setCurrentIndex(self.window.trigger.findData(-1))
        self.show_wheel()
        geometry = self.wheel.geometry()
        paths, options = self.wheel.paths.copy(), self.wheel.options.copy()
        old_values = {key: self.window.settings.value(key) for key in ("trigger", "custom_vk", "notify", "reveal")}
        changed = QSignalSpy(self.window.trigger.currentIndexChanged)
        self.window.language_combo.setCurrentIndex(self.window.language_combo.findData("en"))
        self.assertEqual(self.window.language, "en")
        self.assertEqual(self.window.windowTitle(), "FlipRing Settings")
        self.assertEqual(self.window.tabs.tabText(0), "Settings")
        self.assertEqual(self.window.trigger.currentData(), -1)
        self.assertEqual(self.window.custom_vk, 65)
        self.assertEqual(self.window.trigger.currentText(), "Custom")
        self.assertEqual(changed.count(), 0)
        self.assertEqual({key: self.window.settings.value(key) for key in old_values}, old_values)
        self.assertEqual(self.wheel.geometry(), geometry)
        self.assertEqual(self.wheel.paths, paths)
        self.assertEqual(self.wheel.options, options)
        self.assertTrue(self.wheel.isVisible())
        self.assertIn("Custom key (65)", self.window.subtitle.text())
        self.assertIn("Choose files…", [action.text() for action in self.window.tray_menu.actions()])
        self.window.show()
        APPLICATION.processEvents()
        self.assertTrue(self.window.grab().save(str(ROOT / "Mono-English-settings.png")))
        self.window.hide()

    def test_24_language_persists_when_window_recreated(self):
        self.window.set_language("en")
        self.window.settings.sync()
        script = (
            "import json,pathlib; from PySide6.QtWidgets import QApplication; import app; "
            f"app.DATA=pathlib.Path({str(app.DATA)!r}); q=QApplication([]); app.apply_application_style(q); w=app.MainWindow(); "
            "w.timer.stop(); print(json.dumps({'language':w.language,'tab':w.tabs.tabText(0)})); "
            "w.tray.hide(); w.wheel.hide(); w.pool.shutdown(wait=True)"
        )
        restarted = subprocess.run([sys.executable, "-B", "-X", "utf8", "-c", script],
                                   cwd=Path(app.__file__).parent, capture_output=True, text=True,
                                   encoding="utf-8", timeout=10, check=False)
        self.assertEqual(restarted.returncode, 0, restarted.stderr)
        self.assertEqual(json.loads(restarted.stdout), {"language": "en", "tab": "Settings"})
        other = app.MainWindow()
        try:
            other.timer.stop()
            self.assertEqual(other.language, "en")
            self.assertEqual(other.language_combo.currentData(), "en")
            self.assertEqual(other.tabs.tabText(2), "History")
            self.assertEqual(other.settings.value("language"), "en")
            self.assertEqual(other.settings.fileName(), self.window.settings.fileName())
        finally:
            other.timer.stop()
            other.tray.hide()
            other.wheel.hide()
            other.hide()
            other.pool.shutdown(wait=True)
            self.window.set_language("ko")
        self.window.show()
        APPLICATION.processEvents()
        self.assertTrue(self.window.grab().save(str(ROOT / "Mono-Korean-settings.png")))
        self.window.hide()

    def test_25_translation_placeholders_are_complete(self):
        formatter = string.Formatter()
        values = {"app": "FlipRing", "key": "F8", "tool": "FFmpeg", "count": 2,
                  "name": "원본.jpg", "error": "Example", "detail": "OS diagnostic"}
        for message_id, pair in i18n.TEXT.items():
            with self.subTest(message_id=message_id):
                fields = [{name for _, name, _, _ in formatter.parse(text) if name} for text in pair]
                self.assertEqual(fields[0], fields[1])
                for language in ("ko", "en"):
                    self.assertNotIn("\ufffd", i18n.tr(language, message_id, **values))

    def test_26_engine_errors_are_translated_without_mutating_records(self):
        for korean, english in i18n.ERROR_TEXT.items():
            self.assertEqual(i18n.error_text("en", korean), english)
            self.assertEqual(i18n.error_text("ko", korean), korean)
            self.assertIsNone(re.search("[가-힣]", english))
        for korean, english in [
            ("지원하지 않는 파일입니다: sample.foo", "Unsupported file: sample.foo"),
            ("LibreOffice에서 PDF 결과를 만들지 못했습니다.", "LibreOffice did not produce a PDF result."),
            ("FFmpeg 도구를 설치해 주세요. 설정에서 설치 명령을 복사할 수 있습니다.", "Install FFmpeg. You can copy the install command in Settings."),
            ("ffmpeg 변환 실패 (2)\ncodec error", "ffmpeg conversion failed (2)\ncodec error"),
        ]:
            self.assertEqual(i18n.error_text("en", korean), english)
        original = self.window.records.copy()
        row = {"time": "2026-10-21T00:00:00", "source": str(SOURCE), "output": "",
               "error": "지원하지 않는 변환입니다."}
        self.window.records = [row]
        self.window.last_result = ("", row["error"])
        try:
            self.window.set_language("en")
            self.assertIn("Failed: This conversion is not supported.", self.window.history.item(0).text())
            self.assertIn(SOURCE.name, self.window.history.item(0).text())
            self.assertEqual(row["error"], "지원하지 않는 변환입니다.")
            self.assertEqual(self.window.status.text(), "Failed · This conversion is not supported.")
        finally:
            self.window.records = original
            self.window.last_result = None
            self.window.set_language("ko")

    def test_27_monochrome_palette_wheel_icons_and_bundled_font(self):
        for color in re.findall(r"#[0-9a-fA-F]{6}", self.window.styleSheet()):
            self.assertEqual(color[1:3], color[3:5])
            self.assertEqual(color[3:5], color[5:7])
        for role in (QPalette.Window, QPalette.WindowText, QPalette.Base, QPalette.Text,
                     QPalette.Highlight, QPalette.Button, QPalette.ButtonText, QPalette.Accent):
            color = APPLICATION.palette().color(role)
            self.assertEqual(color.red(), color.green())
            self.assertEqual(color.green(), color.blue())
        self.assertEqual(app.ui_font().families()[:2], ["SUIT", "Segoe UI"])
        self.assertIn("Malgun Gothic", app.ui_font().families())
        self.assertEqual(app.ui_font().weight(), QFont.Normal)
        self.assertEqual(APPLICATION.font().weight(), QFont.Normal)
        self.assertEqual(QFontInfo(app.ui_font()).family(), "SUIT")
        self.assertEqual(QFontInfo(APPLICATION.font()).family(), "SUIT")
        self.assertEqual(set(APPLICATION._flipring_fonts), {"Regular", "Medium", "SemiBold"})
        self.assertTrue(all(value >= 0 for value in APPLICATION._flipring_fonts.values()))
        self.assertTrue(all(value >= 0 for value in REGISTERED_TEST_FONTS.values()))
        self.show_wheel()
        settle()
        self.wheel.set_hover(0)
        settle(120)
        pixmaps = [app.icon(busy=False).pixmap(64, 64), app.icon(busy=True).pixmap(64, 64), self.wheel.grab()]
        for pixmap in pixmaps:
            image = pixmap.toImage()
            for y in range(image.height()):
                for x in range(image.width()):
                    color = image.pixelColor(x, y)
                    if color.alpha():
                        self.assertEqual(color.red(), color.green())
                        self.assertEqual(color.green(), color.blue())
        self.assertTrue(self.wheel.grab().save(str(ROOT / "Mono-monochrome-wheel.png")))

    def test_28_recording_and_busy_status_follow_language(self):
        self.window.record_key()
        self.window.set_language("en")
        self.assertEqual(self.window.record_button.text(), "Press a key · Esc to cancel")
        self.window.pending = 2
        try:
            self.window.update_status()
            self.assertEqual(self.window.status.text(), "Converting · 2 remaining")
            self.window.set_language("ko")
            self.assertEqual(self.window.status.text(), "변환 중 · 2개 대기")
            self.assertEqual(self.window.record_button.text(), "사용할 키를 누르세요 · Esc 취소")
        finally:
            self.window.pending = 0
            self.window.recording = False
            self.window.update_record_label()
            self.window.update_status()

    def test_29_dialog_labels_and_standard_buttons_follow_language(self):
        for language, open_text, cancel_text in (("ko", "열기", "취소"), ("en", "Open", "Cancel")):
            self.window.set_language(language)
            notice = app.message_dialog(self.window, self.window.text("busy_title"), self.window.text("busy_message"))
            self.assertEqual(notice.icon(), QMessageBox.NoIcon)
            self.assertEqual(notice.button(QMessageBox.Ok).text().replace("&", ""), "확인" if language == "ko" else "OK")
            notice.deleteLater()
            dialog = self.window.file_dialog(False)
            try:
                self.assertTrue(dialog.testOption(QFileDialog.DontUseNativeDialog))
                self.assertEqual(dialog.labelText(QFileDialog.Accept), open_text)
                self.assertEqual(dialog.labelText(QFileDialog.Reject), cancel_text)
                self.assertEqual(dialog.labelText(QFileDialog.FileName), self.window.text("dialog_filename"))
                box = dialog.findChild(QDialogButtonBox)
                self.assertIsNotNone(box)
                self.assertEqual(box.button(QDialogButtonBox.Cancel).text().replace("&", ""), cancel_text)
                self.assertEqual(QApplication.translate("QFileSystemModel", "Name"), "이름" if language == "ko" else "Name")
                self.assertEqual(QApplication.translate("QFileDialog", "Unmapped diagnostic"), "Unmapped diagnostic")
                dialog.resize(660, 430)
                dialog.show()
                APPLICATION.processEvents()
                self.assertTrue(dialog.grab().save(str(ROOT / f"Mono-{language}-file-dialog.png")))
            finally:
                dialog.hide()
                dialog.deleteLater()
        self.window.set_language("ko")

    def test_30_autostart_value_is_language_independent(self):
        class Key:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch.object(app.winreg, "CreateKey", return_value=Key()), \
                patch.object(app.winreg, "SetValueEx") as write, \
                patch.object(app.winreg, "DeleteValue") as delete:
            self.window.set_language("en")
            self.window.autostart(True)
            self.assertEqual(write.call_args.args[1], "FlipRing")
            self.window.set_language("ko")
            self.window.autostart(False)
            self.assertEqual(delete.call_args.args[1], "FlipRing")
        self.assertEqual(app.DATA, ROOT / "격리설정")

    def test_31_history_double_click_selects_result_without_running_it(self):
        output = ROOT / "기록 & [선택] 한글.png"
        output.write_bytes("결과 파일".encode("utf-8"))
        self.window.records = [{"time": "2026-10-21T12:00:00", "source": str(SOURCE),
                                "output": str(output), "error": ""}]
        self.window.refresh_history()
        item = self.window.history.item(0)
        self.assertEqual(item.data(Qt.UserRole), str(output))
        with patch.object(app, "select_in_explorer") as launch:
            self.window.tabs.setCurrentIndex(2)
            self.window.show()
            APPLICATION.processEvents()
            point = self.window.history.visualItemRect(item).center()
            QTest.mouseClick(self.window.history.viewport(), Qt.LeftButton, pos=point)
            launch.assert_not_called()
            QTest.mouseDClick(self.window.history.viewport(), Qt.LeftButton, pos=point)
            APPLICATION.processEvents()
        launch.assert_called_once_with(output)
        with patch.object(app, "select_in_explorer") as launch:
            QTest.mouseDClick(self.window.history.viewport(), Qt.RightButton, pos=point)
            APPLICATION.processEvents()
            launch.assert_not_called()
        self.window.hide()
        output.unlink()

    def test_32_history_failure_and_missing_result_show_bilingual_guidance(self):
        rows = [
            {"time": "2026-10-21T12:00:00", "source": str(SOURCE), "output": "",
             "error": "지원하지 않는 변환입니다."},
            {"time": "2026-10-21T12:01:00", "source": str(SOURCE),
             "output": str(ROOT / "이동되었거나 삭제된 결과.png"), "error": ""},
        ]
        for language, expected in (
                ("ko", ["실패한 변환 기록에는 선택할 결과 파일이 없습니다.", "결과 파일이 없거나 폴더입니다."]),
                ("en", ["Failed conversions do not have a result file to select.",
                        "The result is missing or is a folder."])):
            self.window.records = rows
            self.window.set_language(language)
            self.window.refresh_history()
            with patch.object(app, "select_in_explorer") as launch, \
                    patch.object(app, "message_dialog", return_value=Mock()) as dialog:
                self.window.open_history_result(self.window.history.item(1))
                self.window.open_history_result(self.window.history.item(0))
            self.assertEqual(dialog.call_count, 2)
            self.assertIn(expected[0], dialog.call_args_list[0].args[2])
            self.assertIn(expected[1], dialog.call_args_list[1].args[2])
            launch.assert_not_called()
        self.window.set_language("ko")
        self.window.records = []
        self.window.refresh_history()

    def test_33_history_non_record_rows_and_directories_do_not_open_explorer(self):
        directory = ROOT / "기록에 저장된 폴더"
        directory.mkdir(exist_ok=True)
        self.window.records = [{"time": "2026-10-21T12:00:00", "source": str(SOURCE),
                                "output": str(directory), "error": ""}]
        self.window.refresh_history()
        self.window.history.addItem("기록 오류 안내")
        with patch.object(app, "select_in_explorer") as launch, \
                patch.object(app, "message_dialog", return_value=Mock()) as dialog:
            self.window.open_history_result(self.window.history.item(0))
            self.window.open_history_result(self.window.history.item(1))
        launch.assert_not_called()
        self.assertEqual(dialog.call_count, 1)
        directory.rmdir()
        self.window.records = []
        self.window.refresh_history()
        self.window.set_language("ko")

    def test_34_history_explorer_failure_and_empty_output_are_explained(self):
        output = ROOT / "선택 가능한 결과.png"
        output.write_bytes(b"result")
        original = self.window.records.copy()
        try:
            for language in ("ko", "en"):
                self.window.set_language(language)
                self.window.records = [{"time": "2026-10-21T12:00:00", "source": str(SOURCE),
                                        "output": str(output), "error": ""}]
                self.window.refresh_history()
                with patch.object(app, "select_in_explorer", side_effect=OSError("Unavailable")), \
                        patch.object(app, "message_dialog", return_value=Mock()) as dialog:
                    self.window.open_history_result(self.window.history.item(0))
                self.assertEqual(dialog.call_args.args[1], self.window.text("history_explorer_title"))
                self.assertIn("Unavailable", dialog.call_args.args[2])
                self.window.records[0]["output"] = ""
                self.window.refresh_history()
                with patch.object(app, "select_in_explorer") as launch, \
                        patch.object(app, "message_dialog", return_value=Mock()) as dialog:
                    self.window.open_history_result(self.window.history.item(0))
                launch.assert_not_called()
                self.assertEqual(dialog.call_args.args[1], self.window.text("history_missing_title"))
        finally:
            output.unlink()
            self.window.records = original
            self.window.set_language("ko")
            self.window.refresh_history()

    def test_35_pdf_panel_language_and_tab_contract(self):
        self.assertEqual(self.window.tabs.count(), 5)
        self.assertIs(self.window.tabs.widget(4), self.window.pdf_panel)
        for language in ("en", "ko"):
            with patch.object(self.window.pdf_panel, "set_language",
                              wraps=self.window.pdf_panel.set_language) as change:
                self.window.set_language(language)
            change.assert_called_once_with(language)
            self.assertEqual(self.window.tabs.tabText(4), self.window.text("pdf_tools"))
            self.window.tabs.setCurrentIndex(4)
            self.window.show()
            APPLICATION.processEvents()
            self.assertTrue(self.window.grab().save(str(ROOT / f"FlipRing-{language}-pdf-panel.png")))
        self.window.hide()

    def test_36_pdf_result_signal_uses_history_without_changing_queue(self):
        output = ROOT / "PDF 패널 결과.pdf"
        app.engine.Image.new("RGB", (20, 20), "white").save(output, "PDF")
        pending = self.window.pending
        self.window.pdf_panel.result_ready.emit(str(SOURCE), str(output), "")
        APPLICATION.processEvents()
        self.assertEqual(self.window.pending, pending)
        row = self.window.records[-1]
        self.assertEqual(set(row), {"time", "source", "output", "error"})
        self.assertEqual(row["output"], str(output))
        self.assertEqual(row["source"], str(SOURCE))
        self.assertEqual(row["error"], "")
        self.assertEqual(self.window.history.item(0).data(Qt.UserRole), str(output))
        self.assertEqual(json.loads(self.window.history_path.read_text(encoding="utf-8"))[-1], row)
        self.assertEqual(hashlib.sha256(SOURCE.read_bytes()).hexdigest(), ORIGINAL_HASH)

    def test_37_pdf_busy_blocks_quit(self):
        with patch.object(self.window.pdf_panel, "is_busy", return_value=True), \
                patch.object(app, "message_dialog", return_value=Mock()) as dialog, \
                patch.object(self.window.pool, "shutdown") as shutdown, \
                patch.object(app.QApplication, "quit") as quitting:
            self.window.quit()
        self.assertEqual(dialog.call_args.args[1], self.window.text("busy_title"))
        shutdown.assert_not_called()
        quitting.assert_not_called()

    def test_38_pdf_busy_blocks_other_conversion_queue(self):
        pending, records = self.window.pending, self.window.records.copy()
        with patch.object(self.window.pdf_panel, "is_busy", return_value=True), \
                patch.object(app, "message_dialog", return_value=Mock()) as dialog, \
                patch.object(self.window.pool, "submit") as submit:
            self.window.enqueue([str(SOURCE)], "jpg")
        self.assertEqual(dialog.call_args.args[1], self.window.text("busy_title"))
        submit.assert_not_called()
        self.assertEqual(self.window.pending, pending)
        self.assertEqual(self.window.records, records)

    def test_39_pdf_standard_error_pairs_follow_current_language(self):
        for code, pair in PDF_ERRORS.items():
            for stored in pair:
                with self.subTest(code=code, stored=stored):
                    self.assertEqual(i18n.error_text("ko", stored), pair[0])
                    self.assertEqual(i18n.error_text("en", stored), pair[1])
        self.assertEqual(i18n.error_text("ko", "Unrecognized OS diagnostic"), "Unrecognized OS diagnostic")
        self.assertEqual(i18n.error_text("en", "Unrecognized OS diagnostic"),
                         "External tool or system error: Unrecognized OS diagnostic")

    def test_40_pdf_error_history_status_and_notifications_switch_both_ways(self):
        records, last_result = self.window.records.copy(), self.window.last_result
        old_error = self.window.pdf_panel._error
        before = self.window.history_path.read_bytes() if self.window.history_path.exists() else None
        pending = self.window.pending
        try:
            for origin, destination in (("ko", "en"), ("en", "ko")):
                for code, pair in PDF_ERRORS.items():
                    with self.subTest(origin=origin, destination=destination, code=code):
                        self.window.set_language(origin)
                        with patch.object(self.window, "notify") as notice:
                            self.window.pdf_panel._on_error(PdfToolError(code, source=str(SOURCE)))
                        stored = pair[origin == "en"]
                        self.assertEqual(self.window.records[-1]["error"], stored)
                        notice.assert_called_once_with(self.window.text("failed_title"), SOURCE.name + "\n" + stored)
                        self.window.set_language(destination)
                        expected = pair[destination == "en"]
                        self.assertIn(expected, self.window.history.item(0).text())
                        self.assertEqual(self.window.status.text(), self.window.text("failed_status", error=expected[:90]))
                        self.assertEqual(self.window.records[-1]["error"], stored)
                        saved = json.loads(self.window.history_path.read_text(encoding="utf-8"))[-1]
                        self.assertEqual(saved["error"], stored)
                        self.assertEqual(set(saved), {"time", "source", "output", "error"})
                        with patch.object(self.window, "notify") as notice:
                            self.window.pdf_finished(str(SOURCE), "", stored)
                        notice.assert_called_once_with(self.window.text("failed_title"), SOURCE.name + "\n" + expected)
                        self.assertEqual(self.window.pending, pending)
                        if code == "invalid_pdf":
                            self.window.tabs.setCurrentIndex(2)
                            self.window.show()
                            APPLICATION.processEvents()
                            self.assertTrue(self.window.grab().save(str(ROOT / f"FlipRing-{destination}-pdf-error-history.png")))
                            self.window.hide()
        finally:
            self.window.records, self.window.last_result = records, last_result
            self.window.pdf_panel._error = old_error
            self.window.set_language("ko")
            self.window.refresh_history()
            self.window.update_status()
            if before is not None:
                self.window.history_path.write_bytes(before)

    def shell_mocks(self, initialize=0, parse=0, select=0, pointer=0x12345678ABCDEF00):
        # 실제 탐색기나 운영체제 COM 상태를 변경하지 않는 계약 시험 대역이다.
        ole, shell = Mock(), Mock()
        ole.CoInitializeEx.return_value = initialize

        def parse_name(filename, binding, result, flags, attributes):
            app.ctypes.cast(result, app.ctypes.POINTER(app.ctypes.c_void_p))[0] = pointer
            return parse

        shell.SHParseDisplayName.side_effect = parse_name
        shell.SHOpenFolderAndSelectItems.return_value = select
        return ole, shell

    def test_41_shell_api_uses_signed_hresult_and_pointer_sized_pidls(self):
        self.assertEqual(app.ctypes.sizeof(app.ctypes.c_int32), 4)
        self.assertEqual(app.ctypes.sizeof(app.ctypes.c_void_p), 8)
        for function in (app.OLE32.CoInitializeEx, app.SHELL32.SHParseDisplayName,
                         app.SHELL32.SHOpenFolderAndSelectItems):
            self.assertIs(function.restype, app.ctypes.c_int32)
        self.assertEqual(app.OLE32.CoInitializeEx.argtypes, [app.ctypes.c_void_p, app.wintypes.DWORD])
        self.assertEqual(app.SHELL32.SHParseDisplayName.argtypes,
                         [app.wintypes.LPCWSTR, app.ctypes.c_void_p,
                          app.ctypes.POINTER(app.ctypes.c_void_p), app.wintypes.ULONG,
                          app.ctypes.POINTER(app.wintypes.ULONG)])
        self.assertEqual(app.SHELL32.SHOpenFolderAndSelectItems.argtypes,
                         [app.ctypes.c_void_p, app.wintypes.UINT,
                          app.ctypes.POINTER(app.ctypes.c_void_p), app.wintypes.DWORD])
        self.assertEqual(app.OLE32.CoTaskMemFree.argtypes, [app.ctypes.c_void_p])
        self.assertIsNone(app.OLE32.CoTaskMemFree.restype)
        self.assertEqual(app.OLE32.CoUninitialize.argtypes, [])
        self.assertIsNone(app.OLE32.CoUninitialize.restype)

    def test_42_shell_selects_full_unicode_file_pidl_and_balances_both_com_successes(self):
        filename = ROOT / "한글 공백 & [선택] 결과.pdf"
        for initialized in (0, 1):
            with self.subTest(initialized=initialized):
                ole, shell = self.shell_mocks(initialize=initialized)
                calls = Mock()
                for name, function in (("initialize", ole.CoInitializeEx),
                                       ("parse", shell.SHParseDisplayName),
                                       ("select", shell.SHOpenFolderAndSelectItems),
                                       ("free", ole.CoTaskMemFree),
                                       ("uninitialize", ole.CoUninitialize)):
                    calls.attach_mock(function, name)
                with patch.object(app, "OLE32", ole), patch.object(app, "SHELL32", shell):
                    app.select_in_explorer(filename)
                ole.CoInitializeEx.assert_called_once_with(None, 0x2)
                parsed = shell.SHParseDisplayName.call_args.args
                self.assertEqual(parsed[:2], (str(filename.resolve()), None))
                self.assertEqual(parsed[3:], (0, None))
                selected = shell.SHOpenFolderAndSelectItems.call_args.args
                self.assertEqual(selected[0].value, 0x12345678ABCDEF00)
                self.assertEqual(selected[1:], (0, None, 0))
                ole.CoTaskMemFree.assert_called_once_with(selected[0])
                ole.CoUninitialize.assert_called_once_with()
                self.assertEqual([entry[0] for entry in calls.mock_calls],
                                 ["initialize", "parse", "select", "free", "uninitialize"])

    def test_43_shell_com_failure_preserves_existing_com_and_reports_signed_hresult(self):
        for result in (0x80010106, app.ctypes.c_int32(0x80010106).value):
            with self.subTest(result=result):
                ole, shell = self.shell_mocks(initialize=result)
                with patch.object(app, "OLE32", ole), patch.object(app, "SHELL32", shell):
                    with self.assertRaisesRegex(OSError, r"CoInitializeEx.*0x80010106"):
                        app.select_in_explorer(SOURCE)
                shell.SHParseDisplayName.assert_not_called()
                shell.SHOpenFolderAndSelectItems.assert_not_called()
                ole.CoTaskMemFree.assert_not_called()
                ole.CoUninitialize.assert_not_called()

    def test_44_shell_parse_failure_releases_any_returned_memory_and_com(self):
        for pointer in (None, 0x12345678ABCDEF00):
            with self.subTest(pointer=pointer):
                ole, shell = self.shell_mocks(parse=0x80070002, pointer=pointer)
                with patch.object(app, "OLE32", ole), patch.object(app, "SHELL32", shell):
                    with self.assertRaisesRegex(OSError, r"SHParseDisplayName.*0x80070002"):
                        app.select_in_explorer(SOURCE)
                shell.SHOpenFolderAndSelectItems.assert_not_called()
                if pointer is None:
                    ole.CoTaskMemFree.assert_not_called()
                else:
                    self.assertEqual(ole.CoTaskMemFree.call_args.args[0].value, pointer)
                    self.assertEqual(ole.CoTaskMemFree.call_count, 1)
                ole.CoUninitialize.assert_called_once_with()

    def test_45_shell_selection_failure_releases_pidl_and_com(self):
        ole, shell = self.shell_mocks(select=app.ctypes.c_int32(0x80004005).value)
        with patch.object(app, "OLE32", ole), patch.object(app, "SHELL32", shell):
            with self.assertRaisesRegex(OSError, r"SHOpenFolderAndSelectItems.*0x80004005"):
                app.select_in_explorer(SOURCE)
        self.assertEqual(ole.CoTaskMemFree.call_args.args[0].value, 0x12345678ABCDEF00)
        self.assertEqual(ole.CoTaskMemFree.call_count, 1)
        ole.CoUninitialize.assert_called_once_with()

    def test_46_shell_empty_pidl_does_not_open_a_folder(self):
        ole, shell = self.shell_mocks(pointer=None)
        with patch.object(app, "OLE32", ole), patch.object(app, "SHELL32", shell):
            with self.assertRaisesRegex(OSError, r"SHParseDisplayName.*0x80004005"):
                app.select_in_explorer(SOURCE)
        shell.SHOpenFolderAndSelectItems.assert_not_called()
        ole.CoTaskMemFree.assert_not_called()
        ole.CoUninitialize.assert_called_once_with()

    def test_47_optional_result_reveal_uses_same_api_and_keeps_conversion_success(self):
        records, last_result = self.window.records.copy(), self.window.last_result
        reveal = self.window.reveal.isChecked()
        before = self.window.history_path.read_bytes() if self.window.history_path.exists() else None
        output = ROOT / "완료 후 선택 결과.png"
        output.write_bytes(b"result")
        try:
            self.window.reveal.setChecked(True)
            with patch.object(app, "select_in_explorer") as select:
                self.window.append_record(str(SOURCE), str(output), "")
            select.assert_called_once_with(str(output))
            for language in ("ko", "en"):
                self.window.set_language(language)
                with patch.object(app, "select_in_explorer", side_effect=OSError("HRESULT 0x80004005")), \
                        patch.object(app, "message_dialog", return_value=Mock()) as dialog:
                    self.window.append_record(str(SOURCE), str(output), "")
                self.assertEqual(dialog.call_args.args[1], self.window.text("history_explorer_title"))
                self.assertEqual(dialog.call_args.args[2],
                                 self.window.text("history_explorer_error", detail="HRESULT 0x80004005"))
                self.assertEqual(self.window.records[-1]["error"], "")
                self.assertEqual(self.window.last_result, (str(output), ""))
        finally:
            self.window.reveal.setChecked(reveal)
            self.window.records, self.window.last_result = records, last_result
            self.window.set_language("ko")
            self.window.refresh_history()
            self.window.update_status()
            if before is not None:
                self.window.history_path.write_bytes(before)
            output.unlink()

    def test_48_wheel_reentry_preserves_rendered_progress_and_hit_regions(self):
        point = QPoint(500, 380)
        self.wheel.display(point, [str(SOURCE)])
        self.wheel.motion.setCurrentTime(90)
        geometry = self.wheel.geometry()
        regions = [self.wheel.region(p) for p in (QPointF(170, 170), QPointF(220, 80), QPointF(2, 2))]
        first = self.wheel.reveal
        self.assertGreater(first, 0)
        self.assertLess(first, 1)
        self.assertTrue(self.wheel.grab().save(str(ROOT / "Fluid-wheel-open-middle.png")))
        for attempt in range(3):
            before = self.wheel.reveal
            self.wheel.dismiss()
            self.assertAlmostEqual(self.wheel.reveal, before)
            self.wheel.motion.setCurrentTime(self.wheel.motion.duration() // 3)
            closing = self.wheel.reveal
            self.assertLess(closing, before)
            self.assertGreater(closing, 0)
            if attempt == 0:
                self.assertTrue(self.wheel.grab().save(str(ROOT / "Fluid-wheel-close-middle.png")))
            self.wheel.display(point, [str(SOURCE)])
            self.assertAlmostEqual(self.wheel.reveal, closing)
            self.assertTrue(self.wheel.acceptDrops())
            self.wheel.motion.setCurrentTime(self.wheel.motion.duration() // 2)
            self.assertGreater(self.wheel.reveal, closing)
            self.assertEqual(self.wheel.geometry(), geometry)
            self.assertEqual([self.wheel.region(p) for p in (QPointF(170, 170), QPointF(220, 80), QPointF(2, 2))], regions)
        self.wheel.motion.setCurrentTime(self.wheel.motion.duration())
        self.assertAlmostEqual(self.wheel.reveal, 1)
        self.assertEqual(self.wheel.motion.state(), QAbstractAnimation.Stopped)
        self.assertTrue(self.wheel.grab().save(str(ROOT / "Fluid-wheel-open-full.png")))
        self.assertNotEqual((ROOT / "Fluid-wheel-open-middle.png").read_bytes(),
                            (ROOT / "Fluid-wheel-open-full.png").read_bytes())

    def test_49_fast_hover_retargets_current_weights_and_refreshes_helper_state(self):
        self.show_wheel()
        self.wheel.motion.setCurrentTime(self.wheel.motion.duration())
        geometry = self.wheel.geometry()
        points = (QPointF(170, 170), QPointF(220, 80), QPointF(2, 2))
        regions = [self.wheel.region(point) for point in points]

        def assert_visual_weights_unchanged(expected):
            # 그리기는 누락된 키를 0으로 읽으므로 표현과 무관하게 모든 가중치를 대조한다.
            actual = self.wheel.weights
            keys = set(expected) | set(actual) | {-1} | set(range(len(self.wheel.options)))
            for key in keys:
                self.assertAlmostEqual(actual.get(key, 0.0), expected.get(key, 0.0))
                self.assertTrue(0 <= actual.get(key, 0.0) <= 1)
            self.assertEqual(self.wheel.geometry(), geometry)
            self.assertEqual([self.wheel.region(point) for point in points], regions)

        self.wheel.set_hover(0)
        self.wheel.highlight.setCurrentTime(70)
        before = self.wheel.weights.copy()
        self.assertGreater(before[0], 0)
        self.assertLess(before[0], 1)
        self.assertTrue(self.wheel.grab().save(str(ROOT / "Fluid-hover-first-middle.png")))
        self.wheel.set_hover(1)
        assert_visual_weights_unchanged(before)
        self.wheel.set_paths([str(SOURCE)])
        assert_visual_weights_unchanged(before)
        self.wheel.highlight.setCurrentTime(75)
        self.assertGreater(self.wheel.weights[1], 0)
        self.assertLess(self.wheel.weights[0], before[0])
        self.assertTrue(self.wheel.grab().save(str(ROOT / "Fluid-hover-retarget-middle.png")))
        for target in (2, -1, 0, 1):
            before = self.wheel.weights.copy()
            self.wheel.set_hover(target)
            assert_visual_weights_unchanged(before)
            self.wheel.highlight.setCurrentTime(35)
            self.assertTrue(all(0 <= value <= 1 for value in self.wheel.weights.values()))
        self.wheel.highlight.setCurrentTime(self.wheel.highlight.duration())
        self.assertAlmostEqual(self.wheel.weights[1], 1)
        self.assertEqual(self.wheel.highlight.state(), QAbstractAnimation.Stopped)
        self.assertTrue(all(abs(value) < 0.001 for key, value in self.wheel.weights.items() if key != 1))
        with patch.object(app.engine, "requirement", return_value="test helper") as requirement:
            self.wheel.set_paths([str(SOURCE)])
        self.assertTrue(requirement.called)
        self.assertTrue(all(reason == "test helper" for reason in self.wheel.reasons.values()))
        self.wheel.set_paths([str(SOURCE)])

    def test_50_button_hover_frames_preserve_clicks_geometry_and_idle_state(self):
        button = app.QPushButton("부드러운 버튼 Smooth")
        button.setStyleSheet(self.window.styleSheet())
        button.resize(210, 40)
        motion = app.ButtonMotion(button)
        clicks = QSignalSpy(button.clicked)
        try:
            button.show()
            APPLICATION.processEvents()
            motion.hovered = motion.pressed = False
            motion.animation.stop()
            motion.amount = 0.0
            geometry = button.geometry()
            self.assertTrue(button.grab().save(str(ROOT / "Fluid-button-normal.png")))
            motion.eventFilter(button, QEvent(QEvent.Enter))
            motion.animation.setCurrentTime(65)
            middle = motion.amount
            self.assertGreater(middle, 0)
            self.assertLess(middle, 1)
            self.assertTrue(button.grab().save(str(ROOT / "Fluid-button-hover-middle.png")))
            motion.eventFilter(button, QEvent(QEvent.Leave))
            self.assertAlmostEqual(motion.amount, middle)
            motion.animation.setCurrentTime(motion.animation.duration())
            self.assertAlmostEqual(motion.amount, 0)
            self.assertEqual(motion.animation.state(), QAbstractAnimation.Stopped)
            self.assertEqual(button.geometry(), geometry)
            self.assertNotEqual((ROOT / "Fluid-button-normal.png").read_bytes(),
                                (ROOT / "Fluid-button-hover-middle.png").read_bytes())
            QTest.mouseClick(button, Qt.LeftButton)
            self.assertEqual(clicks.count(), 1)
            QTest.keyClick(button, Qt.Key_Space)
            self.assertEqual(clicks.count(), 2)
            button.setEnabled(False)
            QTest.mouseClick(button, Qt.LeftButton)
            self.assertEqual(clicks.count(), 2)
            self.assertEqual(button.geometry(), geometry)
            for item in self.window.findChildren(app.QPushButton):
                self.assertIsInstance(getattr(item, "_flipring_button_motion", None), app.ButtonMotion)
                self.assertIs(item._flipring_button_motion.parent(), item)
                self.assertEqual([child for child in item.children() if isinstance(child, app.ButtonMotion)],
                                 [item._flipring_button_motion])
        finally:
            button.hide()
            button.deleteLater()

    def test_51_rapid_tab_changes_release_old_effect_without_overlays_or_input_loss(self):
        self.window.show()
        APPLICATION.processEvents()
        tabs = self.window.tabs
        geometry = tabs.geometry()
        old_page = tabs.currentWidget()
        for index in (3, 1, 4, 0, 4):
            tabs.setCurrentIndex(index)
            current = tabs.currentWidget()
            if old_page is not current:
                self.assertIsNone(old_page.graphicsEffect())
            tabs.fade.setCurrentTime(70)
            self.assertGreater(current.graphicsEffect().opacity(), 0.9)
            self.assertLess(current.graphicsEffect().opacity(), 1)
            self.assertTrue(current.isEnabled())
            self.assertFalse(current.testAttribute(Qt.WA_TransparentForMouseEvents))
            self.assertEqual(tabs.geometry(), geometry)
            old_page = current
        self.assertTrue(self.window.grab().save(str(ROOT / "Fluid-tab-middle.png")))
        tabs.fade.setCurrentTime(tabs.fade.duration())
        self.assertIsNone(tabs.currentWidget().graphicsEffect())
        self.assertIsNone(tabs._fade_page)
        self.assertEqual(tabs.fade.state(), QAbstractAnimation.Stopped)
        self.assertTrue(self.window.pdf_panel.operation.isEnabled())
        self.assertTrue(self.window.pdf_panel.add_button.isEnabled())
        self.window.hide()
        self.assertIsNone(tabs.currentWidget().graphicsEffect())

    def test_52_drops_during_close_are_rejected_and_reentry_accepts_once(self):
        self.show_wheel()
        self.wheel.motion.setCurrentTime(self.wheel.motion.duration())
        self.wheel.dismiss()
        self.wheel.motion.setCurrentTime(65)
        event = drop_at(QPointF(220, 80))
        self.wheel.dropEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertEqual(self.events, [])
        self.wheel.display(QPoint(500, 380), [str(SOURCE)])
        event = drop_at(QPointF(220, 80))
        self.wheel.dropEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertEqual(event.dropAction(), Qt.CopyAction)
        self.assertEqual(self.events, [([str(SOURCE)], "jpg")])
        repeated = drop_at(QPointF(220, 80))
        self.wheel.dropEvent(repeated)
        self.assertFalse(repeated.isAccepted())
        self.assertEqual(len(self.events), 1)
        self.wheel.motion.setCurrentTime(self.wheel.motion.duration())
        self.assertFalse(self.wheel.isVisible())
        self.assertEqual(hashlib.sha256(SOURCE.read_bytes()).hexdigest(), ORIGINAL_HASH)

    def test_53_bundled_suit_styles_shape_korean_english_and_apply_to_all_pages(self):
        sample = "플립링한국어가나다한글FlipRingEnglish0123456789"
        for style, weight in (("Regular", QFont.Normal), ("Medium", QFont.Medium), ("SemiBold", QFont.DemiBold)):
            font = app.ui_font(12, weight)
            raw = QRawFont.fromFont(font)
            self.assertTrue(raw.isValid())
            self.assertEqual(QFontInfo(font).family(), "SUIT")
            self.assertEqual(raw.familyName(), "SUIT")
            self.assertEqual(raw.styleName(), style)
            self.assertEqual(raw.weight(), int(weight))
            # UCS-4 정수 오버로드로 검사한다. 문자열 오버로드의 한글 거짓 음성과 구분한다.
            self.assertTrue(all(raw.supportsCharacter(ord(character)) for character in sample))
            shaped = QTextLayout(sample, font)
            shaped.beginLayout()
            line = shaped.createLine()
            line.setLineWidth(1500)
            shaped.endLayout()
            self.assertTrue(shaped.glyphRuns())
            for run in shaped.glyphRuns():
                self.assertEqual(run.rawFont().familyName(), "SUIT")
                self.assertTrue(all(glyph > 0 for glyph in run.glyphIndexes()))
        self.window.show()
        for language in ("ko", "en"):
            self.window.set_language(language)
            for index, label in ((0, "settings"), (4, "pdf-ocr")):
                self.window.tabs.setCurrentIndex(index)
                self.window.tabs.fade.setCurrentTime(self.window.tabs.fade.duration())
                APPLICATION.processEvents()
                self.assertTrue(self.window.grab().save(str(ROOT / f"Fluid-{language}-{label}.png")))
            for widget in (self.window.brand, self.window.language_combo, self.window.record_button,
                           self.window.pdf_panel.operation, self.window.pdf_panel.pages,
                           self.window.pdf_panel.start_button, self.window.pdf_panel.status):
                self.assertEqual(QFontInfo(widget.font()).family(), "SUIT")
        self.window.set_language("ko")
        self.window.hide()

    def test_54_live_common_dialog_buttons_have_one_motion_and_keep_native_input(self):
        notice = app.message_dialog(self.window, "확인", "버튼 모션과 입력을 확인합니다.")
        picker = self.window.file_dialog(False)
        dialogs = ((notice, "message"), (picker, "file"))
        try:
            for dialog, label in dialogs:
                with self.subTest(dialog=label):
                    dialog.show()
                    APPLICATION.processEvents()
                    buttons = dialog.findChildren(app.QPushButton)
                    self.assertTrue(buttons)
                    before = [getattr(button, "_flipring_button_motion", None) for button in buttons]
                    self.assertTrue(all(isinstance(motion, app.ButtonMotion) for motion in before))
                    app.install_button_motions(dialog)
                    app.install_button_motions(dialog)
                    self.assertEqual([button._flipring_button_motion for button in buttons], before)
                    for index, button in enumerate(buttons):
                        motion = button._flipring_button_motion
                        self.assertIs(motion.parent(), button)
                        self.assertEqual([child for child in button.children() if isinstance(child, app.ButtonMotion)], [motion])
                        enabled = button.isEnabled()
                        button.setEnabled(True)
                        motion.animation.stop()
                        motion.hovered = motion.pressed = False
                        motion.amount = 0.0
                        geometry = button.geometry()
                        motion.eventFilter(button, QEvent(QEvent.Enter))
                        motion.animation.setCurrentTime(65)
                        middle = motion.amount
                        self.assertGreater(middle, 0)
                        self.assertLess(middle, 1)
                        if index == 0:
                            self.assertTrue(dialog.grab().save(str(ROOT / f"Fluid-live-{label}-buttons.png")))
                        motion.eventFilter(button, QEvent(QEvent.Leave))
                        self.assertAlmostEqual(motion.amount, middle)
                        motion.animation.setCurrentTime(motion.animation.duration())
                        self.assertAlmostEqual(motion.amount, 0)
                        self.assertEqual(motion.animation.state(), QAbstractAnimation.Stopped)
                        self.assertEqual(button.geometry(), geometry)
                        button.setEnabled(enabled)
                    action = (notice.button(QMessageBox.Ok) if dialog is notice else
                              picker.findChild(QDialogButtonBox).button(QDialogButtonBox.Cancel))
                    clicked = QSignalSpy(action.clicked)
                    action.setEnabled(False)
                    QTest.mouseClick(action, Qt.LeftButton)
                    self.assertEqual(clicked.count(), 0)
                    action.setEnabled(True)
                    QTest.mouseClick(action, Qt.LeftButton)
                    self.assertEqual(clicked.count(), 1)
                    dialog.show()
                    APPLICATION.processEvents()
                    QTest.keyClick(action, Qt.Key_Space)
                    self.assertEqual(clicked.count(), 2)
                    dialog.hide()
                    self.assertTrue(all(motion.animation.state() == QAbstractAnimation.Stopped for motion in before))
        finally:
            for dialog, _ in dialogs:
                dialog.hide()
                dialog.deleteLater()

    def test_55_common_dialog_deferred_deletion_releases_button_owned_motions(self):
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        baseline = len(self.window.findChildren(app.QPushButton))
        self.assertFalse(hasattr(self.window, "_button_motions"))
        for create in (lambda: app.message_dialog(self.window, "확인", "수명 확인"),
                       lambda: self.window.file_dialog(False), lambda: self.window.file_dialog(True)):
            dialog = create()
            buttons = dialog.findChildren(app.QPushButton)
            motions = [button._flipring_button_motion for button in buttons]
            animations = [motion.animation for motion in motions]
            self.assertTrue(buttons)
            self.assertTrue(all(isValid(item) for item in buttons + motions + animations))
            dialog.deleteLater()
            self.assertTrue(isValid(dialog))
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.assertFalse(isValid(dialog))
            self.assertTrue(all(not isValid(item) for item in buttons + motions + animations))
            self.assertEqual(len(self.window.findChildren(app.QPushButton)), baseline)

    def test_56_combo_has_flat_frame_visible_arrow_and_unchanged_native_selection(self):
        combo = self.window.trigger
        original_index = combo.currentIndex()
        original_style = self.window.styleSheet()
        source_arrow = app.engine.asset("combo-chevron.svg")
        self.assertFalse(app.QPixmap(str(source_arrow)).isNull())
        spaced = ROOT / "한글 공백 경로"
        spaced.mkdir(exist_ok=True)
        copied_arrow = spaced / "선택 화살표.svg"
        copied_arrow.write_bytes(source_arrow.read_bytes())
        try:
            self.window.tabs.setCurrentIndex(0)
            self.window.show()
            self.window.tabs.fade.setCurrentTime(self.window.tabs.fade.duration())
            APPLICATION.processEvents()
            geometry = combo.geometry()
            with patch.object(app.engine, "asset", return_value=copied_arrow):
                self.window.apply_style()
            APPLICATION.processEvents()
            self.assertEqual(combo.geometry(), geometry)
            image = combo.grab().toImage()
            # 내부 우측에 남던 어두운 입체선과 화살표 소실을 픽셀로 구분한다.
            self.assertTrue(all(image.pixelColor(image.width() - 2, y).red() >= 200
                                for y in range(8, image.height() - 8)))
            arrow_pixels = [image.pixelColor(x, y) for y in range(8, image.height() - 8)
                            for x in range(image.width() - 28, image.width() - 5)]
            self.assertGreater(sum(color.red() < 180 for color in arrow_pixels), 5)
            self.assertTrue(all(color.red() == color.green() == color.blue() for color in arrow_pixels))
            self.assertTrue(combo.grab().save(str(ROOT / "Fluid-combo-flat-arrow.png")))
            option = QStyleOptionComboBox()
            combo.initStyleOption(option)
            arrow_rect = combo.style().subControlRect(app.QStyle.CC_ComboBox, option,
                                                       app.QStyle.SC_ComboBoxArrow, combo)
            self.assertTrue(combo.rect().contains(arrow_rect))
            self.assertGreaterEqual(arrow_rect.width(), 20)
            combo.setCurrentIndex(0)
            QTest.keyClick(combo, Qt.Key_Down)
            self.assertEqual(combo.currentData(), 0x12)
            QTest.mouseClick(combo, Qt.LeftButton, pos=arrow_rect.center())
            APPLICATION.processEvents()
            self.assertTrue(combo.view().isVisible())
            index = combo.model().index(0, 0)
            target = combo.view().visualRect(index).center()
            activated = QSignalSpy(combo.activated)
            # Qt의 팝업 직후 클릭 보호가 실제 행 이동으로 해제되는 입력 순서를 재현한다.
            target_global = combo.view().viewport().mapToGlobal(target)
            movement = QMouseEvent(QEvent.MouseMove, QPointF(target), QPointF(target),
                                   QPointF(target_global), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
            QApplication.sendEvent(combo.view().viewport(), movement)
            self.assertEqual(combo.view().currentIndex().row(), 0)
            QTest.mouseClick(combo.view().viewport(), Qt.LeftButton, pos=target)
            APPLICATION.processEvents()
            self.assertEqual(combo.currentData(), 0x10)
            self.assertEqual(activated.count(), 1)
            self.assertFalse(combo.view().isVisible())
            self.assertEqual(combo.geometry(), geometry)
            combo.setEnabled(False)
            QTest.keyClick(combo, Qt.Key_Down)
            QTest.mouseClick(combo, Qt.LeftButton, pos=arrow_rect.center())
            self.assertEqual(combo.currentData(), 0x10)
            self.assertEqual(activated.count(), 1)
            self.assertFalse(combo.view().isVisible())
            self.assertTrue(combo.grab().save(str(ROOT / "Fluid-combo-disabled.png")))
            combo.setEnabled(True)
            combo.setFocus()
            self.assertTrue(self.window.grab().save(str(ROOT / "Fluid-combo-final-settings.png")))
        finally:
            combo.hidePopup()
            combo.setEnabled(True)
            combo.setCurrentIndex(original_index)
            self.window.setStyleSheet(original_style)
            self.window.tray_menu.setStyleSheet(original_style)
            self.window.hide()

    def test_57_hover_label_contrast_stays_readable_through_rendered_frames(self):
        self.show_wheel()
        self.wheel.motion.setCurrentTime(self.wheel.motion.duration())
        self.assertEqual(self.wheel.options[1], "webp")
        self.assertFalse(self.wheel.reasons["webp"])
        self.wheel.set_hover(1)
        self.wheel.highlight.pause()
        rows = []

        def luminance(shade):
            value = shade / 255
            return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

        for position in (0, 0.25, 0.5, 0.75, 1):
            self.wheel.highlight.setCurrentTime(round(self.wheel.highlight.duration() * position))
            image = self.wheel.grab().toImage()
            background = image.pixelColor(303, 170)
            # 고정 WEBP 라벨 내부만 검사하고 중앙 문구·외곽선·AA 경계 픽셀은 제외한다.
            cores = [image.pixelColor(x, y) for y in range(153, 187) for x in range(240, 304)
                     if image.pixelColor(x, y).alpha() >= 250 and image.pixelColor(x, y).red() >= 238]
            self.assertTrue(cores)
            foreground = max(cores, key=lambda color: color.red())
            self.assertEqual(foreground.red(), foreground.green())
            self.assertEqual(foreground.green(), foreground.blue())
            # 흰 바탕 위에 놓인 최악의 투명 합성까지 포함해 대비를 계산한다.
            paper_background = background.red() * background.alphaF() + 255 * (1 - background.alphaF())
            contrast = (luminance(foreground.red()) + 0.05) / (luminance(paper_background) + 0.05)
            self.assertGreaterEqual(contrast, 4.5)
            rows.append({"animation_position": position, "actual_weight": self.wheel.weights.get(1, 0),
                         "foreground_core": foreground.getRgb(), "background": background.getRgb(),
                         "contrast_on_white": contrast, "glyph_core_pixels": len(cores)})
            if position in (0, 0.5, 1):
                self.assertTrue(self.wheel.grab().save(str(ROOT / f"Fluid-hover-contrast-{position:g}.png")))
        self.wheel.highlight.stop()
        (ROOT / "Fluid-호버대비.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_58_tab_completion_destroys_effect_and_requests_one_background_update(self):
        tabs = self.window.tabs
        self.window.show()
        tabs.setCurrentIndex(0)
        tabs.fade.setCurrentTime(tabs.fade.duration())
        APPLICATION.processEvents()
        geometry = tabs.geometry()
        with patch.object(self.window, "update", wraps=self.window.update) as redraw:
            tabs.setCurrentIndex(4)
            effect = tabs.currentWidget().graphicsEffect()
            self.assertIsInstance(effect, app.QGraphicsOpacityEffect)
            self.assertTrue(isValid(effect))
            page_geometry = tabs.currentWidget().geometry()
            tabs.fade.setCurrentTime(70)
            self.assertGreater(effect.opacity(), 0.9)
            self.assertLess(effect.opacity(), 1)
            self.assertEqual(redraw.call_count, 0)
            tabs.fade.setCurrentTime(tabs.fade.duration())
            self.assertFalse(isValid(effect))
            self.assertIsNone(tabs._fade_page)
            self.assertTrue(all(tabs.widget(i).graphicsEffect() is None for i in range(tabs.count())))
            self.assertEqual(tabs.fade.state(), QAbstractAnimation.Stopped)
            self.assertEqual(redraw.call_count, 1)
            # 완료 뒤 도착한 프레임과 중복 정리는 삭제된 효과를 참조하거나 재갱신하지 않는다.
            tabs._fade_frame(0.95)
            tabs._finish_fade()
            APPLICATION.processEvents()
            self.assertEqual(redraw.call_count, 1)
            self.assertEqual(tabs.geometry(), geometry)
            self.assertEqual(tabs.currentWidget().geometry(), page_geometry)
            self.assertTrue(self.window.pdf_panel.operation.isEnabled())
            self.assertTrue(self.window.grab().save(str(ROOT / "Fluid-tab-complete-clean.png")))
        self.window.hide()

    def test_59_tab_interruption_hide_and_restart_leave_no_idle_effect_or_animation(self):
        tabs = self.window.tabs
        self.window.show()
        tabs.setCurrentIndex(0)
        tabs.fade.setCurrentTime(tabs.fade.duration())
        APPLICATION.processEvents()
        geometry = tabs.geometry()
        previous = None
        for index in (4, 2, 4, 0, 4):
            tabs.setCurrentIndex(index)
            if previous is not None:
                self.assertFalse(isValid(previous))
            effect = tabs.currentWidget().graphicsEffect()
            self.assertTrue(isValid(effect))
            self.assertIsNot(effect, previous)
            tabs.fade.setCurrentTime(55)
            self.assertEqual(sum(tabs.widget(i).graphicsEffect() is not None for i in range(tabs.count())), 1)
            self.assertEqual(tabs.geometry(), geometry)
            self.assertTrue(tabs.currentWidget().isEnabled())
            previous = effect
        self.window.hide()
        self.assertFalse(isValid(previous))
        self.assertIsNone(tabs._fade_page)
        self.assertEqual(tabs.fade.state(), QAbstractAnimation.Stopped)
        self.assertTrue(all(tabs.widget(i).graphicsEffect() is None for i in range(tabs.count())))
        tabs._fade_frame(0.96)
        tabs.setCurrentIndex(0)
        self.assertIsNone(tabs.currentWidget().graphicsEffect())
        self.window.show()
        APPLICATION.processEvents()
        self.assertEqual(tabs.fade.state(), QAbstractAnimation.Stopped)
        self.assertIsNone(tabs.currentWidget().graphicsEffect())
        tabs.setCurrentIndex(4)
        restarted = tabs.currentWidget().graphicsEffect()
        self.assertTrue(isValid(restarted))
        tabs.fade.setCurrentTime(tabs.fade.duration())
        self.assertFalse(isValid(restarted))
        self.assertIsNone(tabs.currentWidget().graphicsEffect())
        self.assertEqual(tabs.fade.state(), QAbstractAnimation.Stopped)
        self.assertEqual(tabs.geometry(), geometry)
        self.window.hide()


def main():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(GuiTests)
    result = unittest.TextTestRunner(verbosity=2, failfast=True).run(suite)
    report = {
        "version": app.VERSION,
        "tests": result.testsRun,
        "passed": result.testsRun - len(result.failures) - len(result.errors),
        "failures": [{"test": str(test), "detail": detail} for test, detail in result.failures],
        "errors": [{"test": str(test), "detail": detail} for test, detail in result.errors],
        "original_sha256": ORIGINAL_HASH,
        "original_preserved": hashlib.sha256(SOURCE.read_bytes()).hexdigest() == ORIGINAL_HASH,
        "qt_platform": APPLICATION.platformName(),
        "scope": "Qt 위젯·그리기·애니메이션·이벤트 전달·이미지 변환과 모형 키 상태 시험. offscreen 플랫폼이면 창은 화면에 표시하지 않습니다. 실제 Windows 탐색기 OLE 드래그 및 물리 Shift 키는 별도 미검증입니다.",
        "os_input_injected": False,
        "registry_writes_tested": False,
        "registered_test_fonts": REGISTERED_TEST_FONTS,
        "windows_system_font_files_copied_or_redistributed": False,
        "bundled_ui_font_files": ["SUIT-Regular.ttf", "SUIT-Medium.ttf", "SUIT-SemiBold.ttf"],
        "shell_selection_api_tested_with_mocks": True,
        "actual_explorer_file_selection_tested": False,
        "bundled_ui_font": "SUIT Regular 400 / Medium 500 / SemiBold 600",
        "motion_scope": "실제 Qt 중간 프레임·재진입 연속성·호버 재지정·탭 전환·고정 드롭 영역을 검사했습니다. 실제 화면 프레임 속도는 별도 확인 범위입니다.",
    }
    (ROOT / "Mono-Qt검증.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in ("failures", "errors")}, ensure_ascii=False))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
