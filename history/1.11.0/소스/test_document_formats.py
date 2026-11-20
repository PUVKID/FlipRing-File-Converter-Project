"""대표 문서의 실제 변환 방향과 위험 입력 거부를 검사한다."""
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import warnings
import xml.etree.ElementTree as ET

import engine
import document_formats
import document_bridge


class DocumentFormatTests(unittest.TestCase):
    def test_01_representative_inputs_are_classified(self):
        expected = {
            "문서": "hwp hwpx doc docx docm dot dotx dotm odt ott fodt rtf txt md html xhtml epub pages wpd abw sxw stw",
            "프레젠테이션": "ppt pptx pptm pot potx potm pps ppsx ppsm odp otp fodp key",
            "스프레드시트": "xls xlsx xlsb xlsm xlt xltx xltm ods ots fods csv tsv dif slk numbers",
        }
        for kind, extensions in expected.items():
            for extension in extensions.split():
                with self.subTest(extension=extension):
                    self.assertIn(extension, engine.TABLE[kind][0].split())
                    self.assertEqual((kind, extension), engine.classify("시험." + extension))

    def test_02_hwp_is_import_only_and_preserves_document_targets(self):
        for extension in ("hwp", "hwpx"):
            options = engine.targets(["시험." + extension])
            self.assertIn("docx", options)
            self.assertIn("pdf", options)
            self.assertIn("odt", options)
            # 양방향 저장 요청에 따라 반대 native 목표만 명시적으로 허용한다.
            self.assertNotIn(extension, options)
            self.assertIn("hwpx" if extension == "hwp" else "hwp", options)

    def test_03_legacy_excel_can_be_created_without_binary_xlsb_claim(self):
        options = engine.targets(["시험.xlsx"])
        self.assertIn("xls", options)
        self.assertIn("ods", options)
        self.assertNotIn("xlsb", options)
        self.assertNotIn("xlsm", options)

    def test_04_presentation_can_be_saved_as_editable_office(self):
        options = engine.targets(["시험.ppt"])
        for target in ("pptx", "odp", "pdf", "jpg", "png", "txt"):
            self.assertIn(target, options)

    def test_05_mixed_selection_intersects_real_outputs(self):
        self.assertEqual({"pdf", "jpg", "png", "txt"},
                         set(engine.targets(["시험.hwpx", "발표.pptx"])))

    def test_06_missing_hwp_dependencies_are_specific(self):
        self.assertTrue(hasattr(engine, "hwp_status"))
        status = engine.hwp_status()
        self.assertIsInstance(status["ready"], bool)
        for key in ("code", "message", "oxt", "java"):
            self.assertIn(key, status)

    def test_07_cancel_prevents_document_processing(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "취소.hwpx"
            source.write_bytes(b"not-a-document")
            event = threading.Event()
            event.set()
            with self.assertRaises(engine.Cancelled):
                engine.convert(source, "pdf", cancel=event)
            self.assertEqual(b"not-a-document", source.read_bytes())
            self.assertEqual([source], list(Path(folder).iterdir()))

    def test_08_load_options_always_block_macros_and_updates(self):
        handler = object()
        for extension in ("xlsm", "docm", "pptm", "hwp", "hwpx"):
            properties = document_bridge.load_options(handler, extension)
            self.assertIs(properties["ReadOnly"], True)
            self.assertIs(properties["Hidden"], True)
            self.assertIs(properties.get("OnMainThread"), True)
            self.assertEqual(0, properties["MacroExecutionMode"])
            self.assertEqual(0, properties["UpdateDocMode"])
            self.assertIs(handler, properties["InteractionHandler"])

    def test_09_secured_profile_is_private_and_disables_active_content(self):
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / "격리"
            document_formats.write_secure_profile(profile)
            raw = (profile / "user/registrymodifications.xcu").read_text(encoding="utf-8")
            self.assertIn('oor:name="DisableMacrosExecution"', raw)
            self.assertIn('oor:name="DisableActiveContent"', raw)
            self.assertIn('oor:name="MacroSecurityLevel"', raw)
            self.assertIn('<value>3</value>', raw)

    def test_10_interactions_select_only_the_abort_continuation(self):
        self.assertTrue(hasattr(document_bridge, "abort_interaction"))
        selected = []
        expected_type = object()
        class Continuation:
            def __init__(self, name, is_abort):
                self.name, self.is_abort = name, is_abort
            def queryInterface(self, interface):
                self.asserted_type = interface
                return self if self.is_abort and interface is expected_type else None
            def select(self):
                selected.append(self.name)
        class Request:
            def getContinuations(self):
                return [Continuation("approve", False), Continuation("abort", True)]
        document_bridge.abort_interaction(Request(), expected_type)
        self.assertEqual(["abort"], selected)

    def test_11_input_validation_closes_file_handles(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "시험.rtf"
            path.write_bytes(b"{\\rtf1 test}")
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", ResourceWarning)
                document_formats.validate_input(path, "rtf")
            self.assertFalse([item for item in caught if issubclass(item.category, ResourceWarning)])

    def test_12_new_legacy_outputs_preflight_missing_office(self):
        with patch.object(engine, "tool", return_value=None):
            for extension in ("txt", "md", "html", "epub"):
                for target in ("doc", "odt", "rtf"):
                    with self.subTest(extension=extension, target=target):
                        self.assertIsNotNone(engine.requirement("시험." + extension, target))

    def test_13_export_options_keep_normalization_and_final_policies(self):
        self.assertTrue(hasattr(document_bridge, "export_options"))
        handler = object()
        normalization = None
        cases = [
            ("writer8", None, None),
            ("MS Word 97", "doc", None),
            ("Text - txt - csv (StarCalc)", "csv", "44,34,76,1,,0,false,true,true,false,false,0"),
            ("Text - txt - csv (StarCalc)", "tsv", "9,34,76,1,,0,false,true,true,false,false,0"),
            ("Text (encoded)", "txt", "UTF8,LF"),
        ]
        for filter_name, target, extra in cases:
            with self.subTest(target=target):
                options = document_bridge.export_options(handler, filter_name, target)
                expected = {"FilterName": filter_name, "Overwrite": False,
                            "InteractionHandler": handler, "OnMainThread": True}
                if extra is not None:
                    expected["FilterOptions"] = extra
                self.assertEqual(expected, options)
                self.assertIs(handler, options["InteractionHandler"])
                if target is None:
                    normalization = options
        # 다른 출력 형식의 추가 옵션이 정규화 요청으로 새지 않아야 한다.
        self.assertNotIn("FilterOptions", normalization)

    def test_14_secure_profile_prevents_initial_sidebar_creation(self):
        oor = "{http://openoffice.org/2001/registry}"
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder) / "격리"
            document_formats.write_secure_profile(profile)
            path = profile / "user/registrymodifications.xcu"
            root = ET.fromstring(path.read_bytes())
            self.assertEqual(oor + "items", root.tag)
            secure = {}
            for item in root:
                for prop in item.findall("prop"):
                    key = (item.get(oor + "path"), prop.get(oor + "name"))
                    self.assertNotIn(key, secure)
                    secure[key] = prop.find("value").text
            # 일회용 프로필의 새 필수 설정도 정확한 기대값으로 검사한다.
            self.assertEqual({
                ("/org.openoffice.Office.Common/Security/Scripting", "MacroSecurityLevel"): "3",
                ("/org.openoffice.Office.Common/Security/Scripting", "DisableMacrosExecution"): "true",
                ("/org.openoffice.Office.Common/Security/Scripting", "DisableActiveContent"): "true",
                ("/org.openoffice.Office.Common/Security/Scripting", "BlockUntrustedRefererLinks"): "true",
                ("/org.openoffice.Office.Common/Load", "UpdateDocMode"): "0",
                ("/org.openoffice.Office.Common/Misc", "UseOpenCL"): "false",
            }, secure)
            sidebar = [item for item in root if item.get(oor + "path") == "/org.openoffice.Office.Views/Windows"]
            self.assertEqual(1, len(sidebar))
            self.assertEqual(7, len(root))
            nodes = list(sidebar[0])
            self.assertEqual(5, len(nodes))
            self.assertEqual({name + "/10336" for name in ("scalc", "sdraw", "simpress", "smath", "swriter")},
                             {node.get(oor + "name") for node in nodes})
            with path.open("rb") as stream:
                namespaces = dict(value for event, value in ET.iterparse(stream, events=("start-ns",)))
            self.assertEqual("http://www.w3.org/2001/XMLSchema", namespaces.get("xs"))
            for node in nodes:
                with self.subTest(module=node.get(oor + "name")):
                    self.assertEqual("fuse", node.get(oor + "op"))
                    self.assertEqual(2, len(node))
                    visible = node.find("prop")
                    self.assertEqual("Visible", visible.get(oor + "name"))
                    self.assertEqual("false", visible.find("value").text)
                    userdata = node.find("node")
                    self.assertEqual("UserData", userdata.get(oor + "name"))
                    self.assertEqual(1, len(userdata))
                    data = userdata.find("prop")
                    self.assertEqual("Data", data.get(oor + "name"))
                    self.assertEqual("xs:string", data.get(oor + "type"))
                    self.assertEqual("fuse", data.get(oor + "op"))
                    self.assertIsNotNone(data.find("value"))
                    self.assertIn(data.find("value").text, (None, ""))


if __name__ == "__main__":
    unittest.main()
