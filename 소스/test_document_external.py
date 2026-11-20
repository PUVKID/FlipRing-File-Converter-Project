"""별도로 준비한 공개 원형 표본으로 HWP·HWPX·XLSB·암호 XLS를 검사한다.

표본은 저작권에 따라 별도 보관한다. 환경 변수로 표본 폴더를 지정할 수 있으며,
준비되지 않은 경우 건너뛰기를 성공으로 집계하지 않고 명확하게 실패한다.
"""
from pathlib import Path
from datetime import datetime
import hashlib
import os
import shutil
import struct
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
import zlib

import olefile

from docx import Document
from openpyxl import load_workbook
from openpyxl.utils.datetime import to_excel
import engine


FIXTURE_SHA256 = {
    'sample-5017.hwp': 'ff3faae938610fcfbedc21c27c507ca0cc038b44872b65d10fcad0b55af67ba2',
    'parashape.hwp': '1df75e74dff1b93f42ce88cfa0e362ae489756274eca0a2abcb2b34ddd7c9548',
    'table.hwp': 'df4746b82eea954a2aba36eb7dc51acf8cd975dced5e3331a1838932eaf123f9',
    'hwpx-sample.hwpx': '502d75c289813ce4b99648ecbc3cbe333bd8acd78e9f4b4b370566f308c1e6de',
    'Simple.xlsb': '41b0c82bfa682f968d69e05e23137232d6c89ea4f24439786f0b779be319929b',
    'sample.xlsb': '8cf995ace93f9d0e3bf34b6bdb1355ff46db2d418f6f3fb7943fdc4ca1db4d1b',
    'testVarious.xlsb': '8c600e97d719b0266dcfb49c1872feb8d10c6ed12bc768ff16ace7dae555ebfc',
    'rc4cryptoapi_password.xls': 'b804cba40c27ea88f2ea994b6b7d75145661532f9356e7246d2499f63d58abfe',
}


def fixture_directory():
    return Path(os.environ.get('FLIPRING_DOCUMENT_FIXTURES',
                               str(Path(__file__).resolve().parent.parent / 'work/document-fixtures110/upstream')))


def original_binary_records(data):
    """검사에서만 쓰는 독립 레코드 열거기다."""
    position = 0
    while position < len(data):
        record, shift = 0, 0
        while True:
            value = data[position]
            position += 1
            record |= (value & 0x7f) << shift
            if not value & 0x80:
                break
            shift += 7
        size, shift = 0, 0
        while True:
            value = data[position]
            position += 1
            size |= (value & 0x7f) << shift
            if not value & 0x80:
                break
            shift += 7
        payload = data[position:position + size]
        if len(payload) != size:
            raise ValueError('원형 표본의 레코드가 잘렸습니다.')
        position += size
        yield record, payload


def original_binary_strings(data):
    """시험 XLSB의 독립 BrtSSTItem 원문을 읽어 변환된 셀과 대조한다."""
    strings = []
    for record, payload in original_binary_records(data):
        if record == 0x13:
            length = int.from_bytes(payload[1:5], 'little')
            strings.append(payload[5:5 + length * 2].decode('utf-16le'))
    return strings


def original_binary_cells(data, strings):
    """상수 원문 값과 수식 위치를 결과 XLSX와 독립적으로 대조한다."""
    row = 0
    for record, payload in original_binary_records(data):
        if record == 0:
            row = int.from_bytes(payload[:4], 'little')
        if record not in range(2, 12):
            continue
        column = int.from_bytes(payload[:4], 'little')
        if record >= 8:
            yield row + 1, column + 1, 'formula', None
            continue
        if record == 2:
            raw = int.from_bytes(payload[8:12], 'little')
            if raw & 2:
                value = struct.unpack('<i', struct.pack('<I', raw))[0] >> 2
            else:
                value = struct.unpack('<d', struct.pack('<II', 0, raw & 0xfffffffc))[0]
            if raw & 1:
                value /= 100
        elif record == 5:
            value = struct.unpack('<d', payload[8:16])[0]
        elif record == 4:
            value = bool(payload[8])
        elif record == 6:
            length = int.from_bytes(payload[8:12], 'little')
            value = payload[12:12 + length * 2].decode('utf-16le')
        elif record == 7:
            value = strings[int.from_bytes(payload[8:12], 'little')]
        else:
            continue
        yield row + 1, column + 1, 'constant', value


class ExternalDocumentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='fr-external110-')
        self.root = Path(self.temporary.name)
        self.originals = {}

    def tearDown(self):
        for source, digest in self.originals.items():
            self.assertEqual(digest, hashlib.sha256(source.read_bytes()).hexdigest())
        self.temporary.cleanup()

    def copy_fixture(self, filename):
        source = fixture_directory() / filename
        self.assertTrue(source.is_file(), f'별도 실제 표본이 필요합니다: {source}')
        self.assertEqual(FIXTURE_SHA256[filename], hashlib.sha256(source.read_bytes()).hexdigest(),
                         '원형 표본의 고정 출처 해시와 다릅니다.')
        output = self.root / filename
        shutil.copyfile(source, output)
        self.originals[output] = hashlib.sha256(output.read_bytes()).hexdigest()
        return output

    def test_01_real_hwp5_converts_original_preview_text_to_word_and_pdf(self):
        source = self.copy_fixture('parashape.hwp')
        self.assertTrue(source.read_bytes().startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'))
        with olefile.OleFileIO(source) as original:
            preview = original.openstream('PrvText').read().decode('utf-16le')
        self.assertGreater(len(preview.strip()), 3)
        status = engine.hwp_status()
        self.assertTrue(status['ready'], status['message'])
        word = Path(engine.convert(source, 'docx'))
        document = Document(word)
        body = '\n'.join([p.text for p in document.paragraphs] +
                         [c.text for table in document.tables for row in table.rows for c in row.cells])
        self.assertEqual(''.join(preview.split()), ''.join(body.split()))
        pdf = Path(engine.convert(source, 'pdf'))
        with engine.pdfium.PdfDocument(str(pdf)) as parsed:
            self.assertGreater(len(parsed), 0)

    def test_02_real_hwpx_xml_text_is_preserved_in_word(self):
        source = self.copy_fixture('hwpx-sample.hwpx')
        with zipfile.ZipFile(source) as archive:
            names = [name for name in archive.namelist() if name.startswith('Contents/section') and name.endswith('.xml')]
            self.assertTrue(names)
            original = ''.join(element.text or '' for name in names for element in ET.fromstring(archive.read(name)).iter()
                               if element.tag.endswith('}t'))
        self.assertTrue(original.strip(), '표본의 실제 텍스트가 필요합니다.')
        word = Path(engine.convert(source, 'docx'))
        with zipfile.ZipFile(word) as archive:
            body = ''.join(element.text or '' for element in ET.fromstring(archive.read('word/document.xml')).iter()
                           if element.tag.endswith('}t'))
        # 두 형식의 줄·단락 공백을 정규화하고 모든 원문 문자와 숫자의 순서를 대조한다.
        self.assertEqual(''.join(original.split()), ''.join(body.split()))

    def test_03_unsupported_beta2_xlsb_is_refused_without_empty_output(self):
        source = self.copy_fixture('Simple.xlsb')
        with zipfile.ZipFile(source) as archive:
            self.assertIn('xl/workbook.bin', archive.namelist())
            original_strings = original_binary_strings(archive.read('xl/sharedStrings.bin'))
        self.assertTrue(original_strings)
        before = set(self.root.iterdir())
        with self.assertRaisesRegex((ValueError, RuntimeError), 'XLSB'):
            engine.convert(source, 'xlsx')
        self.assertEqual(before, set(self.root.iterdir()))

    def assert_modern_xlsb(self, filename):
        source = self.copy_fixture(filename)
        with zipfile.ZipFile(source) as archive:
            strings = original_binary_strings(archive.read('xl/sharedStrings.bin'))
            parts = sorted(name for name in archive.namelist()
                           if name.startswith('xl/worksheets/sheet') and name.endswith('.bin'))
            originals = [list(original_binary_cells(archive.read(part), strings)) for part in parts]
        workbook = load_workbook(engine.convert(source, 'xlsx'), data_only=False)
        try:
            self.assertEqual(len(parts), len(workbook.worksheets))
            checked_constants = checked_formulas = 0
            for sheet, cells in zip(workbook.worksheets, originals):
                for row, column, kind, value in cells:
                    actual = sheet.cell(row, column)
                    if kind == 'formula':
                        self.assertEqual('f', actual.data_type)
                        self.assertTrue(actual.value)
                        checked_formulas += 1
                    elif isinstance(value, (float, int)) and not isinstance(value, bool):
                        converted = to_excel(actual.value) if isinstance(actual.value, datetime) else actual.value
                        self.assertAlmostEqual(value, converted, delta=max(abs(value) * 1e-13, 1e-10))
                        checked_constants += 1
                    else:
                        self.assertEqual(value, actual.value if actual.value is not None else '')
                        checked_constants += 1
            self.assertGreater(checked_constants, 5)
            self.assertGreater(checked_formulas, 0)
        finally:
            workbook.close()

    def test_05_modern_xlsb_multiple_sheets_constants_and_formulas(self):
        self.assert_modern_xlsb('sample.xlsb')

    def test_06_modern_xlsb_numbers_dates_and_formulas(self):
        self.assert_modern_xlsb('testVarious.xlsb')

    def test_07_hwp_table_dimensions_match_original_binary_record(self):
        source = self.copy_fixture('table.hwp')
        dimensions = []
        with olefile.OleFileIO(source) as original:
            compressed = int.from_bytes(original.openstream('FileHeader').read()[36:40], 'little') & 1
            for name in original.listdir():
                if len(name) != 2 or name[0] != 'BodyText' or not name[1].startswith('Section'):
                    continue
                raw = original.openstream(name).read()
                data = zlib.decompress(raw, -15) if compressed else raw
                position = 0
                while position < len(data):
                    self.assertGreaterEqual(len(data) - position, 4)
                    header = int.from_bytes(data[position:position + 4], 'little')
                    position += 4
                    tag, size = header & 1023, header >> 20
                    if size == 4095:
                        self.assertGreaterEqual(len(data) - position, 4)
                        size = int.from_bytes(data[position:position + 4], 'little')
                        position += 4
                    payload = data[position:position + size]
                    self.assertEqual(size, len(payload))
                    position += size
                    if tag == 77:
                        self.assertGreaterEqual(size, 8)
                        dimensions.append(struct.unpack_from('<HH', payload, 4))
        self.assertTrue(dimensions)
        document = Document(engine.convert(source, 'docx'))
        self.assertEqual(dimensions, [(len(table.rows), len(table.columns)) for table in document.tables])

    def test_08_known_complex_hwp_failure_is_reported_without_new_output(self):
        source = self.copy_fixture('sample-5017.hwp')
        with olefile.OleFileIO(source) as original:
            self.assertGreater(len(original.openstream('PrvText').read()), 3)
        before = set(self.root.iterdir())
        with self.assertRaises((RuntimeError, ValueError)) as failure:
            engine.convert(source, 'docx')
        self.assertTrue(str(failure.exception))
        self.assertEqual(before, set(self.root.iterdir()))

    def test_04_encrypted_legacy_excel_is_aborted_without_new_output(self):
        source = self.copy_fixture('rc4cryptoapi_password.xls')
        before = set(self.root.iterdir())
        with self.assertRaises((RuntimeError, ValueError)) as failure:
            engine.convert(source, 'xlsx')
        self.assertTrue(str(failure.exception))
        self.assertEqual(before, set(self.root.iterdir()))


if __name__ == '__main__':
    unittest.main()
