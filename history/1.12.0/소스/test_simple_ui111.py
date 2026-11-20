"""쉬운 기본 화면과 작업별 고급 설정의 값·입력 보존 검사."""
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QComboBox, QLabel, QLineEdit
from PySide6.QtTest import QTest
import app
import ui_motion

APPLICATION = QApplication.instance() or QApplication([])
APPLICATION.setQuitOnLastWindowClosed(False)


class SimpleUiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.previous_data = app.DATA
        app.DATA = Path(self.directory.name)/'설정'
        app.apply_application_style(APPLICATION)
        self.window = app.MainWindow()
        self.window.timer.stop()
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        self.window.tabs.setCurrentIndex(0)
        self.settle()

    def tearDown(self):
        self.window.pending = 0
        self.window.workspace_panel.shutdown()
        self.window.wheel.hide()
        self.window.tray.hide()
        self.window.pool.shutdown(wait=True)
        self.window.hide()
        app.DATA = self.previous_data
        self.directory.cleanup()

    def settle(self):
        APPLICATION.processEvents()
        QTest.qWait(35)
        APPLICATION.processEvents()

    def choose(self, combo, value):
        index = combo.findData(value)
        self.assertGreaterEqual(index, 0)
        QTest.mouseClick(combo, Qt.LeftButton)
        QTest.keyClick(combo, Qt.Key_Home)
        for unused in range(index):
            QTest.keyClick(combo, Qt.Key_Down)
        QTest.keyClick(combo, Qt.Key_Return)
        self.settle()
        self.assertEqual(combo.currentData(), value)

    def test_fresh_window_starts_simple_and_workspace_remains_accessible(self):
        # 기존 준비 코드의 탭 강제 선택과 분리하여 새 창의 실제 시작 상태를 확인한다.
        fresh = app.MainWindow()
        fresh.timer.stop()
        try:
            self.assertEqual(fresh.tabs.currentIndex(), 0)
            self.assertEqual(fresh.tabs.count(), 7)
            fresh.show()
            fresh.raise_()
            fresh.activateWindow()
            self.settle()
            for language in ('ko', 'en'):
                fresh.set_language(language)
                for reduced in (False, True):
                    fresh.reduced_motion_toggle.setChecked(reduced)
                    QTest.mouseClick(fresh.nav_buttons[6], Qt.LeftButton)
                    self.settle()
                    self.assertEqual(fresh.tabs.currentIndex(), 6)
                    self.assertTrue(fresh.workspace_panel.isVisible())
                    self.assertIs(fresh.tabs.widget(6), fresh.workspace_panel)
                    QTest.mouseClick(fresh.nav_buttons[0], Qt.LeftButton)
                    self.settle()
                    self.assertEqual(fresh.tabs.currentIndex(), 0)
                    self.assertTrue(fresh.choose_button.isVisible())
        finally:
            fresh.workspace_panel.shutdown()
            fresh.pdf_panel.shutdown()
            fresh.pool.shutdown(wait=True)
            fresh.wheel.hide()
            fresh.tray.hide()
            fresh.hide()

    def test_expand_buttons_accept_focused_return_and_space_in_both_languages(self):
        # Enter가 빠지거나 한 번 입력에 두 번 토글되면 펼침 상태와 클릭 수로 드러난다.
        window = self.window
        for language in ('ko', 'en'):
            window.set_language(language)
            for reduced in (False, True):
                window.reduced_motion_toggle.setChecked(reduced)
                panel = window.pdf_panel
                panel.operation.setCurrentIndex(panel.operation.findData('recognize'))
                cases = ((0, window.preset_toggle, window.preset_section),
                         (1, window.document_support_toggle, window.document_support_details),
                         (4, panel.pdf_advanced_toggle, panel._advanced_section))
                for tab, button, section in cases:
                    with self.subTest(language=language, reduced=reduced, button=button.text()):
                        window.tabs.setCurrentIndex(tab)
                        button.setChecked(False)
                        window.raise_()
                        window.activateWindow()
                        self.settle()
                        clicks = []
                        button.clicked.connect(lambda checked, observed=clicks: observed.append(checked))
                        for key, expected in ((Qt.Key_Return, True), (Qt.Key_Return, False),
                                              (Qt.Key_Space, True), (Qt.Key_Space, False)):
                            window.setFocus()
                            button.setFocus(Qt.TabFocusReason)
                            self.settle()
                            self.assertTrue(button.hasFocus())
                            self.assertTrue(button.isVisible())
                            self.assertTrue(button.isEnabled())
                            before = len(clicks)
                            QTest.keyClick(button, key)
                            self.settle()
                            self.assertEqual(len(clicks), before + 1)
                            self.assertEqual(button.isChecked(), expected)
                            self.assertEqual(section.isVisible(), expected)

    def test_primary_action_and_conditional_queue_actions(self):
        window = self.window
        self.assertTrue(window.choose_button.property('primary'))
        self.assertFalse(window.preset_section.isVisible())
        path = Path(self.directory.name)/'원본.png'
        Image.new('RGB', (30, 20)).save(path)
        original = path.read_bytes()
        window.set_files([str(path)])
        self.settle()
        self.assertFalse(window.choose_button.property('primary'))
        self.assertTrue(window.run_button.property('primary'))
        self.assertTrue(window.run_button.isVisible())
        self.assertFalse(window.cancel_button.isVisible())
        self.assertFalse(window.retry_button.isVisible())
        self.assertIn('30 × 20', window.preview_panel.panels[0][2].text())
        window.jobs[0].update(state='failed', format='jpg', error='검사 실패')
        window.refresh_queue()
        self.assertTrue(window.retry_button.isVisible())
        window.pending = 1
        window.refresh_queue()
        self.assertTrue(window.cancel_button.isVisible())
        self.assertFalse(window.retry_button.isVisible())
        self.assertEqual(path.read_bytes(), original)

    def test_presets_can_be_opened_by_keyboard_without_resetting_selection(self):
        window = self.window
        before = window.preset_combo.currentData()
        window.preset_toggle.setFocus()
        QTest.keyClick(window.preset_toggle, Qt.Key_Space)
        self.settle()
        self.assertTrue(window.preset_section.isVisible())
        self.assertTrue(window.preset_combo.isVisible())
        QTest.keyClick(window.preset_toggle, Qt.Key_Space)
        self.settle()
        self.assertFalse(window.preset_section.isVisible())
        self.assertEqual(window.preset_combo.currentData(), before)

    def test_support_details_and_language_keep_readiness_visible(self):
        window = self.window
        window.tabs.setCurrentIndex(1)
        for language in ('en', 'ko'):
            window.set_language(language)
            self.settle()
            self.assertFalse(window.document_support_details.isVisible())
            self.assertTrue(window.hwp_status_label.isVisible())
            self.assertTrue(window.document_dependency_note.isVisible())
            state = dict(window._hwp_status)
            QTest.mouseClick(window.document_support_toggle, Qt.LeftButton)
            self.settle()
            self.assertTrue(window.document_support_details.isVisible())
            self.assertTrue(all(label.isVisible() for label, unused, position in window.document_format_labels))
            self.assertEqual(window._hwp_status, state)
            QTest.mouseClick(window.document_support_toggle, Qt.LeftButton)
            self.settle()

    def test_custom_key_record_is_only_visible_for_custom_trigger(self):
        window = self.window
        window.tabs.setCurrentIndex(5)
        self.assertFalse(window.record_button.isVisible())
        self.choose(window.trigger, -1)
        self.assertTrue(window.record_button.isVisible())
        window.set_language('en')
        self.assertTrue(window.record_button.isVisible())
        self.choose(window.trigger, 0x10)
        self.assertFalse(window.record_button.isVisible())

    def test_pdf_operations_keep_primary_fields_and_preserve_advanced_values(self):
        window = self.window
        window.tabs.setCurrentIndex(4)
        panel = window.pdf_panel
        matrix = {
            'merge': (set(), set()),
            'split': ({'pages'}, set()),
            'extract': ({'pages'}, set()),
            'delete': ({'pages'}, set()),
            'rotate': ({'pages', 'rotation'}, set()),
            'images_to_pdf': (set(), {'dpi'}),
            'pdf_to_images': ({'output'}, {'pages', 'dpi', 'quality'}),
            'compress': ({'compression'}, set()),
            'recognize': ({'ocr_language', 'output'}, {'pages', 'dpi', 'layout'}),
        }
        panel.pages.setText('1,3')
        panel.dpi.setValue(275)
        panel.quality.setValue(75)
        panel.force.setChecked(True)
        for language in ('ko', 'en'):
            window.set_language(language)
            for operation, (primary, advanced) in matrix.items():
                with self.subTest(language=language, operation=operation):
                    if panel.pdf_advanced_toggle.isChecked():
                        QTest.mouseClick(panel.pdf_advanced_toggle, Qt.LeftButton)
                    self.choose(panel.operation, operation)
                    for key in primary:
                        self.assertTrue(panel._labels[key][1].isVisible(), key)
                    for key in advanced:
                        self.assertFalse(panel._labels[key][1].isVisible(), key)
                    self.assertEqual(panel.pdf_advanced_toggle.isVisible(), bool(advanced))
                    if advanced:
                        QTest.mouseClick(panel.pdf_advanced_toggle, Qt.LeftButton)
                        self.settle()
                        for key in advanced:
                            self.assertTrue(panel._labels[key][1].isVisible(), key)
                        QTest.mouseClick(panel.pdf_advanced_toggle, Qt.LeftButton)
                        self.settle()
                    self.assertEqual(panel.pages.text(), '1,3')
                    self.assertEqual(panel.dpi.value(), 275)
                    self.assertEqual(panel.quality.value(), 75)
                    self.assertTrue(panel.force.isChecked())
            self.choose(panel.operation, 'compress')
            self.choose(panel.compression, 'images')
            self.assertTrue(panel.lossy_note.isVisible())
            self.assertTrue(panel.pdf_advanced_toggle.isVisible())
            QTest.mouseClick(panel.pdf_advanced_toggle, Qt.LeftButton)
            self.settle()
            self.assertTrue(panel.dpi.isVisible())
            self.assertTrue(panel.quality.isVisible())
            self.choose(panel.compression, 'lossless')
            self.assertFalse(panel.pdf_advanced_toggle.isVisible())

    def test_reduced_motion_and_folder_labels_keep_escape_and_filters(self):
        window = self.window
        window.reduced_motion_toggle.setChecked(True)
        self.assertTrue(ui_motion.reduced_motion())
        window.tabs.setCurrentIndex(1)
        QTest.mouseClick(window.document_support_toggle, Qt.LeftButton)
        self.settle()
        self.assertTrue(window.document_support_details.isVisible())
        for language, label in (('ko', '폴더 이름:'), ('en', 'Folder name:')):
            window.set_language(language)
            dialog = window.file_dialog(True)
            dialog.setDirectory(self.directory.name)
            dialog.show()
            self.settle()
            try:
                self.assertEqual(dialog.fileMode(), QFileDialog.Directory)
                self.assertEqual(dialog.labelText(QFileDialog.FileName), label)
                self.assertFalse(dialog.findChild(QComboBox, 'fileTypeCombo').isVisible())
                QTest.keyClick(dialog, Qt.Key_Escape)
                self.assertFalse(dialog.isVisible())
                self.assertEqual(dialog.result(), QFileDialog.Rejected)
            finally:
                dialog.hide()
                dialog.deleteLater()
        normal = ui_motion.make_file_dialog(window, 'PDF', name_filter='PDF (*.pdf)')
        normal.show()
        self.settle()
        try:
            self.assertTrue(normal.findChild(QComboBox, 'fileTypeCombo').isVisible())
            self.assertIn('PDF (*.pdf)', normal.nameFilters())
        finally:
            normal.hide()
            normal.deleteLater()


if __name__ == '__main__':
    unittest.main()
