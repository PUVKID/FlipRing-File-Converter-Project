"""대기열 영속성·중단 경계·비공개 진단의 실제 파일 검사."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from PIL import Image
import quick_actions as core
import queue_journal as journal


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.output = self.root / '결과'; self.output.mkdir()
        self.source = self.root / '비공개이름.png'; Image.new('RGB', (20, 20), 'red').save(self.source)
        self.records = core.collect_inputs([self.source])['inputs']; self.action = copy.deepcopy(core.BUILTINS[0])
        self.ledger = core.OutputLedger(); self.store = journal.QueueJournal(self.root / '기록.json')
        self.job = {'id': '1234abcd', 'inputs': self.records, 'action': self.action, 'output': str(self.output),
                    'state': 'running', 'result': None, 'file_states': {str(self.source): 'waiting'},
                    'checkpoints': {str(self.source): {'input_sha256': core.digest(self.source), 'state': 'waiting', 'outputs': [], 'expected': 1}}}
    def event(self, event):
        journal.checkpoint_event(self.job, event)
        if event['state'] == 'completed': self.ledger.register(event.get('outputs', []))
        self.store.save([self.job], self.ledger)
    def run_job(self, cancel=None):
        return core.run_action(self.records, self.action, self.output, cancel, self.event, self.job['checkpoints'])
    def test_builtins_explicit_values(self):
        self.assertEqual(len(core.BUILTINS), 6)
        for row in core.BUILTINS: core.validate_action(row)
        self.assertEqual(core.BUILTINS[3]['max_bytes'], 1024 ** 2)
        self.assertEqual(core.BUILTINS[4]['width'], 0)
        self.assertEqual(core.BUILTINS[5]['format'], 'webp')
    def test_preview_matches_disk_and_batch_collisions(self):
        (self.output / '비공개이름.jpg').write_bytes(b'keep')
        rows = self.records * 2
        preview = core.preview_output_names(rows, self.action, self.output)
        result = core.run_action(rows, self.action, self.output)
        self.assertEqual([r['path'] for r in preview], [r['path'] for r in result['outputs']])
        self.assertEqual(Path(preview[0]['path']).name, '비공개이름 2.jpg')
        self.assertEqual((self.output / '비공개이름.jpg').read_bytes(), b'keep')
    def test_pdf_two_pages_preview_matches_all_collisions(self):
        import pypdfium2 as pdfium
        source = self.root / '두페이지.pdf'
        with pdfium.PdfDocument.new() as document:
            document.new_page(100, 100); document.new_page(100, 100); document.save(str(source))
        records = core.collect_inputs([source])['inputs'] * 2
        action = {**self.action, 'format': 'png'}
        (self.output / '두페이지-1.png').write_bytes(b'keep')
        before = core.digest(source)
        preview = core.preview_output_names(records, action, self.output)
        result = core.run_action(records, action, self.output)
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual([r['path'] for r in preview], [r['path'] for r in result['outputs']])
        self.assertEqual(len(preview), 4); self.assertEqual(core.digest(source), before)
    def test_preview_cancel_and_missing_tool_preserve_original(self):
        token = threading.Event(); token.set(); before = core.digest(self.source)
        with self.assertRaises((core.pdf_tools.Cancelled, core.engine.Cancelled)):
            core.preview_output_names(self.records, self.action, self.output, token)
        fake = self.root / '문서.docx'; fake.write_bytes(b'not opened by mocked engine')
        action = {**self.action, 'format': 'png'}
        with patch('quick_actions.workspace._single', side_effect=ValueError('공식 도구가 필요합니다.')):
            with self.assertRaisesRegex(ValueError, '공식 도구'):
                core.preview_output_names(core.collect_inputs([fake])['inputs'], action, self.output)
        self.assertEqual(core.digest(self.source), before); self.assertFalse(list(self.output.iterdir()))
    def test_office_preview_uses_real_temporary_engine_output(self):
        from docx import Document
        source = self.root / '문서.docx'; document = Document(); document.add_paragraph('Preview page one'); document.add_page_break(); document.add_paragraph('Preview page two'); document.save(str(source))
        action = {**self.action, 'format': 'png'}; records = core.collect_inputs([source])['inputs']
        before = core.digest(source)
        preview = core.preview_output_names(records, action, self.output)
        self.assertEqual(len(preview), 2); self.assertEqual(core.digest(source), before)
        self.assertFalse(list(self.output.iterdir()))
        result = core.run_action(records, action, self.output)
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual([r['path'] for r in preview], [r['path'] for r in result['outputs']])
    def test_restore_skips_valid_completed_output(self):
        result = self.run_job(); self.assertEqual(result['status'], 'completed', result)
        restored = journal.recover_jobs(self.store.load()['jobs'])[0]
        with patch('quick_actions.workspace.execute_workspace', side_effect=AssertionError('재변환 금지')):
            again = core.run_action(self.records, self.action, self.output, completed=restored['checkpoints'])
        self.assertEqual(again['status'], 'completed', again)
        self.assertEqual(result['outputs'], again['outputs'])
    def test_input_change_blocks_resume(self):
        self.run_job(); self.source.write_bytes(b'changed')
        recovered = journal.recover_jobs(self.store.load()['jobs'])[0]
        self.assertEqual(recovered['state'], 'review')
        result = core.run_action(self.records, self.action, self.output, completed=recovered['checkpoints'])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(len(list(self.output.glob('*.jpg'))), 1)
    def test_output_change_blocks_resume_and_cleanup(self):
        result = self.run_job(); target = Path(result['outputs'][0]['path']); target.write_bytes(b'changed')
        recovered = journal.recover_jobs(self.store.load()['jobs'])[0]
        self.assertEqual(recovered['state'], 'review')
        again = core.run_action(self.records, self.action, self.output, completed=recovered['checkpoints'])
        self.assertEqual(again['status'], 'failed'); self.assertTrue(self.ledger.cleanup([str(target)])['errors'])
        self.assertEqual(target.read_bytes(), b'changed')
    def test_crash_after_publish_before_completed_event(self):
        def crash(event):
            if event['state'] == 'completed': raise SystemExit('비정상 종료 모의')
            self.event(event)
        with self.assertRaises(SystemExit): core.run_action(self.records, self.action, self.output, on_event=crash, completed=self.job['checkpoints'])
        restored = journal.recover_jobs(self.store.load()['jobs'])[0]
        self.assertEqual(restored['checkpoints'][str(self.source)]['state'], 'completed')
        again = core.run_action(self.records, self.action, self.output, completed=restored['checkpoints'])
        self.assertEqual(again['status'], 'completed'); self.assertEqual(len(list(self.output.glob('*.jpg'))), 1)
    def test_cancel_and_partial_failure_keep_checkpoint(self):
        other = self.root / '둘.png'; Image.new('RGB', (20, 20), 'blue').save(other)
        self.records += core.collect_inputs([other])['inputs']; self.job['inputs'] = self.records
        self.job['file_states'][str(other)] = 'waiting'
        token = threading.Event()
        def cancel(event):
            self.event(event)
            if event['state'] == 'completed': token.set()
        result = core.run_action(self.records, self.action, self.output, token, cancel)
        self.assertEqual(result['status'], 'cancelled'); self.assertEqual(len(result['outputs']), 1)
        count = [0]; original = core.workspace.execute_workspace
        def fail_second(*args, **kwargs):
            count[0] += 1
            if count[0] == 2: raise OSError('의도한 두 번째 실패')
            return original(*args, **kwargs)
        with patch('quick_actions.workspace.execute_workspace', side_effect=fail_second):
            partial = core.run_action(self.records, self.action, self.output)
        self.assertEqual(partial['status'], 'failed'); self.assertEqual(len(partial['files']), 1)
    def test_damaged_and_oversized_state_preserved(self):
        self.store.path.write_bytes(b'{broken'); before = self.store.path.read_bytes()
        with self.assertRaises(ValueError): self.store.load()
        with self.assertRaises(ValueError): self.store.save([self.job], self.ledger)
        self.assertEqual(self.store.path.read_bytes(), before)
        self.store.path.write_bytes(b' ' * (journal.MAX_BYTES + 1))
        with self.assertRaises(ValueError): journal.QueueJournal(self.store.path).load()
    def test_invalid_state_rejected(self):
        self.job['inputs'][0]['relative'] = '../탈출.png'
        with self.assertRaises(ValueError): self.store.save([self.job], self.ledger)
    def test_cleanup_undo_survives_restart_and_collision(self):
        result = self.run_job(); path = result['outputs'][0]['path']
        self.ledger.on_change = lambda: self.store.save([self.job], self.ledger)
        self.assertEqual(len(self.ledger.cleanup([path])['moved']), 1)
        value = self.store.load(); restored = core.OutputLedger(); restored.rows = value['ledger']['rows']; restored.moves = value['ledger']['moves']
        Path(path).write_bytes(b'other'); self.assertTrue(restored.undo()['errors']); Path(path).unlink()
        self.assertEqual(restored.undo()['restored'], [path]); self.assertEqual(core.digest(path), result['outputs'][0]['sha256'])
    def test_shared_diagnostic_contains_only_allowlist(self):
        self.job['state'] = 'failed'; self.job['result'] = {'error': 'SECRET /private/name.txt 문서 본문'}
        value = journal.diagnostic([self.job]); encoded = json.dumps(value)
        self.assertEqual(set(value), {'version', 'jobs', 'states', 'extensions', 'error_codes'})
        for private in (str(self.root), self.source.name, self.action['name'], 'SECRET', '문서 본문'):
            self.assertNotIn(private, encoded)
        self.assertEqual(value['extensions'], {'png': 1})
    def test_zip_crash_does_not_recreate_bundle(self):
        self.action['zip'] = True
        def crash(event):
            if event['state'] == 'completed' and event['source'] == '': raise SystemExit('묶음 완료 직전 중단')
            self.event(event)
        with self.assertRaises(SystemExit):
            core.run_action(self.records, self.action, self.output, on_event=crash, completed=self.job['checkpoints'])
        restored = journal.recover_jobs(self.store.load()['jobs'])[0]
        self.assertEqual(restored['checkpoints']['']['state'], 'completed')
        with patch('quick_actions.create_bundle', side_effect=AssertionError('묶음 중복 생성 금지')):
            result = core.run_action(self.records, self.action, self.output, completed=restored['checkpoints'])
        self.assertEqual(result['status'], 'completed', result); self.assertEqual(len(list(self.output.glob('*.zip'))), 1)
    def test_invalid_result_type_preserves_existing_state(self):
        self.store.save([self.job], self.ledger); before = self.store.path.read_bytes()
        self.job['result'] = ['invalid']
        with self.assertRaises(ValueError): self.store.save([self.job], self.ledger)
        self.assertEqual(self.store.path.read_bytes(), before)
    def test_waiting_input_change_review(self):
        self.job['state'] = 'waiting'; self.store.save([self.job], self.ledger)
        self.assertEqual(journal.recover_jobs(self.store.load()['jobs'])[0]['state'], 'waiting')
        self.source.write_bytes(b'changed')
        self.assertEqual(journal.recover_jobs(self.store.load()['jobs'])[0]['state'], 'review')


class QueueUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
    def pump(self, condition):
        import time
        limit = time.monotonic() + 15
        while not condition() and time.monotonic() < limit:
            self.app.processEvents(); time.sleep(.01)
        self.app.processEvents(); self.assertTrue(condition())
    def test_restart_requires_explicit_resume_and_cleanup_by_job(self):
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QWidget
        from quick_actions_ui import QuickActionsPanel
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / '입력.png'; Image.new('RGB', (20, 20), 'red').save(source)
            owner = QWidget(); owner.pending = False; owner.settings = QSettings(str(root / '설정.ini'), QSettings.IniFormat)
            panel = QuickActionsPanel(owner); self.addCleanup(panel.shutdown)
            self.pump(lambda: not panel._tasks)
            panel.output.setText(str(root / '결과')); panel.add_paths([str(source)])
            self.pump(lambda: not panel._tasks); panel.pause(); panel.enqueue()
            self.pump(lambda: not panel._tasks); self.assertEqual(panel._jobs[0]['state'], 'waiting')
            self.assertTrue(panel.shutdown())
            second = QuickActionsPanel(owner); self.addCleanup(second.shutdown)
            self.pump(lambda: not second._tasks)
            self.assertTrue(second._paused); self.assertEqual(second._jobs[0]['state'], 'waiting')
            self.assertFalse(list((root / '결과').glob('*.jpg')))
            second.resume(); self.pump(lambda: second._jobs[0]['state'] == 'completed' and not second.is_busy())
            result = second._jobs[0]['result']['outputs'][0]; second.queue.setCurrentRow(0); second.cleanup_jobs()
            self.pump(lambda: not second.is_busy()); self.assertFalse(Path(result['path']).exists())
            self.assertTrue(second.shutdown())
            third = QuickActionsPanel(owner); self.addCleanup(third.shutdown)
            self.pump(lambda: not third._tasks); third.undo(); self.pump(lambda: not third.is_busy())
            self.assertEqual(core.digest(result['path']), result['sha256'])
    def test_delivery_busy_blocks_and_diagnostic_requires_preview(self):
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QWidget, QMessageBox
        from quick_actions_ui import QuickActionsPanel
        with tempfile.TemporaryDirectory() as temporary:
            owner = QWidget(); owner.pending = False
            owner.settings = QSettings(str(Path(temporary) / '설정.ini'), QSettings.IniFormat)
            owner.delivery_dialogs = [type('Busy', (), {'is_busy': lambda self: True})()]
            panel = QuickActionsPanel(owner); self.addCleanup(panel.shutdown); self.pump(lambda: not panel._tasks)
            self.assertTrue(panel._other_busy())
            with patch.object(QMessageBox, 'exec', return_value=QMessageBox.Cancel), patch.object(panel, 'choose_paths') as picker:
                panel.shared_diagnostic(); picker.assert_not_called()


if __name__ == '__main__': unittest.main()
