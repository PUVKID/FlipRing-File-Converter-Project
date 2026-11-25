"""문서 입력 수리의 정상·안전 경계를 자체 생성 XML로 확인한다."""
from pathlib import Path
import tempfile
import unittest

import document_bridge
import document_formats


ABW_DTD = '<!DOCTYPE abiword PUBLIC "-//ABISOURCE//DTD AWML 1.0 Strict//EN" "http://www.abisource.com/awml.dtd">'
ABW_BODY = '<abiword xmlns="http://www.abisource.com/awml.dtd"><section><p>한글 hello world</p></section></abiword>'


class DocumentImport1121Tests(unittest.TestCase):
    def test_06_dif_korean_encodings_are_normalized_without_changing_original(self):
        content = 'TABLE\n0,1\n"한글 변환 시험"\n'
        for encoding in ('utf-8-sig', 'utf-16', 'cp949'):
            with self.subTest(encoding=encoding), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source, profile = root / '원본.dif', root / 'profile'
                profile.mkdir()
                original = content.encode(encoding)
                source.write_bytes(original)
                output = document_formats.prepare_import_source(source, 'dif', profile)
                self.assertEqual(content.encode('utf-8'), output.read_bytes())
                self.assertEqual(original, source.read_bytes())

    def test_01_dif_character_set_is_explicit_without_approving_interactions(self):
        handler = object()
        options = document_bridge.load_options(handler, "dif")
        self.assertEqual("DIF", options["FilterName"])
        self.assertEqual("76", options["FilterOptions"])
        self.assertEqual(0, options["MacroExecutionMode"])
        self.assertEqual(0, options["UpdateDocMode"])
        self.assertIs(handler, options["InteractionHandler"])

    def test_02_canonical_abiword_dtd_is_removed_only_in_private_copy(self):
        for encoding in ("utf-8", "utf-16", "utf-16-be"):
            with self.subTest(encoding=encoding), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source, profile = root / "원본.abw", root / "private"
                profile.mkdir()
                declaration = "utf-16" if encoding == "utf-16-be" else encoding
                raw = ('<?xml version="1.0" encoding="' + declaration + '"?>\n' + ABW_DTD + '\n' + ABW_BODY).encode(encoding)
                if encoding == "utf-16-be":
                    raw = b'\xfe\xff' + raw
                source.write_bytes(raw)
                document_formats.validate_input(source, "abw")
                copy = document_formats.prepare_import_source(source, "abw", profile)
                expected = raw.replace(ABW_DTD.encode(encoding).removeprefix(b'\xff\xfe'), b"")
                self.assertEqual(profile, copy.parent)
                self.assertEqual(raw, source.read_bytes())
                self.assertEqual(expected, copy.read_bytes())

    def test_03_abiword_without_dtd_reuses_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "원본.abw"
            source.write_text(ABW_BODY, encoding="utf-8")
            self.assertEqual(source, document_formats.prepare_import_source(source, "abw", root))
            self.assertEqual([source], list(root.iterdir()))

    def test_04_dtd_entity_and_internal_subsets_are_rejected_across_encodings(self):
        unsafe = [
            '<!DOCTYPE abiword SYSTEM "file:///C:/secret.dtd">',
            ABW_DTD[:-1] + ' [<!ENTITY sample SYSTEM "file:///C:/secret.txt">]>',
            ABW_DTD[:-1] + ' []>',
            ABW_DTD.replace("www.abisource.com", "other.example"),
            '<!DOCTYPE abiword [<!ENTITY sample "payload">]>',
        ]
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "unsafe.abw"
            for encoding in ("utf-8", "utf-16", "utf-16-be"):
                for doctype in unsafe:
                    with self.subTest(encoding=encoding, doctype=doctype):
                        declaration = "utf-16" if encoding == "utf-16-be" else encoding
                        raw = ('<?xml version="1.0" encoding="' + declaration + '"?>' + doctype + ABW_BODY).encode(encoding)
                        if encoding == "utf-16-be":
                            raw = b'\xfe\xff' + raw
                        source.write_bytes(raw)
                        with self.assertRaises(ValueError):
                            document_formats.validate_input(source, "abw")
                        self.assertEqual(raw, source.read_bytes())

    def test_05_other_xml_documents_keep_doctype_rejection_and_parse_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "unsafe.fodt"
            for extension in ("fodt", "fods", "fodp"):
                for encoding in ("utf-8", "utf-16"):
                    with self.subTest(extension=extension, encoding=encoding):
                        source.write_bytes((ABW_DTD + ABW_BODY).encode(encoding))
                        with self.assertRaises(ValueError):
                            document_formats.validate_input(source, extension)
            source.write_bytes(b"<abiword><section>")
            with self.assertRaises(ValueError):
                document_formats.validate_input(source, "abw")


if __name__ == "__main__":
    unittest.main()
