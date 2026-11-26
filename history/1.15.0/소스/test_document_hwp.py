"""새 한글 출력의 내용 보존과 파서 이전 거부 경계를 검사한다."""
from pathlib import Path
import hashlib
import importlib
import importlib.util
import io
import tempfile
import struct
import unittest
from unittest.mock import patch
import zipfile
import xml.etree.ElementTree as ET

from docx import Document
from PIL import Image


class NativeHwpTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def core(self):
        self.assertIsNotNone(importlib.util.find_spec('document_hwp'), '새 native 저장 코어가 필요합니다.')
        return importlib.import_module('document_hwp')

    def package(self, entries, compression=zipfile.ZIP_DEFLATED):
        source = self.root / '입력.hwpx'
        with zipfile.ZipFile(source, 'w', compression=compression) as z:
            for name, data in entries:
                z.writestr(name, data)
        return source

    def test_guard_precedes_legacy_for_unsafe_zip(self):
        core = self.core()
        cases = [([('../escape.xml', b'<x/>')], zipfile.ZIP_DEFLATED),
                 ([('x.xml', b'<x/>'), ('X.xml', b'<x/>')], zipfile.ZIP_DEFLATED),
                 ([('x.xml', b'<x/>')], zipfile.ZIP_BZIP2),
                 ([('x.xml', b' ' * 5000 + b'<!DOCTYPE x [<!ENTITY a SYSTEM "file:///x">]><x/>')], zipfile.ZIP_DEFLATED)]
        for entries, compression in cases:
            with self.subTest(entries=entries[0][0], compression=compression):
                source = self.package(entries, compression)
                with patch('document_formats.validate_input', side_effect=AssertionError('가드 전에 호출됨')) as legacy:
                    with self.assertRaises(ValueError):
                        core.convert_document(source, 'hwp', self.root / '결과.hwp')
                    self.assertEqual(0, legacy.call_count)
                self.assertFalse((self.root / '결과.hwp').exists())

    def test_external_relation_and_unsupported_docx_refused(self):
        core = self.core()
        source = self.root / '외부.docx'
        doc = Document()
        p = doc.add_paragraph('문자')
        from docx.oxml import OxmlElement
        p._p.append(OxmlElement('w:fldSimple'))
        doc.save(source)
        with self.assertRaises(ValueError):
            core.convert_document(source, 'hwpx', self.root / '거부.hwpx')
        self.assertFalse((self.root / '거부.hwpx').exists())

    def test_txt_native_formats_and_round_trip(self):
        core = self.core()
        source = self.root / '문단.txt'
        original = '한글 English 2026\n둘째 문단 123\n'.encode('utf-8')
        source.write_bytes(original)
        hwpx = self.root / '결과.hwpx'
        report = core.convert_document(source, 'hwpx', hwpx)
        self.assertTrue(report['ok'])
        self.assertEqual('unverified', report['visual_complete_status'])
        self.assertFalse(report['render_checked'])
        hwp = self.root / '결과.hwp'
        report2 = core.convert_document(hwpx, 'hwp', hwp)
        self.assertTrue(report2['ok'])
        self.assertEqual(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1', hwp.read_bytes()[:8])
        reverse = self.root / '다시.hwpx'
        core.convert_document(hwp, 'hwpx', reverse)
        with zipfile.ZipFile(reverse) as z:
            section = ET.fromstring(z.read('Contents/section0.xml'))
        self.assertIn('한글 English 2026', ''.join(section.itertext()))
        self.assertEqual(original, source.read_bytes())

    def test_docx_order_bold_table_and_picture_bytes(self):
        core = self.core()
        source = self.root / '순서.docx'
        png = io.BytesIO()
        Image.new('RGB', (64, 48), (10, 20, 30)).save(png, 'PNG')
        image = png.getvalue()
        doc = Document()
        p = doc.add_paragraph('시작 ')
        p.add_run('굵게').bold = True
        table = doc.add_table(rows=3, cols=3)
        for r in range(3):
            for c in range(3):
                table.cell(r, c).text = f'셀{r}{c}'
        p = doc.add_paragraph('그림 앞')
        p.add_run().add_picture(io.BytesIO(image))
        p.add_run('그림 뒤').italic = True
        doc.add_paragraph('마지막')
        doc.save(source)
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        output = self.root / '순서.hwpx'
        core.convert_document(source, 'hwpx', output)
        with zipfile.ZipFile(output) as z:
            xml = ET.fromstring(z.read('Contents/section0.xml'))
            embedded = [z.read(n) for n in z.namelist() if n.startswith('BinData/')]
            head = ET.fromstring(z.read('Contents/header.xml'))
        ns = {'hp': 'http://www.hancom.co.kr/hwpml/2011/paragraph'}
        texts = [n.text for n in xml.findall('.//hp:t', ns) if n.text]
        self.assertLess(texts.index('굵게'), texts.index('셀00'))
        self.assertLess(texts.index('셀22'), texts.index('그림 앞'))
        self.assertLess(texts.index('그림 뒤'), texts.index('마지막'))
        self.assertIn(image, embedded)
        self.assertTrue(any(n.tag.endswith('}bold') for n in head.iter()))
        self.assertTrue(any(n.tag.endswith('}italic') for n in head.iter()))
        paragraph = next(p for p in xml.findall('.//hp:p', ns) if '그림 앞' in ''.join(p.itertext()))
        nodes = [n.tag.rsplit('}', 1)[-1] for n in paragraph.iter()]
        self.assertIn('pic', nodes)
        self.assertEqual(before, hashlib.sha256(source.read_bytes()).hexdigest())

    def test_collision_protection_and_bad_utf8_leave_originals(self):
        core = self.core()
        source = self.root / '입력.txt'
        source.write_bytes(b'\xff')
        output = self.root / '기존.hwpx'
        output.write_bytes(b'KEEP')
        with self.assertRaises((ValueError, FileExistsError)):
            core.convert_document(source, 'hwpx', output)
        self.assertEqual(b'KEEP', output.read_bytes())
        output.unlink()
        with self.assertRaises(ValueError):
            core.convert_document(source, 'hwpx', output)
        self.assertFalse(output.exists())
        self.assertEqual(b'\xff', source.read_bytes())

    def test_report_failure_and_content_loss_are_refused(self):
        core = self.core()
        with self.assertRaises(ValueError):
            core.require_no_loss({'unconverted': {'equations': 1}, 'dropped': {}})
        with self.assertRaises(ValueError):
            core.require_quality({'ok': False})

    def test_target_scope_keeps_legacy_reading(self):
        self.core()
        import engine
        for ext in ('docx', 'txt', 'hwp', 'hwpx'):
            targets = engine.targets(['입력.' + ext])
            self.assertIn('hwpx' if ext == 'hwp' else 'hwp', targets)
        for ext in ('doc', 'odt', 'md', 'pdf', 'xlsx'):
            self.assertNotIn('hwp', engine.targets(['입력.' + ext]))
            self.assertNotIn('hwpx', engine.targets(['입력.' + ext]))
        with patch.object(engine, 'tool', return_value=None):
            self.assertIsNone(engine.requirement('입력.docx', 'hwpx'))
            self.assertIsNotNone(engine.requirement('입력.hwp', 'pdf'))

    def test_relative_external_hwpx_manifest_refused(self):
        # 로컬 상대 외부 그림을 포함한 패키지의 운반도 금지한다.
        core = self.core()
        source = self.package([('Contents/content.hpf', b'<package><item id="img" href="../outside.png" isEmbeded="0"/></package>')])
        with self.assertRaises(ValueError):
            core.guard_package(source)

    def _hwp_streams(self):
        from hwpx import HwpxDocument
        from hwpx.hwp5.cfb import CompoundFile, read_all_streams
        doc = HwpxDocument.new(inherit_style=False)
        doc.add_paragraph('거부 경계 자체 표본')
        return dict(read_all_streams(CompoundFile(doc.to_bytes(format='hwp'))))

    def test_hwp_script_flag_refused(self):
        from hwpx.hwp5.cfb import build_compound_file
        streams = self._hwp_streams()
        head = bytearray(streams['FileHeader'])
        struct.pack_into('<I', head, 36, struct.unpack_from('<I', head, 36)[0] | 8)
        streams['FileHeader'] = bytes(head)
        with self.assertRaises(ValueError):
            self.core().guard_hwp(build_compound_file(streams.items()))

    def test_hwp_custom_script_and_linkdoc_refused(self):
        from hwpx.hwp5.cfb import build_compound_file
        from hwpx.hwp5.summary import write_scripts
        for name, payload in [('Scripts/DefaultJScript', write_scripts('alert(1)', '')),
                              ('DocOptions/_LinkDoc', 'relative.hwp'.encode('utf-16-le').ljust(524, b'\0'))]:
            with self.subTest(name=name):
                streams = self._hwp_streams()
                streams[name] = payload
                with self.assertRaises(ValueError):
                    self.core().guard_hwp(build_compound_file(streams.items()))

    def test_hwp_binary_link_refused(self):
        from hwpx.hwp5 import records, docinfo
        from hwpx.hwp5.cfb import build_compound_file
        streams = self._hwp_streams()
        data = records.inflate(streams['DocInfo'], 'DocInfo')
        payload = docinfo.BinDataItem(docinfo.BIN_LINK, abs_path='outside.png').encode()
        data += struct.pack('<I', records.BIN_DATA | (len(payload) << 20)) + payload
        streams['DocInfo'] = records.deflate(data)
        with self.assertRaises(ValueError):
            self.core().guard_hwp(build_compound_file(streams.items()))


    def test_security63_hwpx_manifest_links_and_missing_parts(self):
        # 내부 표시만으로 외부·누락 부품을 허용하면 이 검사가 실패한다.
        for href, embedded in [('outside.png', '0'), ('/outside.png', '1'),
                               ('C:/outside.png', '1'), ('https://example.invalid/a', '1'),
                               ('../outside.png', '1'), ('missing.png', '1')]:
            with self.subTest(href=href, embedded=embedded):
                xml = f'<package><item href="{href}" isEmbeded="{embedded}"/></package>'.encode()
                source = self.package([('Contents/content.hpf', xml)])
                with self.assertRaises(ValueError):
                    self.core().guard_package(source)

    def test_security63_hwpx_scripts_and_linkinfo(self):
        # 매니페스트에 없는 실제 스크립트도 지우거나 운반하지 않고 거부한다.
        cases = [[('Scripts/sourceScripts', 'alert(1)'.encode('utf-16-le'))],
                 [('Scripts/unknown', b'unknown')],
                 [('Contents/header.xml', b'<head><docOption><linkinfo path="relative.hwp"/></docOption></head>')],
                 [('Contents/content.hpf', b'<package><item id="sourcesc" href="Custom/code"/></package>'),
                  ('Custom/code', 'alert(1)'.encode('utf-16-le'))]]
        for entries in cases:
            with self.subTest(part=entries[0][0]):
                with self.assertRaises(ValueError):
                    self.core().guard_package(self.package(entries))

    def test_security63_unknown_hwp_script_parts_and_trailing_bytes(self):
        from hwpx.hwp5.cfb import build_compound_file
        from hwpx.hwp5.summary import write_scripts
        for name, payload in [('Scripts/Other', b'unknown'),
                              ('Scripts/DefaultJScript', write_scripts('', '') + b'unknown'),
                              ('Scripts/JScriptVersion', b'unknown')]:
            with self.subTest(name=name):
                streams = self._hwp_streams()
                streams[name] = payload
                with self.assertRaises(ValueError):
                    self.core().guard_hwp(build_compound_file(streams.items()))

    def test_security63_rejected_conversion_never_reaches_legacy_or_output(self):
        source = self.package([('Scripts/sourceScripts', 'alert(1)'.encode('utf-16-le'))])
        before = source.read_bytes()
        output = self.root / '거부.hwp'
        with patch('document_formats.validate_input', side_effect=AssertionError('조기 가드 누락')) as legacy:
            with self.assertRaises(ValueError):
                self.core().convert_document(source, 'hwp', output)
            self.assertEqual(0, legacy.call_count)
        self.assertEqual(before, source.read_bytes())
        self.assertFalse(output.exists())

    def test_security63_known_default_stubs_remain_supported(self):
        from hwpx.hwp5.cfb import build_compound_file
        from hwpx.hwp5.summary import DEFAULT_HEADER_SCRIPT, DEFAULT_SOURCE_SCRIPT, write_scripts
        for header in ('', DEFAULT_HEADER_SCRIPT):
            for source in ('', DEFAULT_SOURCE_SCRIPT):
                with self.subTest(header=bool(header), source=bool(source)):
                    streams = self._hwp_streams()
                    streams['Scripts/DefaultJScript'] = write_scripts(header, source)
                    self.core().guard_hwp(build_compound_file(streams.items()))
                    for prefix in (b'', b'\xff\xfe'):
                        entries = [('Scripts/headerScripts', prefix + header.encode('utf-16-le')),
                                   ('Scripts/sourceScripts', prefix + source.encode('utf-16-le'))]
                        self.core().guard_package(self.package(entries))

    def test_security63_layout_unverified_is_not_success(self):
        report = {'ok': True, 'render_checked': False, 'visual_complete': False,
                  'open_safety': {'ok': True}, 'semantic': {'ok': True}, 'form': {'ok': True},
                  'layout': {'ok': True, 'status': 'unverified'}}
        with self.assertRaises(ValueError):
            self.core().require_quality(report)

    def test_security65_unknown_hwp_streams_refused_before_publish(self):
        # 알려지지 않은 사용자 내용이 빈 손실 보고서로 사라지는 회귀를 막는다.
        from hwpx.hwp5.cfb import build_compound_file
        for index, name in enumerate(('Custom/UserContent', 'DocOptions/UserData', 'BodyText/Extra')):
            with self.subTest(stream=name):
                streams = self._hwp_streams()
                streams[name] = '보존하거나 명시 거부해야 할 데이터'.encode('utf-8')
                source = self.root / f'미지{index}.hwp'
                source.write_bytes(build_compound_file(streams.items()))
                before = source.read_bytes()
                output = self.root / f'미지{index}.hwpx'
                with self.assertRaises(ValueError):
                    self.core().convert_document(source, 'hwpx', output)
                self.assertEqual(before, source.read_bytes())
                self.assertFalse(output.exists())

    def test_security65_unlisted_binary_stream_refused(self):
        from hwpx.hwp5.cfb import build_compound_file
        from hwpx.hwp5.records import deflate
        image = io.BytesIO()
        Image.new('RGB', (2, 2), (1, 2, 3)).save(image, 'PNG')
        streams = self._hwp_streams()
        streams['BinData/BIN0001.png'] = deflate(image.getvalue())
        with self.assertRaises(ValueError):
            self.core().guard_hwp(build_compound_file(streams.items()))

    def test_security65_preview_omission_is_reported_for_actual_input(self):
        from hwpx.hwp5.cfb import build_compound_file
        image = io.BytesIO()
        Image.new('RGB', (2, 2), (1, 2, 3)).save(image, 'PNG')
        streams = self._hwp_streams()
        streams['PrvImage'] = image.getvalue()
        source = self.root / '미리보기.hwp'
        source.write_bytes(build_compound_file(streams.items()))
        before = source.read_bytes()
        report = self.core().convert_document(source, 'hwpx', self.root / '미리보기.hwpx')
        metadata = report.get('hwp_input_metadata', {})
        self.assertEqual(['PrvImage'], metadata.get('omitted_derived_streams'))
        self.assertIn('\x05HwpSummaryInformation', metadata.get('standard_metadata_streams', []))
        self.assertEqual(before, source.read_bytes())

if __name__ == '__main__':
    unittest.main()
