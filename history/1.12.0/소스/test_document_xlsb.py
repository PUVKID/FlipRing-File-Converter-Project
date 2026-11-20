"""XLSB의 실제 관계·내용 검사와 시트 전체 누락 방지를 검사한다."""
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

import document_xlsb


def record(number, payload=b''):
    def variable(value):
        result = bytearray()
        while True:
            result.append((value & 127) | (128 if value > 127 else 0))
            value >>= 7
            if not value:
                return bytes(result)
    return variable(number) + variable(len(payload)) + payload


def wide(value):
    return struct.pack('<I', len(value)) + value.encode('utf-16le')


def bundle(name, relation):
    return record(156, struct.pack('<II', 0, 1) + wide(relation) + wide(name))


def package(path, sheets, relations=None, shared_strings=None):
    relations = relations or [(f'rId{i}', 'worksheet', f'worksheets/sheet{i}.bin', '')
                              for i in range(1, len(sheets) + 1)]
    xml = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    for name, kind, target, mode in relations:
        xml += (f'<Relationship Id="{name}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/{kind}" '
                f'Target="{target}" TargetMode="{mode}"/>')
    if shared_strings is not None:
        xml += ('<Relationship Id="strings" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" '
                'Target="sharedStrings.bin"/>')
    xml += '</Relationships>'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('xl/workbook.bin', b''.join(bundle(name, f'rId{i}') for i, (name, _) in enumerate(sheets, 1)))
        archive.writestr('xl/_rels/workbook.bin.rels', xml)
        for i, (_, cells) in enumerate(sheets, 1):
            archive.writestr(f'xl/worksheets/sheet{i}.bin', record(145) + cells + record(146))
        if shared_strings is not None:
            archive.writestr('xl/sharedStrings.bin', b''.join(record(19, b'\0' + wide(value)) for value in shared_strings))


class XlsbIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='fr-xlsb-policy-')
        self.source = Path(self.temporary.name) / '시험.xlsb'

    def tearDown(self):
        self.temporary.cleanup()

    def test_01_relationship_order_does_not_change_sheet_mapping(self):
        package(self.source, [('첫째', record(5, bytes(8) + struct.pack('<d', 0))), ('빈 시트', b'')],
                [('rId2', 'worksheet', 'worksheets/sheet2.bin', ''),
                 ('rId1', 'worksheet', 'worksheets/sheet1.bin', '')])
        actual = document_xlsb.source_sheets(self.source)
        self.assertEqual([('첫째', True), ('빈 시트', False)], [(item['name'], item['nonblank']) for item in actual])
        self.assertEqual('xl/worksheets/sheet1.bin', actual[0]['part'])

    def test_02_zero_false_errors_and_empty_result_formulas_are_meaningful(self):
        for number, payload in [(2, bytes(12)), (3, bytes(9)), (4, bytes(9)), (5, bytes(16)),
                                (8, bytes(8) + wide('') + bytes(10)), (9, bytes(30)),
                                (10, bytes(23)), (11, bytes(23))]:
            with self.subTest(number=number):
                package(self.source, [('데이터', record(number, payload))])
                self.assertTrue(document_xlsb.source_sheets(self.source)[0]['nonblank'])

    def test_03_explicit_empty_strings_and_style_only_cells_are_blank(self):
        package(self.source, [('빈 값', record(1, bytes(8)) + record(6, bytes(8) + wide('')))])
        self.assertFalse(document_xlsb.source_sheets(self.source)[0]['nonblank'])

    def test_04_shared_strings_follow_the_actual_index(self):
        for index, expected in [(0, False), (1, True)]:
            with self.subTest(index=index):
                package(self.source, [('문자', record(7, bytes(8) + struct.pack('<I', index)))], shared_strings=['', '원문'])
                self.assertEqual(expected, document_xlsb.source_sheets(self.source)[0]['nonblank'])

    def test_05_chart_sheet_is_distinct_from_worksheet(self):
        package(self.source, [('차트', b'')], [('rId1', 'chartsheet', 'worksheets/sheet1.bin', '')])
        self.assertEqual('chartsheet', document_xlsb.source_sheets(self.source)[0]['kind'])

    def test_06_truncated_headers_and_payloads_are_rejected(self):
        for binary in [b'\x80', b'\x05\x80', b'\x05\x10' + bytes(8)]:
            with self.subTest(binary=binary):
                package(self.source, [('잘림', binary)])
                with self.assertRaises(ValueError):
                    document_xlsb.source_sheets(self.source)

    def test_07_external_relationship_is_never_followed(self):
        package(self.source, [('외부', b'')], [('rId1', 'worksheet', 'file:///D:/other/private.bin', 'External')])
        with self.assertRaisesRegex(ValueError, '관계|경로'):
            document_xlsb.source_sheets(self.source)

    def test_08_ambiguous_and_escaping_relationship_paths_are_rejected(self):
        for target in ['../../private.bin', 'worksheets/../sheet1.bin', 'C:/private.bin',
                       'worksheets\\sheet1.bin', '//host/private.bin', 'worksheets/%2e%2e/private.bin']:
            with self.subTest(target=target):
                package(self.source, [('경로', b'')], [('rId1', 'worksheet', target, '')])
                with self.assertRaises(ValueError):
                    document_xlsb.source_sheets(self.source)

    def test_09_duplicate_relationship_ids_are_rejected(self):
        package(self.source, [('중복', b'')], [('rId1', 'worksheet', 'worksheets/sheet1.bin', ''),
                                            ('rId1', 'worksheet', 'worksheets/sheet1.bin', '')])
        with self.assertRaises(ValueError):
            document_xlsb.source_sheets(self.source)

    def test_10_content_of_each_sheet_is_checked_instead_of_total(self):
        calls = []
        class Cells:
            def __init__(self, count): self.count = count
            def getCount(self): return self.count
        class Sheet:
            def __init__(self, count): self.count = count
            def queryContentCells(self, flags):
                calls.append(flags)
                return Cells(self.count)
        class Sheets:
            def hasByName(self, name): return True
            def getByName(self, name): return Sheet(1 if name == '정상' else 0)
        class Document:
            def getSheets(self): return Sheets()
        with self.assertRaisesRegex(ValueError, '누락'):
            document_xlsb.ensure_loaded_sheets(Document(), [dict(name='정상', kind='worksheet', nonblank=True),
                                                           dict(name='유실', kind='worksheet', nonblank=True)])
        self.assertEqual([23, 23], calls)

    def test_11_cancel_checkpoint_is_respected(self):
        package(self.source, [('취소', b'')])
        class Cancelled(Exception): pass
        def stop(): raise Cancelled()
        with self.assertRaises(Cancelled):
            document_xlsb.source_sheets(self.source, check_cancel=stop)

    def test_12_invalid_shared_string_index_is_rejected(self):
        package(self.source, [('잘못된 참조', record(7, bytes(8) + struct.pack('<I', 99)))], shared_strings=['원문'])
        with self.assertRaises(ValueError):
            document_xlsb.source_sheets(self.source)


if __name__ == '__main__':
    unittest.main()
