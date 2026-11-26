"""확장 준비 지연·상한·실패가 실제 변환 시작을 올바르게 제어하는지 검사한다."""
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch

import document_bridge


class OfficeStarted(Exception):
    """외부 Office를 실제 실행하지 않고 다음 단계 진입을 구분한다."""


class TimedInstall:
    """실제 대기 없이 전달된 예산과 완료 시각에 따라 결과를 돌려준다."""

    def __init__(self, seconds, returncode=0, stdout=b"", stderr=b""):
        self.seconds = seconds
        self.final_code = returncode
        self.stdout, self.stderr = stdout, stderr
        self.returncode = None
        self.stopped = False

    def communicate(self, timeout):
        if self.seconds > timeout:
            raise subprocess.TimeoutExpired("격리 확장 준비", timeout)
        self.returncode = self.final_code
        return self.stdout, self.stderr


class DocumentPrepareTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.source = root / "시험.hwpx"
        self.original = "준비 단계에서 보존할 원본".encode("utf-8")
        self.source.write_bytes(self.original)
        self.request = {"source": str(self.source), "output": str(root / "결과.docx"),
                        "profile": str(root / "profile"), "office": str(root / "program/soffice.exe"),
                        "family": "문서", "extension": "hwpx", "target": "docx",
                        "java": str(root / "java/bin/java.exe"), "oxt": str(root / "H2Orestart.oxt")}
        uno, helper, task = (ModuleType(name) for name in ("uno", "unohelper", "com.sun.star.task"))
        helper.Base = type("UnoBase", (), {})
        task.XInteractionHandler = type("InteractionHandler", (), {})
        self.uno_modules = {"uno": uno, "unohelper": helper, "com.sun.star.task": task}
        self.office_started = False

    def run_conversion(self, install):
        def start(command, **_options):
            if Path(command[0]).name in ("unopkg.com", "unopkg"):
                return install
            self.office_started = True
            raise OfficeStarted("확장 준비 뒤 실제 문서 변환 단계에 진입했습니다.")

        def stop(process):
            self.assertIs(install, process)
            process.stopped = True

        with patch.dict(sys.modules, self.uno_modules), \
                patch.object(document_bridge.subprocess, "Popen", side_effect=start), \
                patch.object(document_bridge, "_stop", side_effect=stop):
            return document_bridge.convert(self.request)

    def test_slow_initialization_reaches_office_without_reinstall_or_stopping(self):
        # 45초 예산으로 돌아가면 60·80초 준비가 다음 변환 단계에 도달하지 못한다.
        for duration in (60, 80):
            with self.subTest(duration=duration):
                install = TimedInstall(duration)
                self.office_started = False
                try:
                    self.run_conversion(install)
                except OfficeStarted:
                    pass
                except Exception as error:
                    self.fail("유한한 느린 초기화가 다음 단계 전에 실패했습니다: " + str(error))
                else:
                    self.fail("문서 변환 단계 진입 신호가 없습니다.")
                self.assertTrue(self.office_started)
                self.assertFalse(install.stopped)
                self.assertEqual(self.original, self.source.read_bytes())

    def test_preparation_beyond_budget_stops_owned_process_and_never_starts_office(self):
        # 새 유한 예산을 무제한 대기로 바꾸거나 회수를 빼면 실패한다.
        install = TimedInstall(130)
        with self.assertRaisesRegex(RuntimeError, "격리한 HWP 확장 준비 시간이 초과"):
            self.run_conversion(install)
        self.assertTrue(install.stopped)
        self.assertFalse(self.office_started)
        self.assertEqual(self.original, self.source.read_bytes())

    def test_nonzero_registration_keeps_diagnostic_and_never_starts_office(self):
        # 비정상 종료를 성공으로 삼거나 오류 원문을 버리면 실패한다.
        for stdout, stderr in ((b"fallback failure", b"registration failure"),
                               (b"registration failure", b"")):
            with self.subTest(stderr=bool(stderr)):
                install = TimedInstall(1, returncode=7, stdout=stdout, stderr=stderr)
                with self.assertRaisesRegex(RuntimeError, "registration failure"):
                    self.run_conversion(install)
                self.assertFalse(self.office_started)
                self.assertFalse(install.stopped)
                self.assertEqual(self.original, self.source.read_bytes())


if __name__ == "__main__":
    unittest.main()
