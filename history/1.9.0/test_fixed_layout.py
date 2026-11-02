"""고정 창·배율 렌더·스크롤 접근과 상태 표시 기한을 실제 Qt에서 검사한다."""
import json
import hashlib
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt, QSize, QPoint, QFileInfo, QAbstractAnimation
from PySide6.QtGui import QFontDatabase, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea, QDialogButtonBox, QLabel, QTreeView
from shiboken6 import isValid
import app
from ui_motion import StateMark, SurfaceMotion, set_reduced_motion

OUT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path('fixed-layout-output').resolve()
OUT.mkdir(parents=True, exist_ok=True)
app.DATA = OUT / '격리설정'
APPLICATION = QApplication([])
APPLICATION.setQuitOnLastWindowClosed(False)
for name in ('segoeui.ttf', 'seguisb.ttf', 'malgun.ttf', 'malgunbd.ttf'):
    QFontDatabase.addApplicationFont(str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / name))
app.apply_application_style(APPLICATION)
OBSERVATIONS = []
SOURCE_ROOT = Path(__file__).resolve().parent
SOURCE_SHA256 = {name: hashlib.sha256((SOURCE_ROOT / name).read_bytes()).hexdigest() for name in (
    'app.py', 'studio_ui.py', 'ui_motion.py', 'preview_panel.py', 'pdf_panel.py', 'i18n.py',
    'fixed_viewport.py', 'test_fixed_layout.py',
    'test_gui.py',
)}


def settle():
    APPLICATION.processEvents()
    QTest.qWait(25)
    APPLICATION.processEvents()


def capture(widget, filename):
    # 정지 배치 검토는 유한 피드백의 종료 장면과 구분해 저장한다.
    for motion in widget.findChildren(SurfaceMotion):
        motion.animation.setCurrentTime(motion.animation.duration())
    APPLICATION.processEvents()
    return widget.grab().save(str(filename))


def expose(widget):
    ancestors = []
    parent = widget.parentWidget()
    while parent:
        if isinstance(parent, QScrollArea):
            ancestors.append(parent)
        parent = parent.parentWidget()
    for scroll in reversed(ancestors):
        scroll.ensureWidgetVisible(widget, 10, 10)
        settle()


class FixedLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.window = app.MainWindow()
        cls.window.timer.stop()
        cls.window.notifications.setChecked(False)
        cls.window.reveal.setChecked(False)
        cls.window.show()
        settle()

    @classmethod
    def tearDownClass(cls):
        cls.window.tray.hide()
        cls.window.hide()
        cls.window.wheel.hide()
        cls.window.pool.shutdown(wait=True)
        cls.window.pdf_panel._pool.shutdown(wait=True)

    def test_01_fixed_size_and_screen_bounds(self):
        window = self.window
        size = window.size()
        self.assertEqual(window.minimumSize(), window.maximumSize())
        self.assertFalse(window.windowFlags() & Qt.WindowMaximizeButtonHint)
        self.assertTrue(window.screen().availableGeometry().contains(window.frameGeometry()))
        bounds = window.screen().availableGeometry()
        if bounds.width() >= 1164 and bounds.height() >= 824:
            self.assertEqual(size, QSize(1160, 820))
        window.resize(700, 500)
        self.assertEqual(window.size(), size)
        OBSERVATIONS.append({'size': size.toTuple(), 'frame': window.frameGeometry().getRect(),
                             'available': bounds.getRect(), 'dpr': window.devicePixelRatioF()})

    def test_02_six_pages_languages_and_sections(self):
        window = self.window
        for language in ('ko', 'en'):
            window.set_language(language)
            window.set_files([])
            for index in range(6):
                window.tabs.setCurrentIndex(index)
                window.tabs.fade.setCurrentTime(window.tabs.fade.duration())
                window.viewport_scroll.horizontalScrollBar().setValue(0)
                window.viewport_scroll.verticalScrollBar().setValue(0)
                settle()
                self.assertTrue(window.nav_buttons[index].isChecked())
                expected_key = ('studio_convert', 'studio_helpers', 'history', 'about', 'pdf_tools', 'settings')[index]
                self.assertEqual(window.tabs.currentIndex(), index)
                self.assertEqual(window.page_title.text(), window.text(expected_key))
                self.assertTrue(capture(window, OUT / f'{language}-page-{index}.png'))
                OBSERVATIONS.append({'image': f'{language}-page-{index}.png', 'tab_index': index,
                                     'page_title': window.page_title.text(), 'nav_checked': index})
                self.assertGreaterEqual(window.page_title.height(), window.page_title.fontMetrics().height())
            window.tabs.setCurrentIndex(0)
            settle()
            gap = window.preset_combo.mapTo(window.preset_heading.parentWidget(), QPoint()).y() - window.preset_heading.geometry().bottom()
            self.assertLessEqual(gap, 24)
            OBSERVATIONS.append({'language': language, 'preset_heading_gap': gap})
            window.receive_files([str(OUT / '원본.png')])
            settle()
            for button in (window.run_button, window.cancel_button, window.retry_button):
                expose(button)
                self.assertTrue(button.visibleRegion().contains(button.rect()), button.text())
                self.assertGreaterEqual(button.width(), button.fontMetrics().horizontalAdvance(button.text()) + 16)
            headings = [label.text() for label in window.findChildren(QLabel, 'sectionHeading')]
            self.assertEqual(len(headings), 4)
            self.assertEqual(len(set(headings)), 4)
            self.assertTrue(capture(window, OUT / f'{language}-selected.png'))
            for _, _, _, button in window.preview_panel.panels:
                expose(button)
                self.assertTrue(button.visibleRegion().contains(button.rect()), button.text())
            self.assertTrue(capture(window, OUT / f'{language}-selected-bottom.png'))

    def test_03_cached_preview_uses_current_dpr(self):
        original = OUT / '원본.png'
        result = OUT / '결과.png'
        app.engine.Image.new('RGB', (500, 300), '#dddddd').save(original)
        app.engine.Image.new('RGB', (400, 250), '#777777').save(result)
        panel = self.window.preview_panel
        panel.set_paths(str(original), str(result))
        self.assertEqual(panel.paths, (str(original), str(result)))
        with patch('preview_panel.Image.open', side_effect=AssertionError('크기 변경 중 원본 재읽기')):
            panel.resize(panel.width() - 1, panel.height())
            for index in range(2):
                panel._fit_picture(index)
                self.assertFalse(panel.panels[index][1].pixmap().isNull())
                self.assertEqual(panel.panels[index][1].pixmap().devicePixelRatio(), panel.devicePixelRatioF())
        self.assertNotEqual(panel.panels[0][0].text(), panel.panels[1][0].text())

    def test_04_file_folder_message_and_enlarged_preview(self):
        from pdf_panel import EnlargedPreview
        from PySide6.QtGui import QPixmap
        for language in ('ko', 'en'):
            self.window.set_language(language)
            for folder in (False, True):
                dialog = self.window.file_dialog(folder)
                try:
                    fixture = OUT / ('읽기-원본' if folder else 'readable-name.png')
                    if folder:
                        fixture.mkdir(exist_ok=True)
                    else:
                        app.engine.Image.new('RGB', (40, 40), 'white').save(fixture)
                    dialog.setDirectory(str(OUT))
                    dialog.show()
                    settle()
                    self.assertTrue(dialog.screen().availableGeometry().contains(dialog.frameGeometry()))
                    tree = dialog.findChild(QTreeView, 'treeView')
                    header = tree.header()
                    self.assertGreaterEqual(header.sectionSize(0), 180)
                    index = tree.model().index(str(fixture))
                    self.assertTrue(index.isValid())
                    tree.scrollTo(index)
                    settle()
                    filename = tree.model().data(index, Qt.DisplayRole)
                    self.assertEqual(filename, fixture.name)
                    self.assertEqual(tree.fontMetrics().elidedText(filename, Qt.ElideRight, header.sectionSize(0) - 36), filename)
                    density_icon = dialog._icon_provider.icon(QFileInfo(str(fixture))).pixmap(QSize(24, 24), 2.0)
                    self.assertEqual(density_icon.size(), QSize(48, 48))
                    self.assertEqual(density_icon.devicePixelRatio(), 2.0)
                    bar = tree.horizontalScrollBar()
                    if header.length() > tree.viewport().width():
                        self.assertGreater(bar.maximum(), 0)
                        bar.setValue(bar.maximum())
                        settle()
                        last = max(column for column in range(header.count()) if not tree.isColumnHidden(column))
                        self.assertLessEqual(header.sectionViewportPosition(last) + header.sectionSize(last), tree.viewport().width())
                        self.assertTrue(capture(dialog, OUT / f'{language}-picker-{folder}-last-column.png'))
                    OBSERVATIONS.append({'picker': f'{language}-{folder}', 'name_width': header.sectionSize(0),
                                         'name_text': filename, 'horizontal_maximum': bar.maximum()})
                    bar.setValue(0)
                    for button in dialog.findChild(QDialogButtonBox).buttons():
                        expose(button)
                        self.assertTrue(button.visibleRegion().contains(button.rect()), button.text())
                    self.assertTrue(capture(dialog, OUT / f'{language}-picker-{folder}.png'))
                finally:
                    dialog.hide()
                    dialog.deleteLater()
            notice = app.message_dialog(self.window, '확인' if language == 'ko' else 'Notice', '긴 원문 경로 · ' * 20)
            notice.show()
            settle()
            self.assertTrue(notice.screen().availableGeometry().contains(notice.frameGeometry()))
            self.assertTrue(capture(notice, OUT / f'{language}-message.png'))
            notice.hide()
            notice.deleteLater()
            pixmap = QPixmap(500, 700)
            pixmap.fill(Qt.white)
            enlarged = EnlargedPreview(pixmap, self.window.pdf_panel)
            enlarged.show()
            settle()
            self.assertTrue(enlarged.screen().availableGeometry().contains(enlarged.frameGeometry()))
            for button in (enlarged.zoom_in_button, enlarged.zoom_out_button, enlarged.fit_button, enlarged.close_button):
                expose(button)
                self.assertTrue(button.visibleRegion().contains(button.rect()))
            self.assertTrue(capture(enlarged, OUT / f'{language}-enlarged.png'))
            enlarged.close()

    def test_05_state_deadline_and_first_tick_delay(self):
        mark = StateMark()
        mark.show()
        settle()
        set_reduced_motion(mark, False)
        for delay in (50, 100):
            mark.respond('complete')
            time.sleep(delay / 1000)
            QTest.qWait(420 - delay)
            self.assertEqual(mark.animation.duration(), 400)
            self.assertEqual(mark.animation.state(), QAbstractAnimation.Stopped)
            self.assertEqual(mark.phase, 1)
            self.assertFalse(mark.deadline.isActive())
        mark.hide()
        mark.deleteLater()

    def test_06_state_reentry_hide_manual_finish_and_reduce(self):
        mark = StateMark()
        mark.show()
        settle()
        mark.respond('working')
        QTest.qWait(250)
        mark.respond('cancelling')
        QTest.qWait(170)
        self.assertEqual(mark.state, 'cancelling')
        self.assertEqual(mark.animation.state(), QAbstractAnimation.Running)
        mark.animation.setCurrentTime(400)
        self.assertFalse(mark.deadline.isActive())
        mark.respond('working')
        mark.hide()
        self.assertFalse(mark.deadline.isActive())
        self.assertEqual(mark.phase, 1)
        mark.show()
        set_reduced_motion(mark, True)
        self.assertEqual(mark.animation.state(), QAbstractAnimation.Stopped)
        self.assertFalse(mark.deadline.isActive())
        mark.respond('complete')
        self.assertEqual(mark.state, 'complete')
        self.assertEqual(mark.phase, 1)
        set_reduced_motion(mark, False)
        mark.hide()
        mark.deleteLater()

    def test_07_real_pdf_editor_and_enlarged_render(self):
        from reportlab.pdfgen import canvas
        import hashlib
        source = OUT / '편집-원본.pdf'
        document = canvas.Canvas(str(source))
        for number in range(3):
            document.drawString(72, 720, f'PAGE {number + 1}')
            document.showPage()
        document.save()
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        panel = self.window.pdf_panel
        self.window.tabs.setCurrentIndex(4)
        self.assertTrue(panel.load_workspace(str(source)))
        deadline = time.monotonic() + 10
        while (panel.is_busy() or panel.page_preview.original.isNull()) and time.monotonic() < deadline:
            QTest.qWait(20)
        self.assertFalse(panel.is_busy())
        self.assertEqual(panel.pages_list.count(), 3)
        self.assertFalse(panel.page_preview.original.isNull())
        for language in ('ko', 'en'):
            self.window.set_language(language)
            for index in range(3):
                item = panel.pages_list.item(index)
                self.assertIn(str(index + 1), item.text())
                self.assertIn(panel.tr_text('page_label', number=index + 1, source=index + 1), item.toolTip())
                self.assertLessEqual(panel.pages_list.fontMetrics().horizontalAdvance(item.text()), panel.pages_list.gridSize().width() - 8)
            for button in (panel.open_pages_button, panel.view_page_button, panel.close_pages_button,
                           panel.rotate_pages_button, panel.delete_pages_button, panel.extract_pages_button,
                           panel.save_pages_button, panel.cancel_pages_button):
                expose(button)
                self.assertTrue(button.visibleRegion().contains(button.rect()), button.text())
            self.assertTrue(capture(self.window, OUT / f'{language}-pdf-editor.png'))
            panel.open_page_preview()
            settle()
            self.assertIsNotNone(panel.preview_dialog)
            self.assertTrue(capture(panel.preview_dialog, OUT / f'{language}-pdf-enlarged.png'))
            panel.preview_dialog.close()
            settle()
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
        panel.close_workspace()


def main():
    app.engine.Image.new('RGB', (500, 300), '#dddddd').save(OUT / '원본.png')
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(FixedLayoutTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
              'skipped': len(result.skipped), 'observations': OBSERVATIONS,
              'platform': APPLICATION.platformName(), 'scale_env': os.environ.get('QT_SCALE_FACTOR'),
              'scope': '실제 Qt offscreen 렌더와 제어 이벤트 시험. 실제 OS 화면 캡처·Windows 배율 변경 아님.'}
    report['source_sha256'] = SOURCE_SHA256
    report['source_unchanged_during_run'] = all(hashlib.sha256((SOURCE_ROOT / name).read_bytes()).hexdigest() == digest
                                              for name, digest in SOURCE_SHA256.items())
    assert report['source_unchanged_during_run']
    (OUT / '고정창-검증.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
