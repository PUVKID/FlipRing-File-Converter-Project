"""문서 지원 안내·미리보기의 실제 Qt 표시와 입력 상태 보존 검사."""
from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import Qt, QRect
from PySide6.QtWidgets import QApplication, QLabel
import app
from preview_panel import PreviewPanel


APPLICATION = QApplication.instance() or QApplication([])
APPLICATION.setQuitOnLastWindowClosed(False)


class DocumentUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.previous_data = app.DATA
        app.DATA = Path(cls.temporary.name) / '격리설정'
        app.apply_application_style(APPLICATION)
        cls.window = app.MainWindow()
        cls.window.timer.stop()

    @classmethod
    def tearDownClass(cls):
        cls.window.quick_actions_panel.shutdown()
        cls.window.workspace_panel.shutdown()
        cls.window.timer.stop()
        cls.window.wheel.hide()
        cls.window.tray.hide()
        cls.window.hide()
        cls.window.pool.shutdown(wait=True)
        app.DATA = cls.previous_data
        cls.temporary.cleanup()

    def test_support_card_distinguishes_input_and_output_without_losing_language(self):
        # 입력과 출력이 한 목록으로 합쳐지거나 언어 갱신이 누락되면 실패한다.
        window = self.window
        window.set_language('ko')
        self.assertTrue(hasattr(window, 'document_support'))
        labels = [item.text() for item in window.document_support.findChildren(QLabel)]
        self.assertIn('입력 형식', labels)
        self.assertIn('출력 형식', labels)
        self.assertTrue(any('DOCX' in text and 'DOC' in text for text in labels))
        window.set_language('en')
        labels = [item.text() for item in window.document_support.findChildren(QLabel)]
        self.assertIn('Input formats', labels)
        self.assertIn('Output formats', labels)
        self.assertIn('Spreadsheets', labels)
        self.assertEqual(window.tabs.count(), 8)
        window.set_language('ko')

    def test_document_metadata_does_not_claim_unreadable_or_start_conversion(self):
        # 알려진 문서를 이미지로 열어 손상 오류로 오인하거나 결과를 만들면 실패한다.
        path = Path(self.temporary.name) / '아직변환하지않은.docx'
        path.write_bytes(b'not a rendered document')
        before = set(path.parent.iterdir())
        panel = PreviewPanel()
        try:
            panel.set_paths(path)
            self.assertEqual(panel.panels[0][1].text(), 'DOCX')
            self.assertIn('PDF로 변환', panel.panels[0][2].text())
            self.assertTrue(panel.panels[0][3].isEnabled())
            self.assertTrue(panel.images[0].isNull())
            panel.set_language('en')
            self.assertIn('Convert to PDF', panel.panels[0][2].text())
            self.assertEqual(set(path.parent.iterdir()), before)
            self.assertEqual(path.read_bytes(), b'not a rendered document')
        finally:
            panel.deleteLater()

    def test_hwp_readiness_keeps_cached_observation_when_language_changes(self):
        # 설치 누락을 사용 가능으로 보이거나 번역 때 관측을 바꾸면 실패한다.
        window = self.window
        window.set_language('en')
        previous = getattr(window, '_hwp_status', None)
        window._hwp_status = {'code': 'missing_oxt', 'ready': False,
                              'message': 'H2Orestart extension missing', 'oxt': '', 'java': 'java.exe'}
        try:
            window.set_language('ko')
            self.assertTrue(hasattr(window, 'hwp_status_label'))
            self.assertIn('H2Orestart', window.hwp_status_label.text())
            self.assertIn('필요', window.hwp_status_label.text())
            window.set_language('en')
            self.assertIn('required', window.hwp_status_label.text())
            self.assertEqual(window._hwp_status['code'], 'missing_oxt')
            self.assertFalse(window._hwp_status['ready'])
            window._hwp_status = {'code': 'ready', 'ready': True, 'message': '',
                                  'oxt': 'extension.oxt', 'java': 'java.exe'}
            window.render_tools()
            self.assertIn('Available', window.hwp_status_label.text())
        finally:
            if previous is None:
                del window._hwp_status
            else:
                window._hwp_status = previous
            window.set_language('ko')

    def test_document_support_wraps_and_remains_reachable_by_scrolling(self):
        # 새 확장자가 늘어났을 때 문구가 잘리거나 가로 영역 밖으로 나가면 실패한다.
        window = self.window
        window.show()
        window.tabs.setCurrentIndex(1)
        try:
            for language in ('ko', 'en'):
                window.set_language(language)
                APPLICATION.processEvents()
                for label, unused_kind, unused_position in window.document_format_labels:
                    self.assertGreaterEqual(label.width(), 150)
                    required = label.fontMetrics().boundingRect(
                        QRect(0, 0, label.contentsRect().width(), 10000),
                        Qt.TextWordWrap, label.text()).height()
                    self.assertLessEqual(required, label.height() + 2)
                scroll = window.tabs.widget(1)
                scroll.ensureWidgetVisible(window.hwp_status_label)
                APPLICATION.processEvents()
                point = window.hwp_status_label.mapTo(scroll.viewport(), window.hwp_status_label.rect().center())
                self.assertTrue(scroll.viewport().rect().contains(point))
        finally:
            window.hide()
            window.set_language('ko')


if __name__ == '__main__':
    unittest.main()
