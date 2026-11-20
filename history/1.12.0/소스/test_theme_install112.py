"""테마와 자동 설치 경계의 최소 검사. 실제 도구는 설치하지 않는다."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QEventLoop, QTimer, QProcess, QSettings
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QWidget, QLabel

from theme_manager import manager, theme_color, ring_color
from tool_installer import ToolInstaller, install_arguments, refresh_process_path


class ThemeInstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_01_theme_surfaces_and_custom_paint(self):
        from ui_motion import make_file_dialog, MotionMessageBox
        from studio_ui import Toggle
        theme = manager(self.app)
        root = QWidget()
        label = QLabel('한글 English', root)
        label.setStyleSheet('background:#ffffff;color:#242424;')
        theme.apply('dark')
        picker = make_file_dialog(root, '선택')
        message = MotionMessageBox(root)
        toggle = Toggle(root)
        self.app.processEvents()
        self.assertLess(self.app.palette().color(QPalette.Base).lightness(), 70)
        self.assertNotIn('background:#ffffff', label.styleSheet())
        self.assertNotIn('background:#fafafa', picker.styleSheet())
        self.assertGreater(theme_color('#242424').lightness(), 180)
        self.assertGreater(ring_color('#ffffff').lightness(), 240)
        self.assertFalse(toggle.grab().isNull())
        theme.apply('light')
        self.assertEqual(label.styleSheet(), 'background:#ffffff;color:#242424;')
        self.assertGreater(self.app.palette().color(QPalette.Base).lightness(), 240)
        theme.apply('system')
        self.assertEqual(theme.mode, 'system')
        picker.deleteLater(); message.deleteLater(); root.deleteLater()

    def test_02_install_allowlist_and_missing_manager(self):
        args = install_arguments('ffmpeg')
        self.assertEqual(args[:4], ['install', '--id', 'Gyan.FFmpeg', '--exact'])
        self.assertNotIn('--ignore-security-hash', args)
        with self.assertRaises(ValueError):
            install_arguments('ffmpeg & calc')
        installer = ToolInstaller()
        results = []
        installer.finished.connect(lambda *result: results.append(result))
        with patch('tool_installer.shutil.which', return_value=None):
            self.assertFalse(installer.start('pandoc'))
        self.assertEqual(results[0][1:3], ('missing', -1))
        self.assertFalse(installer.is_busy())

    def test_03_async_failure_and_cancel(self):
        installer = ToolInstaller()
        results = []
        installer.finished.connect(lambda *result: results.append(result))
        actual_start = QProcess.start
        def fake_start(process, program, arguments):
            self.assertEqual(program, 'winget-test.exe')
            self.assertEqual(arguments, install_arguments('pandoc'))
            actual_start(process, sys.executable, ['-B', '-c', 'import sys; sys.exit(7)'])
        loop = QEventLoop()
        installer.finished.connect(loop.quit)
        with patch('tool_installer.shutil.which', return_value='winget-test.exe'), patch.object(QProcess, 'start', fake_start):
            self.assertTrue(installer.start('pandoc'))
            QTimer.singleShot(5000, loop.quit)
            loop.exec()
        self.assertFalse(installer.is_busy())
        self.assertEqual(results[-1][1:3], ('failed', 7))
        def waiting_start(process, program, arguments):
            actual_start(process, sys.executable, ['-B', '-c', 'import time; time.sleep(10)'])
        with patch('tool_installer.shutil.which', return_value='winget-test.exe'), patch.object(QProcess, 'start', waiting_start):
            self.assertTrue(installer.start('pandoc'))
            QTimer.singleShot(50, installer.cancel)
            QTimer.singleShot(5000, loop.quit)
            loop.exec()
        self.assertFalse(installer.is_busy())
        self.assertEqual(results[-1][1], 'cancelled')

    def test_04_app_theme_persistence_and_pages(self):
        import app
        with tempfile.TemporaryDirectory() as temp, patch.object(app, 'DATA', Path(temp)):
            app.apply_application_style(self.app)
            window = app.MainWindow()
            window.timer.stop()
            self.assertEqual(app.RELEASE_VERSION, '1.12.0')
            self.assertEqual(app.VERSION, 3)
            self.assertEqual(window.tabs.count(), 8)
            for mode in ('dark', 'light'):
                window.theme_combo.setCurrentIndex(window.theme_combo.findData(mode))
                self.app.processEvents()
                self.assertEqual(window.settings.value('theme'), mode)
                for index in range(8):
                    window.tabs.setCurrentIndex(index)
                    self.assertFalse(window.tabs.currentWidget().grab().isNull())
                self.assertFalse(window.wheel.grab().isNull())
            window.set_language('en')
            self.assertEqual(window.nav_buttons[7].text(), 'Quick actions')
            self.assertEqual(window.theme_combo.itemText(0), 'Light')
            saved = QSettings(str(Path(temp) / 'settings-3.ini'), QSettings.IniFormat)
            self.assertEqual(saved.value('theme'), 'light')
            window.quick_actions_panel.shutdown()
            window.workspace_panel.shutdown()
            window.pdf_panel.shutdown()
            window.pool.shutdown(wait=False)
            window.tray.hide()
            window.wheel.deleteLater()
            window.deleteLater()


if __name__ == '__main__':
    unittest.main()
