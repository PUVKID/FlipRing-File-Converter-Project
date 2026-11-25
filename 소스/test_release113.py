"""새 OCR 읽기 순서와 통합 화면의 변경 영향만 확인한다."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtCore import QElapsedTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QListWidgetItem
from inspection_ui import InspectionDialog
from theme_manager import manager


class Release113Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dialog = InspectionDialog(paths=[])
        self.dialog.preview_timer.stop()
        self.dialog.left_canvas.set_image(Image.new('RGB', (200, 100), 'white'))
        self.words = [
            {'text': '첫째', 'confidence': 91.0, 'page': 0, 'rect': [.1, .1, .2, .1]},
            {'text': '둘째', 'confidence': 65.0, 'page': 0, 'rect': [.5, .6, .2, .1]},
            {'text': '다음', 'confidence': 94.0, 'page': 1, 'rect': [.2, .2, .2, .1]},
        ]
        self.dialog.recognized = {'words': self.words, 'text': '첫째 둘째\f다음'}
        self.dialog.page_spin.setMaximum(2)

    def tearDown(self):
        self.dialog.preview_timer.stop()
        self.assertTrue(self.dialog.shutdown())
        self.dialog.deleteLater()
        manager(self.app).apply('light')
        self.app.processEvents()

    def test_reading_order_uses_actual_page_words_and_selection(self):
        d = self.dialog
        d.reading_order.setChecked(True)
        self.assertEqual(d.candidate_list.count(), 2)
        self.assertEqual(d.candidate_list.item(1).data(Qt.UserRole)['text'], '둘째')
        d.candidate_list.setCurrentRow(1)
        self.assertEqual(d.left_canvas.highlight, self.words[1]['rect'])
        d.page_spin.setValue(2)
        self.assertEqual(d.candidate_list.count(), 1)
        self.assertEqual(d.candidate_list.item(0).data(Qt.UserRole)['order'], 1)
        self.assertEqual(d.left_canvas.words[0]['text'], '다음')

    def test_order_overlay_and_languages_in_both_themes(self):
        d = self.dialog
        for theme in ('light', 'dark'):
            manager(self.app).apply(theme)
            for language in ('ko', 'en'):
                d.set_language(language)
                d.reading_order.setChecked(True)
                self.assertFalse(d.left_canvas.grab().isNull())
                self.assertIn('#2', d.candidate_list.item(1).text())
                self.assertIn('자동 누락' if language == 'ko' else 'not detected automatically', d.ocr_review_hint.text())
        d.mode = 'compare'
        d._set_mode_visibility()
        self.assertTrue(d.reading_order.isHidden())
        self.assertTrue(d.ocr_review_hint.isHidden())

    def test_main_window_tool_entry_language_reuse_and_busy_gate(self):
        import app as product
        base = Path(__file__).parent.parent / 'work' / '시험환경'
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as temporary, patch.object(product, 'DATA', Path(temporary)):
            window = product.MainWindow()
            window.timer.stop()
            try:
                # 생성 직후 비동기 저널 읽기가 끝난 실제 준비 상태에서 조작한다.
                clock = QElapsedTimer()
                clock.start()
                while window.work_busy() and clock.elapsed() < 10000:
                    self.app.processEvents()
                    QTest.qWait(20)
                self.assertFalse(window.work_busy(), '초기 작업 준비가 끝나지 않았습니다.')
                window.open_delivery_tools()
                self.assertEqual(len(window.delivery_dialogs), 1)
                dialog = window.delivery_dialogs[0]
                window.set_language('en')
                self.assertEqual(dialog.language, 'en')
                self.assertIn('Compatibility', window.delivery_button.text())
                dialog.reject()
                window.open_delivery_tools()
                self.assertIs(window.delivery_dialogs[0], dialog)
                self.assertFalse(dialog.isHidden())
                window.pending = 1
                with patch.object(window, 'notify') as notify:
                    window.open_delivery_tools()
                    notify.assert_called_once()
                window.pending = 0
            finally:
                for dialog in window.delivery_dialogs:
                    self.assertTrue(dialog.shutdown())
                    dialog.hide()
                window.workspace_panel.shutdown()
                window.quick_actions_panel.shutdown()
                window.pool.shutdown(wait=True)
                window.tray.hide()
                window.hide()
                window.deleteLater()
                self.app.processEvents()

    def test_delivery_small_screen_and_language_preserves_selection(self):
        from delivery_ui import DeliveryDialog
        d = DeliveryDialog()
        try:
            item = QListWidgetItem('작성자: 시험')
            item.setCheckState(Qt.Checked)
            d.metadata_list.addItem(item)
            d.details.setPlainText('검사 결과')
            for theme in ('light', 'dark'):
                manager(self.app).apply(theme)
                for language in ('ko', 'en'):
                    d.set_language(language)
                    d.show()
                    self.app.processEvents()
                    d._flipring_screen_fit.fit()
                    self.assertLessEqual(d.width(), d.screen().availableGeometry().width())
                    self.assertEqual(d.metadata_list.item(0).checkState(), Qt.Checked)
                    self.assertEqual(d.details.toPlainText(), '검사 결과')
        finally:
            self.assertTrue(d.shutdown())
            d.hide()
            d.deleteLater()


if __name__ == '__main__':
    unittest.main()
