"""작업흐름의 원본 보존·취소·설정 유지 회귀 검사."""
import importlib.util
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import engine

class WorkbenchTests(unittest.TestCase):
    def test_workflow_contract_present(self):
        self.assertIsNotNone(importlib.util.find_spec('flipring_workflow'), '프리셋과 사전점검 기능이 필요합니다')

    def test_cancel_before_publish_preserves_original_and_existing(self):
        self.assertTrue(hasattr(engine, 'Cancelled'), '취소와 일반 오류를 구분해야 합니다')
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / '원본.png'
            Image.new('RGB', (20, 10), 'white').save(source)
            original = source.read_bytes()
            existing = source.with_suffix('.jpg'); existing.write_bytes(b'existing')
            cancel = threading.Event(); cancel.set()
            with self.assertRaises(engine.Cancelled):
                engine.convert(source, 'jpg', cancel=cancel)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(existing.read_bytes(), b'existing')
            self.assertEqual(len(list(Path(folder).iterdir())), 2)

    def test_presets_restart_delete_and_invalid(self):
        self.assertIsNotNone(importlib.util.find_spec('flipring_workflow'))
        from flipring_workflow import PresetStore
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'presets.json'
            store = PresetStore(path)
            store.save({'name': '내 사진', 'kind': 'convert', 'format': 'jpg', 'options': {}})
            self.assertEqual(PresetStore(path).items[0]['name'], '내 사진')
            with self.assertRaises(ValueError): store.save({'name': ' ', 'kind': 'convert', 'format': 'jpg'})
            with self.assertRaises(ValueError): store.save({'name': '잘못됨', 'kind': 'convert', 'format': '../png'})
            store.delete('내 사진')
            self.assertEqual(PresetStore(path).items, [])
            path.write_text('{broken', encoding='utf-8')
            broken = PresetStore(path)
            self.assertTrue(broken.error)
            with self.assertRaises(ValueError): broken.save({'name': '사진', 'kind': 'convert', 'format': 'jpg'})
            self.assertEqual(path.read_text(), '{broken')

    def test_preflight_missing_space_helper_and_source_reuse(self):
        self.assertIsNotNone(importlib.util.find_spec('flipring_workflow'))
        from flipring_workflow import preflight
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / '원본.png'; Image.new('RGB', (20, 10)).save(source)
            self.assertTrue(preflight(source, 'jpg')['ok'])
            self.assertFalse(preflight(source, 'png')['ok'])
            self.assertFalse(preflight(source.parent / '없음.png', 'jpg')['ok'])
            with patch('flipring_workflow.shutil.disk_usage', return_value=type('Space', (), {'free': 1})()):
                self.assertFalse(preflight(source, 'jpg')['ok'])
            import i18n
            original = source.read_bytes()
            with patch('engine.requirement', return_value='FFmpeg'):
                report = preflight(source, 'jpg')
            self.assertFalse(report['ok'])
            self.assertEqual(report['code'], 'helper')
            korean = 'FFmpeg 설치가 필요합니다. 외부 도우미 화면에서 설치 방법을 확인해 주세요.'
            english = 'FFmpeg is required. Open Helper tools for installation instructions.'
            self.assertEqual(report['error'], korean)
            self.assertEqual(i18n.error_text('ko', report['error']), korean)
            self.assertEqual(i18n.error_text('en', report['error']), english)
            self.assertEqual(i18n.error_text('ko', report['error']), korean)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(list(source.parent.iterdir()), [source])


    def test_rar_tools_missing_and_incomplete_bundle_preflight(self):
        from flipring_workflow import preflight
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / '원본.rar'; source.write_bytes(b'original')
            vendor = root / 'vendor/7zip'; vendor.mkdir(parents=True)
            (vendor / '7z.exe').write_bytes(b'incomplete')
            with patch.object(engine, '__file__', str(root / 'engine.py')), patch('engine.shutil.which', return_value=None), patch.dict('os.environ', {'ProgramFiles': folder}):
                self.assertFalse(any(engine.rar_tools().values()))
                self.assertEqual(engine.requirement(source, 'zip'), '7-Zip')
                report = preflight(source, 'zip')
                self.assertFalse(report['ok']); self.assertEqual(report['code'], 'helper')
                self.assertIn('7-Zip 설치가 필요합니다.', report['error'])
            self.assertEqual(source.read_bytes(), b'original')

    def test_rar_cancel_and_failure_terminate_only_created_descendants(self):
        import sys, time, rarfile
        for outcome in ('cancel', 'failure'):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); marker = root / '후손완료'; started = root / '후손시작'
                child = f"import time,pathlib; pathlib.Path({str(started)!r}).write_text('started'); time.sleep(2); pathlib.Path({str(marker)!r}).write_text('leaked')"
                parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(30)"
                cancel = threading.Event(); previous = getattr(engine._CONTEXT, 'cancel', None)
                original_popen = rarfile.Popen
                engine._CONTEXT.cancel = cancel
                try:
                    with self.assertRaises(engine.Cancelled if outcome == 'cancel' else RuntimeError):
                        with engine.rar_processes():
                            process = rarfile.custom_popen([sys.executable, '-c', parent])
                            deadline = time.monotonic() + 5
                            while not started.exists() and time.monotonic() < deadline: time.sleep(0.02)
                            self.assertTrue(started.exists())
                            if outcome == 'cancel':
                                cancel.set()
                                process.stdout.read()
                            else:
                                raise RuntimeError('제어된 해제 오류')
                    self.assertIsNotNone(process.poll())
                    self.assertIs(rarfile.Popen, original_popen)
                    time.sleep(2.1)
                    self.assertFalse(marker.exists())
                finally:
                    engine._CONTEXT.cancel = previous

    def test_rar_real_solid_payload_crc_original_and_corruption(self):
        import base64, hashlib, tarfile, zipfile, zlib, rarfile
        # rarfile 공식 테스트 자료의 UTF-8 이름 solid RAR, 원문 SHA로 고정한다.
        original = base64.b64decode('UmFyIRoHADvQcwgADQAAAAAAAAAc8XSAgDYAEQAAAAIAAAADU/xRZwKG5j4dNRYApIEAANGD0LjQuNC+0L7RgtC40LLQuy50eHSnGDDY998j8QAAv4hn9qn/1AX2dJCANAANAAAAAgAAAANT/FFnAobmPh01FACkgQAA8J2QgPCdkIHwnZCB8J2Qgi50eHSHrY13gwC/iGf2qf/UxD17AEAHAA==')
        self.assertEqual(hashlib.sha256(original).hexdigest(), '1d1d25ff7e1a4190055bda32a771a4a5e282ddd8078ce730ca44c45befcec176')
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / '원본 공백.rar'; source.write_bytes(original)
            saved = {name: getattr(rarfile, name) for name in ('Popen', 'CURRENT_SETUP', 'SEVENZIP_TOOL')}
            for target in ('zip', 'tar', 'tar.gz'):
                with self.subTest(target=target):
                    output = Path(engine.convert(source, target))
                    if target == 'zip':
                        with zipfile.ZipFile(output) as z: payload = {n: z.read(n) for n in z.namelist()}
                    else:
                        with tarfile.open(output) as z: payload = {n.name: z.extractfile(n).read() for n in z.getmembers() if n.isfile()}
                    self.assertEqual(payload, {'уииоотивл.txt': b'1\n', '𝐀𝐁𝐁𝐂.txt': b'1\n'})
                    self.assertTrue(all(zlib.crc32(v) == 1733426259 for v in payload.values()))
                    self.assertEqual(source.read_bytes(), original)
                    for name, value in saved.items(): self.assertIs(getattr(rarfile, name), value)
            with rarfile.RarFile(source) as z: offset = z.infolist()[0].data_offset
            damaged = bytearray(original); damaged[offset] ^= 0xff
            corrupt = Path(folder) / '손상.rar'; corrupt.write_bytes(damaged)
            with self.assertRaises((rarfile.Error, RuntimeError)): engine.convert(corrupt, 'zip')
            self.assertEqual(corrupt.read_bytes(), damaged)
            self.assertFalse(corrupt.with_suffix('.zip').exists())
            with self.assertRaises(FileNotFoundError): engine.convert(Path(folder) / '없음.rar', 'zip')
            self.assertEqual(source.read_bytes(), original)
            self.assertFalse(any(p.name.startswith('.puvkid-dragwheel-') for p in Path(folder).iterdir()))

    def test_rar_name_adapter_preserves_unicode_and_rejects_collisions(self):
        import rarfile
        a = rarfile.Rar3Info(); a.filename = '한글.txt'; a.flags = rarfile.RAR_FILE_UNICODE; a.orig_filename = b'not-used'
        b = rarfile.Rar5Info(); b.filename = '폴더/그림.txt'
        setup = rarfile.ToolSetup(rarfile.SEVENZIP_CONFIG)
        original = rarfile.CURRENT_SETUP
        with engine.rar_processes():
            engine.adapt_rar_names(setup, [a, b])
            self.assertEqual(rarfile.CURRENT_SETUP.open_cmdline(None, 'archive.rar', a.filename)[-1], a.filename)
            self.assertEqual(rarfile.CURRENT_SETUP.open_cmdline(None, 'archive.rar', '폴더\\그림.txt')[-1], '폴더\\그림.txt')
            self.assertIn('-spd', rarfile.CURRENT_SETUP.open_cmdline(None, 'archive.rar', a.filename))
            unchanged = rarfile.CURRENT_SETUP
            engine.adapt_rar_names(rarfile.ToolSetup(rarfile.UNRAR_CONFIG), [a])
            self.assertIs(rarfile.CURRENT_SETUP, unchanged)
            a.flags = 0; a.orig_filename = b'same'; b = rarfile.Rar3Info(); b.filename = 'other'; b.flags = 0; b.orig_filename = b'same'
            with self.assertRaisesRegex(ValueError, '중복'): engine.adapt_rar_names(setup, [a, b])
        self.assertIs(rarfile.CURRENT_SETUP, original)

    def test_rar_rejects_unsafe_paths_and_links_before_extraction(self):
        import rarfile
        from unittest.mock import Mock
        for name, symlink in (('../escape.txt', False), ('C:/escape.txt', False), ('link.txt', True)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); source = root / '원본.rar'; source.write_bytes(b'unchanged')
                entry = Mock(filename=name); entry.is_symlink.return_value = symlink
                archive = Mock(); archive.infolist.return_value = [entry]
                with patch.object(engine, 'setup_rar_tools'), patch.object(rarfile.RarFile, '__enter__', return_value=archive), patch.object(rarfile.RarFile, '__init__', return_value=None), patch.object(rarfile.RarFile, '__exit__', return_value=False):
                    work = root / '작업'; work.mkdir()
                    with self.assertRaises(ValueError): engine.archive(source, 'rar', 'zip', work / 'out.zip', work)
                archive.extractall.assert_not_called()
                self.assertEqual(source.read_bytes(), b'unchanged')

    def test_cancel_at_publication_removes_staging(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / '원본.png'; Image.new('RGB', (20, 10)).save(source)
            cancel = threading.Event()
            original_produce = engine.produce
            def finish_then_cancel(*args):
                result = original_produce(*args)
                cancel.set()
                return result
            with patch.object(engine, 'produce', side_effect=finish_then_cancel):
                with self.assertRaises(engine.Cancelled): engine.convert(source, 'jpg', cancel=cancel)
            self.assertEqual(list(Path(folder).iterdir()), [source])

    def test_external_cancel_terminates_descendant(self):
        import sys, time
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / '원본.png'; Image.new('RGB', (20, 10)).save(source)
            marker = Path(folder) / 'child-finished.txt'
            started = Path(folder) / 'child-started.txt'
            child = f"import time,pathlib; pathlib.Path({str(started)!r}).write_text('started'); time.sleep(2); pathlib.Path({str(marker)!r}).write_text('leaked')"
            parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(10)"
            cancel = threading.Event()
            def cancel_after_spawn():
                deadline = time.monotonic() + 4
                while not started.exists() and time.monotonic() < deadline: time.sleep(.02)
                cancel.set()
            thread = threading.Thread(target=cancel_after_spawn); thread.start()
            def external(*args): engine.run(sys.executable, ['-c', parent])
            try:
                with patch.object(engine, 'produce', side_effect=external):
                    with self.assertRaises(engine.Cancelled): engine.convert(source, 'jpg', cancel=cancel)
            finally: thread.join()
            self.assertTrue(started.exists())
            time.sleep(2.2)
            self.assertFalse(marker.exists(), '외부 도구 후손이 살아 있습니다')
            self.assertFalse(source.with_suffix('.jpg').exists())

    def test_pdf_preset_rejects_invalid_values_and_embedded_paths(self):
        from flipring_workflow import PresetStore
        with tempfile.TemporaryDirectory() as folder:
            store = PresetStore(Path(folder) / 'presets.json')
            for index, (extra, options) in enumerate((({}, {'operation': 'missing'}), ({}, {'dpi': True}), ({'paths': ['original.pdf']}, {}))):
                with self.subTest(extra=extra, options=options):
                    with self.assertRaises(ValueError):
                        store.save(dict(name=f'검증{index}', kind='pdf', format='pdf', options=options, **extra))
            self.assertEqual(store.items, [])

    def test_office_profile_is_independent_and_cleaned_on_all_outcomes(self):
        from urllib.request import url2pathname
        from urllib.parse import urlparse
        from docx import Document
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / ('긴작업경로' * 12)
            work.mkdir()
            source = work / '원본.docx'
            document = Document(); document.add_paragraph('원본 보존'); document.save(source)
            original = source.read_bytes()
            for outcome in ('success', 'failure', 'cancel'):
                profiles = []
                def tool_boundary(exe, args, cwd=None):
                    profile = Path(url2pathname(urlparse(args[0].split('=', 1)[1]).path))
                    profiles.append(profile)
                    self.assertTrue(profile.is_dir())
                    self.assertFalse(profile.is_relative_to(work))
                    if outcome == 'failure': raise RuntimeError('의도한 도우미 실패')
                    if outcome == 'cancel': raise engine.Cancelled('작업이 취소되었습니다.')
                    output = Path(args[args.index('--outdir') + 1]) / '원본.pdf'
                    output.write_bytes(b'completed-result')
                with self.subTest(outcome=outcome), patch.object(engine, 'run', side_effect=tool_boundary):
                    if outcome == 'success':
                        result = engine.office(source, 'pdf', work)
                        self.assertEqual(result.read_bytes(), b'completed-result')
                    else:
                        with self.assertRaises(RuntimeError): engine.office(source, 'pdf', work)
                    self.assertTrue(profiles)
                    self.assertTrue(all(not path.exists() for path in profiles))
                    self.assertEqual(source.read_bytes(), original)

    def test_preflight_write_denied(self):
        from flipring_workflow import preflight
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / '사진.png'; Image.new('RGB', (20, 10)).save(source)
            with patch('flipring_workflow.tempfile.TemporaryFile', side_effect=PermissionError('denied')):
                report = preflight(source, 'jpg')
            self.assertFalse(report['ok'])
            self.assertEqual(report['code'], 'write')

class WorkbenchUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        import app
        cls.application = QApplication.instance() or QApplication([])
        cls.directory = tempfile.TemporaryDirectory()
        cls.old_data = app.DATA
        app.DATA = Path(cls.directory.name)
        app.apply_application_style(cls.application)
        cls.window = app.MainWindow()
        cls.window.notify = lambda *args: None
        cls.window.show()
        cls.application.processEvents()

    @classmethod
    def tearDownClass(cls):
        import app
        cls.window.timer.stop(); cls.window.tray.hide(); cls.window.wheel.hide()
        cls.window.pool.shutdown(wait=True)
        cls.window.hide(); cls.window.deleteLater(); cls.application.processEvents()
        app.DATA = cls.old_data
        cls.directory.cleanup()

    def test_settings_are_separate_and_selection_has_preview(self):
        window = self.window
        self.assertTrue(hasattr(window, 'queue_list'), '파일별 목록이 필요합니다')
        self.assertFalse(window.tabs.widget(0).isAncestorOf(window.language_combo))
        path = Path(self.directory.name) / '사진.png'; Image.new('RGB', (30, 20)).save(path)
        window.set_files([str(path)])
        self.assertEqual(window.queue_list.count(), 1)
        self.assertIn('30 × 20', window.preview_panel.panels[0][2].text())
        self.assertTrue(window.run_button.isVisible())

    def test_reduced_motion_completes_open_wheel(self):
        from PySide6.QtCore import QPoint, QVariantAnimation
        from ui_motion import set_reduced_motion
        window = self.window
        window.wheel.display(QPoint(400, 400), preview=True)
        set_reduced_motion(window, True)
        self.assertNotEqual(window.wheel.motion.state(), QVariantAnimation.Running)
        window.wheel.dismiss()
        self.assertFalse(window.wheel.isVisible())
        set_reduced_motion(window, False)


    def wait_queue(self):
        import time
        from PySide6.QtTest import QTest
        deadline = time.monotonic() + 8
        while self.window.pending and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertEqual(self.window.pending, 0)

    def test_queue_failed_only_retry_and_no_duplicate(self):
        window = self.window
        good = Path(self.directory.name) / '성공.png'; Image.new('RGB', (25, 15)).save(good)
        bad = Path(self.directory.name) / '실패.png'; bad.write_bytes(b'not an image')
        records_before = len(window.records)
        window.set_files([str(good), str(bad)])
        window.enqueue([str(good), str(bad), str(good)], 'jpg')
        self.wait_queue()
        self.assertEqual([row['state'] for row in window.jobs], ['complete', 'failed'])
        self.assertIn('25 × 15', window.preview_panel.panels[1][2].text())
        output = Path(window.jobs[0]['output']); before = (output.read_bytes(), output.stat().st_mtime_ns)
        Image.new('RGB', (25, 15), 'red').save(bad)
        window.retry_failed(); self.wait_queue()
        self.assertEqual([row['state'] for row in window.jobs], ['complete', 'complete'])
        self.assertEqual((output.read_bytes(), output.stat().st_mtime_ns), before)
        self.assertEqual(len(window.records) - records_before, 3)
        self.assertTrue(good.exists()); self.assertTrue(bad.exists())

    def test_running_and_waiting_cancel_preserve_files(self):
        window = self.window
        paths = [Path(self.directory.name) / f'취소{i}.png' for i in range(2)]
        for path in paths: Image.new('RGB', (20, 10)).save(path)
        begun, release = threading.Event(), threading.Event()
        produce = engine.produce
        def held(*args):
            begun.set(); release.wait(3)
            return produce(*args)
        window.set_files(list(map(str, paths)))
        with patch.object(engine, 'produce', side_effect=held):
            window.enqueue(list(map(str, paths)), 'jpg')
            self.assertTrue(begun.wait(2))
            window.cancel_jobs(); release.set(); self.wait_queue()
        self.assertEqual([row['state'] for row in window.jobs], ['cancelled', 'cancelled'])
        for path in paths:
            self.assertTrue(path.exists()); self.assertFalse(path.with_suffix('.jpg').exists())
        window.retry_failed()
        self.assertEqual(window.pending, 0)

    def test_selection_explains_unsupported_missing_and_mixed_formats(self):
        window = self.window
        unknown = Path(self.directory.name) / '미지원.xyz'; unknown.write_bytes(b'original')
        absent = Path(self.directory.name) / '없음.png'
        window.set_files([str(unknown), str(absent)])
        self.assertEqual([row['state'] for row in window.jobs], ['failed', 'failed'])
        for index, row in enumerate(window.jobs):
            self.assertTrue(row['error'])
            self.assertTrue(window.queue_list.item(index).toolTip())
        self.assertFalse(window.run_button.isEnabled())
        self.assertFalse(window.retry_button.isEnabled())
        image = Path(self.directory.name) / '혼합사진.png'; Image.new('RGB', (10, 10)).save(image)
        audio = Path(self.directory.name) / '혼합소리.wav'; audio.write_bytes(b'RIFF')
        window.set_files([str(image), str(audio)])
        self.assertFalse(window.run_button.isEnabled())
        self.assertTrue(window.selection_issue)
        self.assertTrue(all(row['error'] for row in window.jobs))
        window.set_language('en')
        self.assertIn('common', window.preflight_label.text())
        window.set_language('ko')
        self.assertEqual(unknown.read_bytes(), b'original')
        self.assertEqual(window.pending, 0)

    def test_presets_pdf_apply_without_execution_and_motion_persists(self):
        window = self.window
        selected = Path(self.directory.name) / '스캔.png'
        Image.new('RGB', (30, 20)).save(selected)
        window.set_files([str(selected)])
        window.preset_combo.setCurrentIndex(1)
        window.apply_selected_preset()
        self.assertEqual(window.pdf_panel.operation.currentData(), 'recognize')
        self.assertEqual(window.pdf_panel.output.currentData(), 'pdf')
        self.assertFalse(window.pdf_panel.is_busy())
        self.assertEqual(window.pdf_panel.input_paths(), [str(selected)])
        window.reduced_motion_toggle.setChecked(True)
        from PySide6.QtCore import QSettings
        saved = QSettings(window.settings.fileName(), QSettings.IniFormat)
        self.assertTrue(saved.value('reduced_motion', False, type=bool))
        window.reduced_motion_toggle.setChecked(False)
        window.tabs.setCurrentIndex(0)

if __name__ == '__main__': unittest.main(verbosity=2)
