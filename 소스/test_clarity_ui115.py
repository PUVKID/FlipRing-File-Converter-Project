"""핵심 탐색·접힌 상세·한영/두 테마·실제 미리보기 연결의 Qt 검사."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import tempfile,unittest
from PIL import Image
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEventLoop,QTimer
from PySide6.QtTest import QTest
import app

APPLICATION=QApplication.instance() or QApplication([])
APPLICATION.setQuitOnLastWindowClosed(False)

class ClarityUiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old_data=app.DATA;app.DATA=Path(self.temp.name)/'data'
        app.apply_application_style(APPLICATION);self.window=app.MainWindow();self.window.timer.stop();self.window.show();APPLICATION.processEvents()
    def tearDown(self):
        w=self.window;w.timer.stop();w.pdf_panel.shutdown();w.workspace_panel.shutdown();w.quick_actions_panel.shutdown();w.pool.shutdown(wait=True);w.tray.hide();w.wheel.hide();w.hide();w.deleteLater();APPLICATION.processEvents();app.DATA=self.old_data;self.temp.cleanup()
    def test_core_navigation_and_optional_panels_stay_quiet(self):
        w=self.window
        for language in ('ko','en'):
            w.set_language(language)
            for theme in ('light','dark'):
                w.theme.apply(theme);APPLICATION.processEvents()
                self.assertEqual([i for i,b in w.nav_buttons.items() if not b.isHidden()],[0,4,2,5])
                self.assertFalse(w.clarity.more.isHidden());self.assertTrue(w.page_description.isHidden());self.assertTrue(w.key_badge.isHidden())
                self.assertTrue(w.preview_panel.isHidden());self.assertTrue(w.clarity.details.isHidden())
                self.assertTrue(w.workspace_panel.visual.isHidden())
                self.assertLessEqual(w.sidebar.width(),180)
    def test_selection_does_not_open_the_wheel_and_recovery_has_exact_action(self):
        w=self.window;p=Path(self.temp.name)/'사진.png';Image.new('RGBA',(60,40),'red').save(p)
        w.receive_files([str(p)]);APPLICATION.processEvents();self.assertFalse(w.wheel.isVisible())
        self.assertTrue(w.clarity.preview_button.isEnabled())
        w.clarity.show_error('FFmpeg 설치가 필요합니다.',str(p));APPLICATION.processEvents();self.assertTrue(w.clarity.recovery.isVisible());self.assertEqual(w.clarity.issue.tool,'ffmpeg');self.assertTrue(w.clarity.details.isHidden())
        w.clarity.details_toggle.setChecked(True);self.assertFalse(w.clarity.details.isHidden());self.assertIn('FFmpeg',w.clarity.details.toPlainText())
    def test_preview_dialog_actual_result_and_close_cleanup(self):
        from preview_dialog import ConversionPreviewDialog
        p=Path(self.temp.name)/'사진.png';Image.new('RGBA',(30,20),'red').save(p);original=p.read_bytes()
        d=ConversionPreviewDialog(self.window,str(p),'jpg');d.show();loop=QEventLoop();timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);d.job.finished.connect(loop.quit);timer.start(15000)
        if d.job.isRunning():loop.exec()
        APPLICATION.processEvents();self.assertFalse(d.is_busy());self.assertIsNotNone(d._outcome[0]);output=Path(d._outcome[0].output);self.assertTrue(output.exists());self.assertIn('실제 결과',d.summary.text());d.reject();self.assertFalse(output.exists());self.assertEqual(p.read_bytes(),original)

    def test_loaded_controls_fit_and_recovery_does_not_stretch(self):
        w=self.window;w._flipring_screen_fit.pending.stop();w.setFixedSize(1160,820)
        p=Path(self.temp.name)/'사진.png';Image.new('RGB',(10,10)).save(p)
        w.receive_files([str(p)]);w.clarity.show_error('FFmpeg 설치가 필요합니다.',str(p));APPLICATION.processEvents();QTest.qWait(200)
        for button in (w.choose_button,w.folder_button):
            point=button.mapTo(w.drop_card,button.rect().bottomRight())
            self.assertTrue(w.drop_card.rect().contains(point))
            self.assertGreaterEqual(button.height(),button.minimumSizeHint().height())
        self.assertLess(w.clarity.recovery.height(),220)

    def test_failed_preview_offers_the_matching_recovery_action(self):
        from unittest.mock import patch
        from preview_dialog import ConversionPreviewDialog
        p=Path(self.temp.name)/'사진.png';Image.new('RGB',(10,10)).save(p)
        with patch('engine.requirement',return_value='FFmpeg'):
            d=ConversionPreviewDialog(self.window,str(p),'jpg');d.show();loop=QEventLoop();d.job.finished.connect(loop.quit);QTimer.singleShot(5000,loop.quit)
            if d.job.isRunning():loop.exec()
            APPLICATION.processEvents();self.assertFalse(d.is_busy());self.assertTrue(hasattr(d,'recovery_button'))
            self.assertTrue(d.recovery_button.isVisible());self.assertIn('FFmpeg',d.recovery_button.text());d.reject()

if __name__=='__main__':unittest.main()
