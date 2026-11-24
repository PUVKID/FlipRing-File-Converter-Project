"""빠른 작업의 원본·경로·취소·저장과 Qt 큐 수명 검사."""
import copy
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile
from PIL import Image
import quick_actions as core

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.source = self.root / '입력'; self.source.mkdir()
        (self.source / '하위').mkdir(); self.path = self.source / '하위/사진.png'
        Image.new('RGBA', (60, 40), (20, 80, 100, 100)).save(self.path)
        self.original = self.path.read_bytes(); self.output = self.root / '결과'
        self.action = copy.deepcopy(core.BUILTINS[0])
    def records(self): return core.collect_inputs([str(self.source)])['inputs']
    def test_collect_filter_duplicates_hidden(self):
        (self.source / '.숨김.png').write_bytes(self.original)
        (self.source / '~임시.png').write_bytes(self.original)
        rows = core.collect_inputs([str(self.source), str(self.path)], 'png')['inputs']
        self.assertEqual(len(rows), 1)
        self.assertEqual(Path(rows[0]['relative']), Path('입력/하위/사진.png'))
    def test_chain_zip_and_collision_preserve_original(self):
        result = core.run_action(self.records(), {**self.action, 'width': 30, 'max_bytes': 1, 'zip': True}, self.output)
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(len(result['outputs']), 2)
        output = Path(result['outputs'][0]['path']); before = output.read_bytes()
        with Image.open(output) as image: self.assertEqual(image.size, (30, 20))
        self.assertFalse(result['outputs'][0]['constraints_met'])
        self.assertEqual(self.path.read_bytes(), self.original)
        with zipfile.ZipFile(result['outputs'][-1]['path']) as archive:
            self.assertEqual(archive.namelist(), ['입력/하위/사진.jpg'])
        second = core.run_action(self.records(), self.action, self.output)
        self.assertNotEqual(str(output), second['outputs'][0]['path'])
        self.assertEqual(output.read_bytes(), before)
        self.assertFalse(list(self.output.glob('.flipring-quick-*')))
    def test_cancel_keeps_completed_files(self):
        token = threading.Event(); (self.source / '하위/둘.png').write_bytes(self.original)
        def event(value):
            if value['state'] == 'completed': token.set()
        result = core.run_action(self.records(), self.action, self.output, token, event)
        self.assertEqual(result['status'], 'cancelled'); self.assertEqual(len(result['outputs']), 1)
        self.assertTrue(Path(result['outputs'][0]['path']).exists()); self.assertEqual(self.path.read_bytes(), self.original)
    def test_bundle_failure_retries_without_reconverting(self):
        with patch('quick_actions.create_bundle', side_effect=OSError('ZIP 실패')):
            result = core.run_action(self.records(), {**self.action, 'zip': True}, self.output)
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['bundle_pending'])
        self.assertEqual(len(result['files']), 1)
        image = Path(result['outputs'][0]['path']); before = image.read_bytes()
        bundle = core.create_bundle(result['outputs'], self.output)
        self.assertTrue(Path(bundle['path']).is_file())
        self.assertEqual(image.read_bytes(), before)

    def test_cleanup_changed_file_and_undo_collision(self):
        result = core.run_action(self.records(), self.action, self.output)
        path = Path(result['outputs'][0]['path']); original = path.read_bytes()
        ledger = core.OutputLedger(); ledger.register(result['outputs'])
        path.write_bytes(b'changed'); self.assertTrue(ledger.cleanup([str(path)])['errors'])
        self.assertEqual(path.read_bytes(), b'changed'); path.write_bytes(original)
        self.assertEqual(len(ledger.cleanup([str(path)])['moved']), 1); self.assertFalse(path.exists())
        path.write_bytes(b'other'); self.assertTrue(ledger.undo()['errors']); self.assertEqual(path.read_bytes(), b'other')
        path.unlink(); self.assertEqual(ledger.undo()['restored'], [str(path)]); self.assertEqual(path.read_bytes(), original)
        self.assertTrue(ledger.cleanup([str(self.path)])['errors'])
    def test_link_escape_missing_helper(self):
        with patch('quick_actions.Path.lstat') as query:
            query.return_value = type('Info', (), {'st_mode': 0o040755, 'st_file_attributes': 0x400})()
            with self.assertRaises(ValueError): core.safe_path(self.root / '연결')
        rows = [{'source': str(self.path), 'relative': '../탈출.png'}]
        self.assertFalse(core.preflight(rows, self.action, self.output)['ok'])
        with patch('quick_actions.engine.requirement', return_value='필수 도구'):
            self.assertFalse(core.preflight(self.records(), self.action, self.output)['ok'])
        records = self.records(); self.path.unlink()
        self.assertFalse(core.preflight(records, self.action, self.output)['ok'])
    def test_store_validation_and_damage_preservation(self):
        store = core.ActionStore(self.root / '설정.json'); store.save(self.action)
        renamed = {**self.action, 'name': '새 이름'}; store.save(renamed, self.action['name'])
        self.assertEqual(store.load(), [renamed])
        with self.assertRaises(ValueError): store.save(renamed)
        store.delete('새 이름'); self.assertEqual(store.load(), [])
        store.path.write_text('{손상', encoding='utf-8'); before = store.path.read_bytes()
        with self.assertRaises(ValueError): store.save(self.action)
        self.assertEqual(store.path.read_bytes(), before)
        with self.assertRaises(ValueError): core.validate_action({**self.action, 'template': '../{name}'})
        with self.assertRaises(ValueError): core.validate_action({**self.action, 'command': 'whoami'})

