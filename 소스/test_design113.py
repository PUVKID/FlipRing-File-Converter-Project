"""소음 없는 표면 피드백과 세 가지 작업 화면의 연결을 확인한다."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from unittest.mock import patch
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QListWidget, QListWidgetItem, QProgressBar, QMainWindow, QMenu
from ui_motion import ensure_surface_motion, set_reduced_motion
from delivery_ui import DeliveryDialog
from theme_manager import manager


class Design113Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        set_reduced_motion(None, False)
        manager(self.app).apply('light')
        self.app.processEvents()

    def test_typing_does_not_restart_surface_feedback(self):
        edit = QLineEdit()
        motion = ensure_surface_motion(edit)
        edit.show()
        edit.setFocus()
        self.app.processEvents()
        QTest.qWait(300)
        with patch.object(motion, 'pulse') as pulse:
            QTest.keyClicks(edit, 'quiet typing')
            self.assertEqual(edit.text(), 'quiet typing')
            pulse.assert_not_called()
        edit.close()
        edit.deleteLater()

    def test_selection_and_reduced_motion_finish_cleanly(self):
        view = QListWidget()
        view.addItems(['first', 'second'])
        motion = ensure_surface_motion(view)
        view.show()
        self.app.processEvents()
        view.setCurrentRow(1)
        self.assertIsNotNone(motion.overlay.rectangle)
        self.assertEqual(view.currentRow(), 1)
        set_reduced_motion(view, True)
        motion.selection_pulse()
        self.assertEqual(motion.amount, 0.0)
        self.assertFalse(motion.overlay.isVisible())
        view.close()
        view.deleteLater()

    def test_progress_feedback_is_finite_and_throttled(self):
        progress = QProgressBar()
        progress.setRange(0, 1000)
        motion = ensure_surface_motion(progress)
        progress.show()
        self.app.processEvents()
        with patch.object(motion, 'pulse') as pulse:
            for value in range(1001):
                progress.setValue(value)
            self.assertEqual(progress.value(), 1000)
            self.assertLessEqual(pulse.call_count, 3)
            self.assertGreaterEqual(pulse.call_count, 2)
        progress.close()
        progress.deleteLater()

    def test_tabs_show_relevant_controls_and_keep_each_result(self):
        import app as product
        owner = QMainWindow()
        owner.tray_menu = QMenu(owner)
        product.MainWindow.apply_style(owner)
        dialog = DeliveryDialog(owner)
        dialog.show()
        self.app.processEvents()
        try:
            self.assertEqual(dialog.tabs.count(), 3)
            self.assertTrue(dialog.compatibility_button.isVisible())
            self.assertFalse(dialog.metadata_list.isVisible())
            self.assertFalse(dialog.left_canvas.isVisible())
            dialog.details.setPlainText('호환 결과')
            dialog.tabs.setCurrentIndex(1)
            self.assertTrue(dialog.metadata_list.isVisible())
            self.assertFalse(dialog.target_combo.isVisible())
            item = QListWidgetItem('작성자')
            item.setCheckState(Qt.Checked)
            dialog.metadata_list.addItem(item)
            dialog.details.setPlainText('개인정보 결과')
            dialog.output_edit.setText('선택 폴더')
            for theme in ('light', 'dark'):
                manager(self.app).apply(theme)
                for language in ('ko', 'en'):
                    dialog.set_language(language)
                    self.assertEqual(dialog.metadata_list.item(0).checkState(), Qt.Checked)
                    self.assertEqual(dialog.details.toPlainText(), '개인정보 결과')
                    self.assertEqual(dialog.output_edit.text(), '선택 폴더')
                    self.assertFalse(dialog.grab().isNull())
            dialog.tabs.setCurrentIndex(2)
            self.assertTrue(dialog.compare_button.isVisible())
            self.assertTrue(dialog.left_canvas.isVisible())
            self.app.processEvents()
            self.assertGreaterEqual(dialog.page_spin.lineEdit().width(),
                                    dialog.page_spin.fontMetrics().horizontalAdvance(dialog.page_spin.text()))
            dialog.page_spin.setMaximum(3)
            dialog._sync_page_buttons()
            dialog.next_page_button.click()
            self.assertEqual(dialog.page_spin.value(), 2)
            dialog.previous_page_button.click()
            self.assertEqual(dialog.page_spin.value(), 1)
            self.assertFalse(dialog.strip_button.isVisible())
            dialog.details.setPlainText('비교 결과')
            dialog.tabs.setCurrentIndex(0)
            self.assertEqual(dialog.details.toPlainText(), '호환 결과')
            dialog.tabs.setCurrentIndex(1)
            self.assertEqual(dialog.details.toPlainText(), '개인정보 결과')
            dialog.tabs.setCurrentIndex(2)
            self.assertEqual(dialog.details.toPlainText(), '비교 결과')
            dialog._set_busy(True)
            self.assertFalse(dialog.tabs.tabBar().isEnabled())
            self.assertFalse(dialog.compare_button.isEnabled())
            self.assertTrue(dialog.cancel_button.isEnabled())
            dialog._set_busy(False)
            set_reduced_motion(dialog, True)
            dialog.compare_button.setFocus(Qt.TabFocusReason)
            self.app.processEvents()
            self.assertTrue(dialog.compare_button.hasFocus())
        finally:
            dialog.close()
            dialog.deleteLater()
            owner.deleteLater()


if __name__ == '__main__':
    unittest.main()
