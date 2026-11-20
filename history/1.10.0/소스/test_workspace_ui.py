"""확장 작업 공간의 실제 Qt·파일·상태 검사."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from PySide6.QtWidgets import QApplication, QWidget, QDialog, QDialogButtonBox, QListWidget, QPushButton, QFileDialog
from PySide6.QtCore import QSettings, Qt, QMimeData, QUrl, QPointF, QTimer, QEventLoop, QAbstractEventDispatcher
from PySide6.QtGui import QDropEvent
from PySide6.QtTest import QTest
from PIL import Image, ImageDraw, ImageFont
from workspace_ui import WorkspacePanel, StableFolderWatch, CommandDialog

APP = QApplication.instance() or QApplication([])

class Owner(QWidget):
    def __init__(self, root):
        super().__init__()
        self.settings = QSettings(str(root / 'settings.ini'), QSettings.IniFormat)
        self.pending = 0
        self.records = []
        self.pdf_panel = type('Pdf', (), {'is_busy': lambda s: False})()
    def append_record(self, *record):
        self.records.append(record)
    def update_status(self):
        pass

class WorkspaceUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.owner = Owner(self.root)
        # 실제 배치 검사는 부모 창까지 표시하여 Qt 레이아웃을 활성화한다.
        self.owner.resize(1000,720)
        self.owner.show()
        self.panel = WorkspacePanel(self.owner)
        self.panel.resize(900, 660)
        self.panel.show()
        self.path = self.root / '원본.png'
        Image.new('RGB', (64, 40), 'white').save(self.path)
    def tearDown(self):
        self.panel.shutdown()
        self.wait_done()
        # 오프스크린 Qt가 소유한 검사 MIME은 QApplication보다 먼저 정리한다.
        # 제품의 실제 클립보드 유지 동작과 파일 복사 검증은 바꾸지 않는다.
        QApplication.clipboard().clear()
        APP.processEvents()
        self.panel.close()
        self.owner.close()
        APP.processEvents()
        self.tmp.cleanup()
    def wait_done(self):
        # 실제 이벤트 루프에서 완료를 관찰하며 기존 27초 제한은 유지한다.
        if not self.panel.is_busy():
            return
        loop=QEventLoop()
        timer=QTimer(loop)
        timer.setSingleShot(True)
        timer.setTimerType(Qt.PreciseTimer)
        dispatcher=QAbstractEventDispatcher.instance()
        active=[True]
        expired=[False]
        def completion_gate(*unused):
            if active[0] and not self.panel.is_busy():
                loop.quit()
        def timeout():
            if active[0]:
                expired[0]=True
                loop.quit()
        # 연결 전에 이미 전송된 완료 신호도 큐 처리 뒤의 gate에서 관찰한다.
        self.panel.bridge.done.connect(completion_gate,Qt.QueuedConnection)
        dispatcher.aboutToBlock.connect(completion_gate)
        timer.timeout.connect(timeout)
        try:
            timer.start(27000)
            if self.panel.is_busy():
                loop.exec()
        finally:
            # 이미 큐에 든 콜백은 비활성 gate로 처리하고 모든 연결을 해제한다.
            active[0]=False
            timer.stop()
            timer.timeout.disconnect(timeout)
            self.panel.bridge.done.disconnect(completion_gate)
            dispatcher.aboutToBlock.disconnect(completion_gate)
        if expired[0] or self.panel.is_busy():
            self.fail('작업이 종료되지 않았습니다')
    def test_files_language_and_motion(self):
        self.panel.set_files([str(self.path)])
        self.assertEqual(self.panel.files.count(), 1)
        self.panel.set_language('en')
        self.assertEqual(self.panel.run_button.text(), 'Run recipe')
        self.assertEqual(self.panel.paths, [str(self.path)])
        self.panel.set_reduced_motion(True)
        self.assertEqual(self.panel.visual.animation.state().name, 'Stopped')
        self.panel.hide()
        self.assertEqual(self.panel.visual.animation.state().name, 'Stopped')
    def test_empty_selection_name_hint_preserves_literal_braces(self):
        from i18n import tr
        expected={'ko':'{name}, {index}, {date}를 사용할 수 있습니다.',
                  'en':'Use {name}, {index}, {date}.'}
        # 미리보기 제공자가 빈 목록을 반환하는 안내 분기도 실제 패널에서 확인한다.
        with patch('workspace_core.preview_names',return_value=[]):
            self.panel.set_files([])
            for language,text in expected.items():
                self.assertEqual(tr(language,'ws_name_hint'),text)
                self.panel.set_language(language)
                self.assertEqual(self.panel.paths,[])
                self.assertEqual(self.panel.names_preview.text(),text)
    def test_pipeline_preserves_source_and_records(self):
        original = self.path.read_bytes()
        self.panel.set_files([str(self.path)])
        self.panel.recipe_editor.setPlainText('{"version":1,"name":"복사","steps":[{"op":"rename","template":"{name}_{index}"}]}')
        self.assertTrue(self.panel.run_recipe())
        self.assertEqual(self.owner.pending, 1)
        self.assertFalse(self.panel.run_recipe())
        self.wait_done()
        self.assertEqual(self.owner.pending, 0)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertTrue(self.owner.records)
        self.assertTrue(Path(self.owner.records[0][1]).is_file())
    def test_invalid_recipe_and_busy_gate(self):
        self.panel.set_files([str(self.path)])
        self.panel.recipe_editor.setPlainText('{"version":1,"name":"bad","steps":[{"op":"shell"}]}')
        self.assertFalse(self.panel.run_recipe())
        self.assertFalse(self.panel.is_busy())
        self.owner.pending = 1
        self.assertFalse(self.panel.run_recipe())
        self.owner.pending = 0
    def test_recipe_save_reload(self):
        self.panel.recipe_editor.setPlainText('{"version":1,"name":"저장","steps":[{"op":"audit"}]}')
        self.assertTrue(self.panel.save_recipe())
        self.assertGreaterEqual(self.panel.recipe_combo.findText('저장'), 0)
    def test_watch_requires_stability_and_excludes_outputs(self):
        output = self.root / 'results'
        output.mkdir()
        watcher = StableFolderWatch()
        watcher.configure(self.root, output)
        self.assertEqual(watcher.scan(), [])
        self.assertEqual(watcher.scan(), [str(self.path)])
        self.assertEqual(watcher.scan(), [])
        Image.new('RGB',(4,4)).save(output / 'out.png')
        self.assertEqual(watcher.scan(), [])
        (self.root / '.tmp.png').write_bytes(b'pending')
        self.assertEqual(watcher.scan(), [])
    def test_no_overlap_and_finite_motion(self):
        self.panel.set_files([str(self.path)])
        APP.processEvents()
        self.assertLess(self.panel.visual.geometry().bottom(), self.panel.files.geometry().top())
        self.assertLess(self.panel.files.geometry().bottom(), self.panel.recipe_combo.geometry().top())
        QTest.qWait(400)
        APP.processEvents()
        self.assertEqual(self.panel.visual.animation.state().name, 'Stopped')
        self.assertAlmostEqual(self.panel.visual.phase, 1.0)
    def test_cancel_queued_result_and_gate_release(self):
        import workspace_core
        real_execute = workspace_core.execute_workspace
        def execute_after_cancel(*args, **kwargs):
            kwargs['cancel'].wait(2)
            return real_execute(*args, **kwargs)
        self.panel.set_files([str(self.path)])
        with patch('workspace_core.execute_workspace', side_effect=execute_after_cancel):
            self.assertTrue(self.panel.run_recipe())
            self.panel.cancel()
            self.wait_done()
        self.assertEqual(self.panel._status_key, 'ws_cancelled')
        self.assertEqual(self.owner.pending, 0)
        self.assertEqual(self.panel.results.count(), 0)
    def test_shutdown_defers_close_until_cancel_signal(self):
        import workspace_core
        real_execute=workspace_core.execute_workspace
        def execute_after_cancel(*args,**kwargs):
            kwargs['cancel'].wait(2)
            return real_execute(*args,**kwargs)
        self.panel.set_files([str(self.path)])
        with patch('workspace_core.execute_workspace',side_effect=execute_after_cancel):
            self.panel.run_recipe()
            self.assertFalse(self.panel.shutdown())
            self.panel.close()
            self.wait_done()
        self.assertEqual(self.owner.pending,0)
        self.assertTrue(self.panel.shutdown())
    def test_explicit_watch_executes_once_and_stops(self):
        self.panel._watch_folder = str(self.root)
        self.panel.output_dir = self.root / 'output'
        self.panel.output_dir.mkdir()
        self.panel.write_recipe({'version':1,'name':'감시','steps':[{'op':'rename','template':'{name}_watched'}]})
        self.assertFalse(self.panel.watch_timer.isActive())
        self.panel.watch_enabled.setChecked(True)
        self.panel.watch_timer.stop()
        self.panel.scan_watch()
        self.assertFalse(self.panel.is_busy())
        self.panel.scan_watch()
        self.wait_done()
        self.assertEqual(len(self.owner.records), 1)
        self.panel.scan_watch()
        self.assertEqual(len(self.owner.records), 1)
        self.panel.watch_enabled.setChecked(False)
        self.assertFalse(self.panel.watch_timer.isActive())
    def test_clipboard_drop_and_result_copy(self):
        QApplication.clipboard().setText('한글 클립보드')
        self.panel.import_clipboard()
        self.assertEqual(Path(self.panel.paths[0]).read_text(encoding='utf-8'), '한글 클립보드')
        mime=QMimeData(); mime.setUrls([QUrl.fromLocalFile(str(self.path))])
        event=QDropEvent(QPointF(20,20),Qt.CopyAction|Qt.MoveAction,mime,Qt.LeftButton,Qt.ShiftModifier)
        self.panel.files.dropEvent(event)
        self.assertEqual(event.dropAction(), Qt.CopyAction)
        self.assertIn(str(self.path),self.panel.paths)
        self.panel.set_files([str(self.path)])
        self.panel.write_recipe({'version':1,'name':'복사','steps':[{'op':'rename','template':'{name}_copy'}]})
        self.panel.run_recipe(); self.wait_done()
        self.panel.copy_result(False)
        self.assertTrue(Path(QApplication.clipboard().text()).is_file())
        self.panel.copy_result(True)
        self.assertTrue(QApplication.clipboard().mimeData().hasUrls())
    def test_commands_search_keyboard_and_wheel_persistence(self):
        dialog=CommandDialog(self.panel)
        dialog.show()
        dialog.search.setText(self.panel.t('ws_run'))
        self.assertEqual(dialog.list.count(),1)
        self.assertFalse(dialog.list.item(0).data(Qt.UserRole+1))
        dialog.close()
        self.owner.settings.setValue('workspace/wheel','{"order":["webp","jpg"],"hidden":["png"],"recipe":""}')
        self.owner.settings.sync()
        self.assertEqual(self.panel.ordered_formats(['png','jpg','webp']),['webp','jpg'])
        stored=QSettings(self.owner.settings.fileName(),QSettings.IniFormat)
        self.assertIn('webp',stored.value('workspace/wheel'))
    def test_command_keyboard_action_and_wheel_dialog_save_reset(self):
        called=[]
        with patch.object(self.panel,'choose_files',lambda:called.append('files')):
            dialog=CommandDialog(self.panel); dialog.show()
            dialog.search.setText(self.panel.t('ws_add'))
            QTest.keyClick(dialog.search,Qt.Key_Down)
            QTest.keyClick(dialog.search,Qt.Key_Return)
            self.assertEqual(called,['files'])
        def save_dialog():
            dialog=next(w for w in QApplication.topLevelWidgets() if isinstance(w,QDialog) and w.isVisible())
            values=dialog.findChild(QListWidget)
            values.item(0).setCheckState(Qt.Unchecked)
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Save).click()
        QTimer.singleShot(50,save_dialog)
        self.panel.edit_wheel()
        self.assertTrue(self.panel.wheel_preferences()['hidden'])
        def reset_dialog():
            dialog=next(w for w in QApplication.topLevelWidgets() if isinstance(w,QDialog) and w.isVisible())
            next(b for b in dialog.findChildren(QPushButton) if b.text()==self.panel.t('ws_reset')).click()
        QTimer.singleShot(50,reset_dialog)
        self.panel.edit_wheel()
        self.assertEqual(self.panel.wheel_preferences(),{})
    def test_actual_collage_and_gif_outputs(self):
        second=self.root/'second.png'; Image.new('RGB',(20,30),'black').save(second)
        self.panel.set_files([str(self.path),str(second)])
        for operation in ('collage','gif','combine_pdf'):
            self.panel.write_recipe({'version':1,'name':operation,'steps':[{'op':operation}]})
            self.assertTrue(self.panel.run_recipe())
            self.wait_done()
            output=Path(self.panel.results.item(0).data(Qt.UserRole))
            self.assertTrue(output.is_file())
            self.assertEqual(self.panel._status_key,'ws_complete')
    def test_default_target_plain_text_copy_and_explicit_quality_rejection(self):
        path=self.root/'원본.txt'; path.write_text('원본 텍스트',encoding='utf-8')
        self.panel.set_files([str(path)])
        self.panel.write_recipe({'version':1,'name':'텍스트 복사','steps':[{'op':'rename','template':'{name}_copy'}]})
        self.assertEqual(self.panel.target(),{})
        self.assertFalse(self.panel.quality.isEnabled())
        self.assertFalse(self.panel.dpi.isEnabled())
        self.assertTrue(self.panel.run_recipe()); self.wait_done()
        self.assertEqual(self.panel._status_key,'ws_complete')
        self.assertEqual(len(self.owner.records),1)
        self.assertEqual(self.owner.records[0][2],'')
        self.assertEqual(Path(self.owner.records[0][1]).read_text(encoding='utf-8'),'원본 텍스트')
        self.panel.quality_enabled.setChecked(True)
        self.assertTrue(self.panel.quality.isEnabled())
        self.assertFalse(self.panel.run_recipe())
        self.assertEqual(len(self.owner.records),1)
        self.assertEqual(self.owner.pending,0)
        self.assertEqual(path.read_text(encoding='utf-8'),'원본 텍스트')
        self.panel.write_recipe({'version':1,'name':'원래 크기','steps':[{'op':'normalize_pages','page_size':'original'}]})
        self.assertFalse(self.panel.run_recipe())
        self.assertEqual(len(self.owner.records),1)
    def test_default_ui_ocr_document_and_receipt_outputs(self):
        import engine
        image=Image.new('RGB',(1100,400),'white')
        font=ImageFont.truetype(str(engine.asset('NanumGothicBold.ttf')),56)
        ImageDraw.Draw(image).text((30,60),'PUVKID 1200\nTOTAL 3000',font=font,fill='black',spacing=35)
        path=self.root/'receipt.png'; image.save(path)
        self.panel.set_files([str(path)])
        self.assertEqual(self.panel.target(),{})
        operations=[{'op':'ocr','format':fmt,'language':'eng'} for fmt in ('txt','docx','xlsx')]
        operations.append({'op':'receipts_xlsx','language':'eng'})
        for step in operations:
            before=len(self.owner.records)
            self.panel.write_recipe({'version':1,'name':'문서 출력','steps':[step]})
            self.assertTrue(self.panel.run_recipe()); self.wait_done()
            self.assertEqual(self.panel._status_key,'ws_complete',self.panel.status.text())
            self.assertEqual(len(self.owner.records),before+1)
            self.assertEqual(self.owner.records[-1][2],'')
            self.assertTrue(Path(self.owner.records[-1][1]).is_file())
    def test_explicit_image_quality_and_independent_targets(self):
        self.panel.format.setCurrentIndex(self.panel.format.findData('pdf'))
        self.panel.max_bytes.setValue(512)
        self.panel.a4.setChecked(True)
        self.assertEqual(self.panel.target(),{'format':'pdf','max_bytes':512*1024,'page_size':'A4'})
        self.panel.format.setCurrentIndex(0); self.panel.max_bytes.setValue(0); self.panel.a4.setChecked(False)
        self.panel.set_files([str(self.path)])
        self.panel.write_recipe({'version':1,'name':'명시 품질','steps':[{'op':'rename','template':'{name}_quality'}]})
        self.panel.quality_enabled.setChecked(True)
        self.panel.quality.setValue(70); self.panel.dpi.setValue(120)
        self.assertEqual(self.panel.target(),{'quality':70,'dpi':120})
        self.panel.set_language('en')
        self.assertTrue(self.panel.quality_enabled.isChecked())
        self.assertTrue(self.panel.run_recipe()); self.wait_done()
        self.assertEqual(self.panel._status_key,'ws_complete')
        self.assertEqual(len(self.owner.records),1)
        self.assertEqual(self.owner.records[0][2],'')
    def test_common_picker_classes_languages_motion_and_cancel(self):
        from ui_motion import MotionFileDialog
        actions=[self.panel.choose_files,self.panel.import_recipe,self.panel.export_recipe,self.panel.choose_output,self.panel.choose_watch_folder]
        before=(self.panel.paths.copy(),self.panel.recipe_editor.toPlainText(),self.panel.output_dir)
        seen=[]
        def reject(dialog):
            self.assertIsInstance(dialog,MotionFileDialog)
            self.assertTrue(dialog.testOption(QFileDialog.DontUseNativeDialog))
            seen.append((dialog.title_key,dialog.fileMode(),dialog.acceptMode()))
            self.panel.set_language('en')
            self.assertEqual(dialog.language,'en')
            self.assertEqual(dialog.windowTitle(),self.panel.t(dialog.title_key))
            self.panel.set_reduced_motion(True)
            dialog.show(); APP.processEvents()
            self.assertTrue(APP.property('flipringReducedMotion'))
            dialog.reject()
            return QFileDialog.Rejected
        with patch.object(MotionFileDialog,'exec',reject):
            for action in actions: action()
        self.assertEqual(len(seen),5)
        self.assertEqual(seen[0][1],QFileDialog.ExistingFiles)
        self.assertEqual(seen[1][1],QFileDialog.ExistingFile)
        self.assertEqual(seen[2][2],QFileDialog.AcceptSave)
        self.assertEqual(seen[3][1],QFileDialog.Directory)
        self.assertEqual(seen[4][1],QFileDialog.Directory)
        self.assertEqual((self.panel.paths,self.panel.recipe_editor.toPlainText(),self.panel.output_dir),before)
        self.assertFalse(hasattr(self.panel,'_watch_folder'))
        self.assertEqual(self.panel._pickers,[])
    def test_common_picker_accepts_files_recipe_export_and_folders(self):
        import json
        from ui_motion import MotionFileDialog
        recipe={'version':1,'name':'선택창 레시피','steps':[{'op':'rename','template':'{name}_selected'}]}
        imported=self.root/'import.json'; imported.write_text(json.dumps(recipe,ensure_ascii=False),encoding='utf-8')
        exported=self.root/'export.json'; output=self.root/'out';output.mkdir();watch=self.root/'watch';watch.mkdir()
        selected={'ws_add':[str(self.path)],'ws_import':[str(imported)],'ws_export':[str(exported)],'ws_output':[str(output)],'ws_watch_folder':[str(watch)]}
        with patch.object(MotionFileDialog,'exec',lambda d:QFileDialog.Accepted), patch.object(MotionFileDialog,'selectedFiles',lambda d:selected[d.title_key]):
            self.panel.choose_files();self.panel.import_recipe();self.panel.export_recipe();self.panel.choose_output();self.panel.choose_watch_folder()
        self.assertEqual(self.panel.paths,[str(self.path)])
        self.assertEqual(json.loads(exported.read_text(encoding='utf-8')),recipe)
        self.assertEqual(self.panel.output_dir,output)
        self.assertEqual(self.panel._watch_folder,str(watch))
        self.assertFalse(self.panel.watch_enabled.isChecked())
    def test_mainwindow_history_filters_and_legacy_boundaries(self):
        import app
        previous=app.DATA; app.DATA=self.root/'app-data'
        window=None
        try:
            app.apply_application_style(APP)
            window=app.MainWindow(); window.timer.stop()
            window.notifications.setChecked(False); window.reveal.setChecked(False)
            self.assertEqual(window.tabs.count(),7)
            self.assertEqual(window.tabs.currentIndex(),6)
            self.assertIs(window.tabs.widget(4),window.pdf_panel)
            self.assertEqual(window.sidebar.width(),204)
            window.records=[{'time':'2026-11-02T00:00:00','source':str(self.path),'output':str(self.path),'error':''},
                            {'time':'2026-11-02T00:01:00','source':'missing.pdf','output':'','error':'failed'}]
            window.refresh_history()
            window.history_format.setText('png')
            self.assertTrue(window.history.item(0).isHidden())
            self.assertFalse(window.history.item(1).isHidden())
            window.history_format.clear(); window.history_state.setCurrentIndex(window.history_state.findData('failed'))
            self.assertFalse(window.history.item(0).isHidden())
            self.assertTrue(window.history.item(1).isHidden())
            window.history_state.setCurrentIndex(0); window.history.setCurrentRow(1)
            window.copy_history_result(False)
            self.assertEqual(QApplication.clipboard().text(),str(self.path))
            window.set_language('en')
            self.assertEqual(window.workspace_panel.run_button.text(),'Run recipe')
        finally:
            if window:
                window.workspace_panel.shutdown(); window.pdf_panel.shutdown(); window.pool.shutdown(wait=False)
                window.timer.stop(); window.wheel.hide(); window.tray.hide(); window.hide()
            app.DATA=previous

if __name__ == '__main__':
    unittest.main()