class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
    def pump(self, predicate):
        until = time.monotonic() + 10
        while time.monotonic() < until and not predicate():
            self.app.processEvents(); time.sleep(.01)
        self.app.processEvents(); self.assertTrue(predicate())
    def test_queue_pause_reorder_and_execution(self):
        from PySide6.QtWidgets import QWidget
        from quick_actions_ui import QuickActionsPanel
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / '원본.png'; Image.new('RGBA', (32, 24)).save(source)
            owner = QWidget(); owner.pending = False; panel = QuickActionsPanel(owner); self.addCleanup(panel.shutdown)
            panel.store = core.ActionStore(root / '설정.json'); panel.output.setText(str(root / '결과'))
            panel.add_paths([str(source)]); self.pump(lambda: len(panel._inputs) == 1 and not panel._tasks)
            panel.pause(); panel.enqueue(); panel.enqueue()
            self.assertEqual([r['state'] for r in panel._jobs], ['waiting', 'waiting'])
            first = panel._jobs[0]['id']; panel.queue.setCurrentRow(1); panel.move_job(-1)
            self.assertEqual(panel._jobs[1]['id'], first)
            panel.set_language('en'); self.assertEqual(panel.title.text(), 'Quick actions')
            panel.set_language('ko'); panel.resume()
            self.pump(lambda: all(r['state'] == 'completed' for r in panel._jobs) and not panel.is_busy())
            self.assertEqual(len(panel._outputs), 2); self.assertTrue(panel.shutdown())
    def test_wheel_snapshot_and_common_file_dialog(self):
        from PySide6.QtWidgets import QWidget, QFileDialog
        from quick_actions_ui import QuickActionsPanel
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / '휠.png'; Image.new('RGB', (20, 10)).save(source)
            owner = QWidget(); owner.pending = False; panel = QuickActionsPanel(owner); self.addCleanup(panel.shutdown)
            panel.output.setText(str(root / '결과'))
            self.assertTrue(panel.wheel_action()); self.assertTrue(panel.wheel_label())
            panel.wheel_enabled.setChecked(False); self.assertIsNone(panel.wheel_action())
            panel.wheel_enabled.setChecked(True); panel.pause(); panel.enqueue_paths([str(source)])
            panel.format.setCurrentText('png')
            self.pump(lambda: len(panel._jobs) == 1 and not panel._tasks)
            self.assertEqual(panel._jobs[0]['action']['format'], 'jpg')
            self.assertEqual(panel._inputs, [])
            from ui_motion import make_file_dialog
            dialog = make_file_dialog(panel, '검사'); dialog.set_language('en')
            self.assertTrue(dialog.testOption(QFileDialog.DontUseNativeDialog)); dialog.deleteLater()
            panel.resume(); self.pump(lambda: panel._jobs[0]['state'] == 'completed' and not panel.is_busy())
            self.assertTrue(panel.shutdown())

    def test_retry_failed_bundle_only_and_no_duplicate_retry(self):
        from PySide6.QtWidgets import QWidget
        from quick_actions_ui import QuickActionsPanel
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / '원본.png'; Image.new('RGB', (20, 10)).save(source)
            owner = QWidget(); owner.pending = False; panel = QuickActionsPanel(owner); self.addCleanup(panel.shutdown)
            panel.output.setText(str(root / '결과')); panel.zip.setChecked(True)
            panel.add_paths([str(source)]); self.pump(lambda: len(panel._inputs) == 1 and not panel._tasks)
            with patch('quick_actions.create_bundle', side_effect=OSError('ZIP 실패')):
                panel.enqueue(); self.pump(lambda: panel._jobs[0]['state'] == 'failed' and not panel.is_busy())
            image = Path(panel._outputs[0]['path']); before = image.read_bytes()
            panel.retry_failed(); self.pump(lambda: len(panel._jobs) == 2 and panel._jobs[1]['state'] == 'completed' and not panel.is_busy())
            self.assertEqual(image.read_bytes(), before); self.assertEqual(len(panel._outputs), 2)
            panel.retry_failed(); self.assertEqual(len(panel._jobs), 2)
            self.assertTrue(panel.shutdown())

    def test_nonblocking_shutdown_releases_worker(self):
        from PySide6.QtWidgets import QWidget
        from quick_actions_ui import QuickActionsPanel, _ACTIVE
        owner = QWidget(); panel = QuickActionsPanel(owner); release = threading.Event()
        panel._submit(lambda: release.wait(2), lambda _: None)
        before = time.monotonic(); self.assertFalse(panel.shutdown()); self.assertLess(time.monotonic() - before, .1)
        release.set(); self.pump(lambda: not panel.is_busy()); self.assertNotIn(panel, _ACTIVE)
        self.assertTrue(panel.shutdown())

if __name__ == '__main__': unittest.main(verbosity=2)
