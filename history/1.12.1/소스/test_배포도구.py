"""실제 컴파일 없이 작은 원본으로 배포 경계의 실패 보호를 검사한다."""
import json
import ast
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import 배포빌드 as delivery


class DeliveryBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "입력"
        self.root.mkdir()
        for name, value in {"소스/app.py": b"print('test')\n", "소스/licenses/COPYING": b"notice",
                            "소스/licenses/archive.tar.gz": b"original source bytes", "검사도구/check.py": b"pass\n"}.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
        self.config = {"version": "1.11.0", "required": ["소스/app.py", "소스/licenses/COPYING", "검사도구/check.py"],
                       "excluded_files": {}, "excluded_dirs": {}, "runtime_source_archive_allowlist": [
                           delivery.record(self.root / "소스/licenses/archive.tar.gz", "소스/licenses/archive.tar.gz")]}
        self.prepared = {"schema": 1, "config": self.config, "source_tree": delivery.snapshot(self.root),
                         "source_root": str(self.root)}
        self.target = self.base / "배포" / delivery.SOURCE_ZIP_NAME

    def freeze(self):
        return delivery.freeze_source(self.root, self.prepared, self.target)

    def test_exact_zip_roundtrip_and_all_code_coverage(self):
        result = self.freeze()
        delivery.verify_zip(self.target, result["entries"])
        self.assertEqual({e["path"] for e in result["entries"]}, {e["path"] for e in self.prepared["source_tree"]})
        self.assertEqual(delivery.snapshot(self.root), self.prepared["source_tree"])

    def test_all_product_code_assets_and_small_sources_are_included(self):
        extra = {"소스/nested/new_product.py": b"product", "소스/new_test.py": b"test",
                 "소스/assets/required.svg": b"svg", "소스/vendor/runtime.dll": b"runtime",
                 "소스/licenses/small-source.tar.gz": b"small legal source"}
        for name, content in extra.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.prepared["source_tree"] = delivery.snapshot(self.root)
        manifest = self.freeze()
        self.assertEqual({entry["path"] for entry in manifest["entries"]}, set(extra) | {
            "소스/app.py", "소스/licenses/COPYING", "소스/licenses/archive.tar.gz", "검사도구/check.py"})
        with zipfile.ZipFile(self.target) as archive:
            for name, content in extra.items():
                self.assertEqual(archive.read(name), content)

    def test_archive_missing_and_same_length_tamper_fail(self):
        archive = self.root / "소스/licenses/archive.tar.gz"
        for value in (None, b"X" * archive.stat().st_size):
            with self.subTest(value=value):
                if value is None:
                    archive.unlink()
                else:
                    archive.write_bytes(value)
                with self.assertRaises(delivery.DeliveryError):
                    self.freeze()
        self.assertFalse(self.target.exists())

    def test_missing_original_notice_fails(self):
        (self.root / "소스/licenses/COPYING").unlink()
        with self.assertRaises(delivery.DeliveryError):
            self.freeze()

    def test_exclusion_cannot_hide_python_or_required_assets(self):
        self.config["excluded_files"] = {"소스/app.py": "금지된 제품 제외"}
        with self.assertRaises(delivery.DeliveryError):
            self.freeze()

    def test_zip_rejects_extra_missing_escape_duplicate_and_case_collision(self):
        expected = self.prepared["source_tree"]
        for bad in ("extra", "missing", "../escape", "duplicate", "case"):
            with self.subTest(bad=bad):
                target = self.base / (bad.replace("/", "_") + ".zip")
                with zipfile.ZipFile(target, "w") as archive:
                    for entry in expected[1:] if bad == "missing" else expected:
                        archive.writestr(entry["path"], (self.root / entry["path"]).read_bytes())
                    if bad == "duplicate":
                        archive.writestr(expected[0]["path"], b"duplicate")
                    elif bad == "case":
                        archive.writestr("소스/APP.py", b"case")
                    elif bad != "missing":
                        archive.writestr(bad, b"unknown")
                with self.assertRaises(delivery.DeliveryError):
                    delivery.verify_zip(target, expected)

    def test_source_change_during_freeze_preserves_failed_partial(self):
        from unittest.mock import patch
        original = delivery.verify_zip
        def mutate(*args):
            original(*args)
            (self.root / "소스/new.py").write_text("changed", encoding="utf-8")
        with patch.object(delivery, "verify_zip", side_effect=mutate):
            with self.assertRaises(delivery.DeliveryError):
                self.freeze()
        self.assertFalse(self.target.exists())
        self.assertTrue(self.target.with_suffix(".zip.partial").is_file())

    def test_existing_output_and_source_inside_output_fail(self):
        self.freeze()
        with self.assertRaises(delivery.DeliveryError):
            self.freeze()
        with self.assertRaises(delivery.DeliveryError):
            delivery.external_path(self.root, self.root / "output")
        with self.assertRaises(delivery.DeliveryError):
            delivery.freeze_source(self.root, self.prepared, self.base / "다른이름.zip")

    def test_runtime_only_exact_allowlist_can_resolve_from_zip(self):
        manifest = self.freeze()
        runtime = self.base / "runtime"
        runtime.mkdir()
        resolver = delivery.ArchiveResolver(runtime, self.target, manifest, self.config)
        exact = runtime / "licenses/archive.tar.gz"
        self.assertEqual(resolver.resolve(exact).read_bytes(), b"original source bytes")
        with self.assertRaises(delivery.DeliveryError):
            resolver.resolve(runtime / "licenses/unlisted.tar.gz")
        with self.assertRaises(delivery.DeliveryError):
            resolver.resolve(runtime / "../escape")

    def test_runtime_archive_presence_is_rejected(self):
        manifest = self.freeze()
        runtime = self.base / "runtime"
        (runtime / "licenses").mkdir(parents=True)
        (runtime / "licenses/archive.tar.gz").write_bytes(b"stale archive")
        with self.assertRaises(delivery.DeliveryError):
            delivery.ArchiveResolver(runtime, self.target, manifest, self.config)

    def test_prepare_generates_portable_inputs_without_compiler_call(self):
        import build
        source = self.root / "소스"
        (source / "assets").mkdir()
        with patch.object(build, "environment", return_value={"packages": {}}), \
                patch.object(build, "collect_legal_notices", return_value=[]), \
                patch.object(build, "run_owned") as compile_call, \
                patch.object(delivery, "load", return_value=self.config):
            prepared = build.prepare(source, self.base / "output", self.base / "work", self.base / "ISCC.exe")
        compile_call.assert_not_called()
        self.assertEqual(prepared["source_tree"], delivery.snapshot(self.root))
        spec = (source / "FlipRing.spec").read_text(encoding="utf-8")
        installer = (source / "installer.iss").read_text(encoding="utf-8-sig")
        self.assertIn("FLIPRING_SOURCE", spec)
        self.assertIn("FLIPRING_PROGRAM", installer)
        self.assertNotIn(str(self.root), spec + installer)
        self.assertNotIn("1.10.0", (source / "version-info.txt").read_text(encoding="utf-8"))
        compile(spec, "FlipRing.spec", "exec")

    def test_stale_notice_overlay_and_missing_notice_are_rejected(self):
        manifest = self.freeze()
        source, program = self.root / "소스", self.base / "program"
        program.mkdir()
        delivery.stage_legal(source, program, manifest, self.config)
        delivery.verify_runtime_legal(source, program, manifest, self.config)
        for name in ("licenses/COPYING", "licenses/전체소스_안내.txt"):
            path = program / name
            content = path.read_bytes()
            path.unlink()
            with self.assertRaises(delivery.DeliveryError):
                delivery.verify_runtime_legal(source, program, manifest, self.config)
            path.write_bytes(content)
        (program / "licenses/stale.txt").write_text("old", encoding="utf-8")
        with self.assertRaises(delivery.DeliveryError):
            delivery.verify_runtime_legal(source, program, manifest, self.config)
        with self.assertRaises(delivery.DeliveryError):
            delivery.stage_legal(source, program, manifest, self.config)

    def test_compile_failure_stops_installer_and_detects_source_mutation(self):
        import build
        manifest = self.freeze()
        self.prepared["environment"] = {"fake": "fixed tool"}
        work = self.base / "compile-work"
        work.mkdir()
        def failing_compiler(*args):
            (self.root / "소스/app.py").write_text("changed", encoding="utf-8")
            raise delivery.DeliveryError("주입한 컴파일 실패")
        with patch.object(build, "environment", return_value=self.prepared["environment"]), \
                patch.object(build, "run_owned", side_effect=failing_compiler) as call, \
                patch.dict("os.environ", {"WINDIR": "C:/Windows"}):
            with self.assertRaisesRegex(delivery.DeliveryError, "동결 소스"):
                build.compile_prepared(self.root / "소스", self.prepared, manifest, self.target.parent, work, self.base / "ISCC.exe")
        self.assertEqual(call.call_count, 1)
        self.assertFalse((self.target.parent / "설치파일").exists())

    def test_changed_compiler_or_dependency_environment_blocks_compile(self):
        import build
        manifest = self.freeze()
        self.prepared["environment"] = {"compiler_version": "6.original"}
        work = self.base / "compile-work"
        work.mkdir()
        with patch.object(build, "environment", return_value={"compiler_version": "6.changed"}), \
                patch.object(build, "run_owned") as run:
            with self.assertRaisesRegex(delivery.DeliveryError, "컴파일러"):
                build.compile_prepared(self.root / "소스", self.prepared, manifest, self.target.parent, work, self.base / "ISCC.exe")
        run.assert_not_called()

    def test_held_input_blocks_before_any_generation(self):
        import build
        self.config["held_inputs"] = {"소스/test-fixtures/sample.heic": "권한 보류"}
        with patch.object(delivery, "load", return_value=self.config), patch.object(build, "generate_build_inputs") as generate:
            with self.assertRaisesRegex(delivery.DeliveryError, "보류"):
                build.prepare(self.root / "소스", self.base / "output", self.base / "work", self.base / "ISCC.exe")
        generate.assert_not_called()

    def test_unclassified_parent_document_and_private_tree_do_not_leak(self):
        self.config["source_roots"] = ["소스", "검사도구", "docs", "work"]
        (self.root / "docs").mkdir()
        (self.root / "docs/내부계획.md").write_text("private", encoding="utf-8")
        with self.assertRaisesRegex(delivery.DeliveryError, "분류"):
            delivery.classified_entries(self.root, self.config)
        self.config["excluded_files"] = {"docs/내부계획.md": "제품 입력이 아닌 공개 미승인 운영 문서"}
        self.config["excluded_dirs"] = {"work": "내부 운영 기록"}
        (self.root / "work").mkdir()
        (self.root / "work/사적인파일이름.txt").write_text("private", encoding="utf-8")
        included, excluded = delivery.classified_entries(self.root, self.config)
        self.assertNotIn("work/사적인파일이름.txt", json.dumps(excluded, ensure_ascii=False))
        self.assertEqual({entry["path"] for entry in included}, {entry["path"] for entry in self.prepared["source_tree"]})
        self.assertEqual({entry["path"] for entry in excluded}, {"work/", "docs/내부계획.md"})

    def test_interrupted_zip_keeps_partial_and_never_promotes(self):
        before = delivery.snapshot(self.root)
        with patch.object(zipfile.ZipFile, "write", side_effect=KeyboardInterrupt("제어된 중단")):
            with self.assertRaises(KeyboardInterrupt):
                self.freeze()
        self.assertFalse(self.target.exists())
        self.assertTrue(self.target.with_suffix(".zip.partial").exists())
        self.assertEqual(before, delivery.snapshot(self.root))

    def test_reparse_point_and_windows_ambiguous_paths_are_rejected(self):
        from types import SimpleNamespace
        real = Path.lstat
        def attributes(path, *args, **kwargs):
            info = real(path, *args, **kwargs)
            if path == self.root / "소스":
                return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
            return info
        # 실제 연결을 만들지 않고 OS 재분석 플래그만 주입한다.
        with patch.object(Path, "lstat", attributes):
            with self.assertRaisesRegex(delivery.DeliveryError, "재분석"):
                delivery.snapshot(self.root)
        for name in ("/absolute", "C:/drive", "a\\b", "a/../b", "CON.txt", "a./b", "a//b"):
            with self.subTest(name=name), self.assertRaises(delivery.DeliveryError):
                delivery.relative_name(name)


class PackagingConnectionTests(unittest.TestCase):
    """실제 진입점의 마지막 package 호출을 작은 가상 배포물로 연결한다."""
    TOOLS = ("regression19.py", "new_suites19.py", "run_new_suite19.py", "release_capture.py",
             "documents_suites110.py", "run_documents_suite110.py")

    def setUp(self):
        DeliveryBoundaryTests.setUp(self)

    def package_fixture(self):
        import package
        source = self.root / "소스"
        release = self.target.parent
        program = release / "프로그램/FlipRing"
        program.mkdir(parents=True)
        # 법적 검증의 작은 입력을 채우되 검사도구의 staging 사본은 만들지 않는다.
        tree = ast.parse(Path(package.__file__).read_text(encoding="utf-8"))
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
        prefix, active = [], False
        for node in main.body:
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "program" for target in node.targets):
                active = True
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "missing" for target in node.targets):
                break
            if active and not isinstance(node, ast.Expr):
                prefix.append(node)
        scope = {"root": source, "release": release, "name": "FlipRing"}
        exec(compile(ast.Module(body=prefix, type_ignores=[]), "가상_필수파일목록", "exec"), scope)
        for path in scope["required"]:
            if path.is_relative_to(release / "검사도구"):
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")
        for name in self.TOOLS:
            (self.root / "검사도구" / name).write_bytes(("tool:" + name).encode("utf-8"))
        gcc = source / "licenses/OCR/ubuntu-gcc"
        (gcc / "gcc-source.tar.gz").write_bytes(b"gcc")
        (gcc / "notice.txt").write_bytes(b"notice")
        item = delivery.record(gcc / "gcc-source.tar.gz", "gcc-source.tar.gz")
        (gcc / "출하목록.json").write_text(json.dumps({"actual_origin": "Debian", "files": [
            {"path": item["path"], "size": item["bytes"], "sha256": item["sha256"]}], "include_metadata": ["notice.txt"]}), encoding="utf-8")
        seven = ["vendor/7zip/7z.exe", "vendor/7zip/7z.dll"] + ["licenses/7Zip/" + name for name in (
            "License.txt", "Source-License.txt", "LGPL-2.1.txt", "unRarLicense.txt", "sources/7z2605-src.tar.xz")]
        (source / "licenses/7Zip/출하목록.json").write_text(json.dumps({"version": "26.05", "files": [
            {"path": name, "size": (source / name).stat().st_size, "sha256": delivery.digest(source / name)} for name in seven]}), encoding="utf-8")
        h2o = source / "licenses/H2Orestart"
        (h2o / "원본출처.json").write_text(json.dumps({
            "binary": delivery.record(source / "vendor/h2orestart/H2Orestart.oxt", "binary"),
            "source": {**delivery.record(h2o / "H2Orestart-v0.8.0-source.tar.gz", "source"), "file": "H2Orestart-v0.8.0-source.tar.gz"}}), encoding="utf-8")
        (source / "licenses/Temurin17/출하목록.json").write_text(json.dumps({"files": [delivery.record(source / name, name) for name in (
            "vendor/java/bin/java.exe", "licenses/Temurin17/OpenJDK17U-jdk-sources_17.0.21_9.tar.gz")]}), encoding="utf-8")
        # 실행 결과는 모의 컴파일이 새로 만들며 빈 output의 존재 계약을 유지한다.
        shutil.rmtree(release)
        self.config["required"] += ["검사도구/" + name for name in self.TOOLS]
        self.prepared["source_tree"] = delivery.snapshot(self.root)
        return source, release

    def test_main_to_package_accepts_zip_tools_without_staging_copies(self):
        import build
        import package
        source, release = self.package_fixture()
        work = self.base / "work"
        compiler = self.base / "ISCC.exe"
        def prepare(*args):
            release.mkdir()
            work.mkdir()
            return self.prepared
        def compile_runtime(source, prepared, manifest, output, work, compiler):
            program = output / "프로그램/FlipRing"
            program.mkdir(parents=True)
            (program / "FlipRing.exe").write_bytes(b"fixture")
            internal = program / "_internal"
            for directory in ("assets", "vendor"):
                shutil.copytree(source / directory, internal / directory)
            for name in ("document_bridge.py", "document_formats.py", "document_xlsb.py"):
                shutil.copy2(source / name, internal / name)
            delivery.stage_legal(source, program, manifest, self.config)
            (output / "설치파일").mkdir()
            (output / "설치파일/FlipRing-Setup.exe").write_bytes(b"fixture")
        called = []
        def package_command(argv, **kwargs):
            called.append(argv)
            self.assertEqual(argv[4], str(source / "package.py"))
            self.assertEqual(kwargs["cwd"], source)
            self.assertFalse((release / "검사도구").exists())
            with patch.object(package, "__file__", str(source / "package.py")), patch.object(sys, "argv", argv[4:]):
                package.main()
        argv = ["배포빌드.py", "--output-root", str(release), "--work-root", str(work), "--iscc", str(compiler)]
        with patch.object(delivery, "__file__", str(source / "배포빌드.py")), patch.object(sys, "argv", argv), \
                patch.object(build, "prepare", side_effect=prepare), patch.object(build, "compile_prepared", side_effect=compile_runtime), \
                patch.object(delivery.subprocess, "run", side_effect=package_command):
            delivery.main()
        self.assertEqual(len(called), 1)
        self.assertTrue((release / "SHA256SUMS.txt").is_file())
        with zipfile.ZipFile(self.target) as archive:
            for name in self.TOOLS:
                self.assertEqual(archive.read("검사도구/" + name), ("tool:" + name).encode("utf-8"))

    def test_missing_tool_entry_is_rejected_against_original(self):
        import package
        source, release = self.package_fixture()
        manifest = delivery.freeze_source(self.root, self.prepared, self.target)
        manifest["entries"] = [entry for entry in manifest["entries"] if entry["path"] != "검사도구/regression19.py"]
        with self.assertRaises(delivery.DeliveryError):
            package.verify_verification_tools(source, self.target, manifest)

    def test_same_length_tool_entry_tamper_is_rejected_against_original(self):
        import package
        source, release = self.package_fixture()
        manifest = delivery.freeze_source(self.root, self.prepared, self.target)
        replacement = self.base / "tampered.zip"
        with zipfile.ZipFile(self.target) as original, zipfile.ZipFile(replacement, "w") as changed:
            for info in original.infolist():
                content = original.read(info.filename)
                changed.writestr(info.filename, b"X" * len(content) if info.filename == "검사도구/regression19.py" else content)
        with self.assertRaises(delivery.DeliveryError):
            package.verify_verification_tools(source, replacement, manifest)

    def test_actual_zip_tool_entry_missing_is_rejected_against_original(self):
        import package
        source, release = self.package_fixture()
        manifest = delivery.freeze_source(self.root, self.prepared, self.target)
        replacement = self.base / "missing-tool.zip"
        with zipfile.ZipFile(self.target) as original, zipfile.ZipFile(replacement, "w") as changed:
            for info in original.infolist():
                if info.filename != "검사도구/regression19.py":
                    changed.writestr(info.filename, original.read(info.filename))
        with self.assertRaises(delivery.DeliveryError):
            package.verify_verification_tools(source, replacement, manifest)


class InnoCompilerProbeTests(unittest.TestCase):
    """컴파일러 실행을 모의하여 실제 엔진 판독과 실패 거부 경계를 검사한다."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        tools = self.base / "tools"
        tools.mkdir()
        self.compiler = tools / "ISCC.exe"
        self.engine = tools / "ISCmplr.dll"
        # 아래 파일은 해시 검사용 표본이며 실제 실행하지 않는다.
        self.compiler.write_bytes(b"unit-executable-never-run")
        self.engine.write_bytes(b"unit-engine-never-loaded")
        text = "Compiler engine version: Inno Setup 6.7.3\r\nSuccessful compile.\r\n"
        self.result = {"status": "passed", "exit_code": 0, "output": text, "output_complete": True,
                       "output_bytes_complete": True, "output_truncated": False, "output_invalid_utf8": False,
                       "output_bytes": len(text.encode("utf-8")), "captured_bytes": len(text.encode("utf-8"))}

    def test_exact_engine_and_both_hashes_without_pe_version_assumption(self):
        import build
        probe = self.base / "probe"
        def compiler_call(check):
            self.assertEqual(check["argv"], [str(self.compiler), "/O-", str(probe / "진단.iss")])
            self.assertEqual(check["cwd"], str(probe))
            text = (probe / "진단.iss").read_text(encoding="utf-8-sig")
            self.assertIn("Output=no\nOutputDir=\nOutputManifestFile=\n", text)
            return self.result.copy()
        with patch.object(build, "capture_compiler_probe", side_effect=compiler_call):
            result = build.probe_compiler(self.compiler, probe)
        self.assertEqual(result["compiler_version"], "6.7.3")
        self.assertEqual(result["compiler_sha256"], delivery.digest(self.compiler))
        self.assertEqual(result["compiler_engine_sha256"], delivery.digest(self.engine))
        self.assertEqual(set(result), {"compiler_version", "compiler_sha256", "compiler_bytes", "compiler_engine_sha256", "compiler_engine_bytes"})
        self.assertFalse(any(path.suffix.lower() == ".exe" for path in probe.rglob("*")))

    def test_failed_incomplete_ambiguous_or_non6_engine_is_rejected(self):
        import build
        outputs = ["Compiler engine version: Inno Setup 7.0.0\r\n", "help only\r\n",
                   self.result["output"] + "Compiler engine version: Inno Setup 6.7.2\r\n",
                   self.result["output"] + "Error: simulated failure\r\n"]
        changes = [{"output": text, "output_bytes": len(text.encode()), "captured_bytes": len(text.encode())} for text in outputs]
        changes += [{"status": "failed", "exit_code": 1}, {"status": "timeout", "exit_code": None},
                    {"output_complete": False}, {"output_bytes_complete": False}, {"output_truncated": True},
                    {"output_invalid_utf8": True}, {"captured_bytes": 1}, {"capture_error": "EOF error"},
                    {"cleanup_errors": ["Job cleanup error"]}]
        for index, change in enumerate(changes):
            with self.subTest(change=change), patch.object(build, "capture_compiler_probe", return_value={**self.result, **change}):
                with self.assertRaises(delivery.DeliveryError):
                    build.probe_compiler(self.compiler, self.base / ("probe" + str(index)))

    def test_probe_output_artifact_and_tool_mutation_are_rejected(self):
        import build
        def installer_created(check):
            (Path(check["cwd"]) / "unexpected.exe").write_bytes(b"unexpected")
            return self.result.copy()
        with patch.object(build, "capture_compiler_probe", side_effect=installer_created), self.assertRaises(delivery.DeliveryError):
            build.probe_compiler(self.compiler, self.base / "artifact-probe")
        def engine_changed(check):
            self.engine.write_bytes(b"changed-engine")
            return self.result.copy()
        with patch.object(build, "capture_compiler_probe", side_effect=engine_changed), self.assertRaises(delivery.DeliveryError):
            build.probe_compiler(self.compiler, self.base / "changed-probe")

    def test_probe_reuse_source_path_and_missing_engine_are_rejected(self):
        import build
        existing = self.base / "already-exists"
        existing.mkdir()
        with patch.object(build, "capture_compiler_probe") as call:
            for target in (existing, build.ROOT / "진단금지"):
                with self.subTest(target=target), self.assertRaises(delivery.DeliveryError):
                    build.probe_compiler(self.compiler, target)
            self.engine.unlink()
            with self.assertRaises(delivery.DeliveryError):
                build.probe_compiler(self.compiler, self.base / "missing-engine")
        call.assert_not_called()


class OwnedBuildCaptureTests(unittest.TestCase):
    """소유 빌드의 UTF-8 실행과 수집 실패 거부를 작은 입력으로 검증한다."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "입력/소스"
        self.source.mkdir(parents=True)
        self.tools = self.source.parent / "검사도구"
        self.tools.mkdir()
        self.work = self.base / "작업"
        self.work.mkdir()
        text = "한글 표준출력\n한글 오류출력\n"
        self.result = {"status": "passed", "exit_code": 0, "output": text,
                       "output_complete": True, "output_bytes_complete": True,
                       "output_truncated": False, "output_display_truncated": False,
                       "output_invalid_utf8": False, "capture_boundary_omitted_bytes": 0,
                       "output_bytes": len(text.encode("utf-8")), "captured_bytes": len(text.encode("utf-8"))}

    def fake_capture(self, result):
        (self.tools / "release_capture.py").write_text(
            "def run_check(check):\n    return " + repr(result) + "\n", encoding="utf-8")

    def assert_rejected(self, result, identity):
        import build
        import os
        self.fake_capture(result)
        before = os.environ.copy()
        with self.assertRaises(delivery.DeliveryError):
            build.run_owned(self.source, [sys.executable], {"PYTHONUTF8": "1"}, self.work, identity, 600)
        self.assertEqual(delivery.load(self.work / (identity + ".json")), result)
        self.assertEqual(os.environ.copy(), before)

    def test_utf8_compiler_argv_and_owned_environment(self):
        import build
        (self.source / "LICENSE.txt").write_text("고지", encoding="utf-8")
        (self.source / "사용안내.txt").write_text("안내", encoding="utf-8")
        output = self.base / "출력"
        output.mkdir()
        called = []
        def owned(source, argv, env, work, identity, timeout):
            called.append((argv, env.copy(), identity, timeout))
            if identity == "pyinstaller":
                (output / "프로그램/FlipRing").mkdir(parents=True)
        prepared = {"environment": {"stable": 1}, "source_tree": [], "config": {}}
        with patch.object(delivery, "verify_source_manifest"), patch.object(build, "environment", return_value={"stable": 1}), \
                patch.object(delivery, "assert_tree"), patch.object(delivery, "stage_legal"), \
                patch.object(delivery, "runtime_notice", return_value="소스 고지"), patch.object(build, "run_owned", side_effect=owned):
            build.compile_prepared(self.source, prepared, {}, output, self.work, self.base / "ISCC.exe")
        self.assertEqual(called[0][0][:6], [sys.executable, "-B", "-X", "utf8", "-m", "PyInstaller"])
        self.assertEqual([item[2:] for item in called], [("pyinstaller", 600), ("inno", 600)])
        self.assertTrue(all(item[1]["PYTHONUTF8"] == "1" for item in called))

    def test_invalid_utf8_even_exit_zero_is_rejected(self):
        self.assert_rejected({**self.result, "output_invalid_utf8": True}, "invalid-utf8")

    def test_truncated_or_incomplete_even_exit_zero_is_rejected(self):
        changes = [{"output_complete": False}, {"output_bytes_complete": False},
                   {"output_truncated": True}, {"output_display_truncated": True},
                   {"capture_boundary_omitted_bytes": 1}]
        for index, change in enumerate(changes):
            with self.subTest(change=change):
                self.assert_rejected({**self.result, **change}, "incomplete-" + str(index))

    def test_capture_and_cleanup_even_exit_zero_are_rejected(self):
        for index, change in enumerate(({"capture_error": "EOF error"}, {"cleanup_errors": ["Job cleanup error"]}, {"error": "unexpected capture failure"})):
            with self.subTest(change=change):
                self.assert_rejected({**self.result, **change}, "capture-" + str(index))

    def test_bad_or_missing_byte_metadata_is_rejected(self):
        changes = [{"output_bytes": 1}, {"captured_bytes": 1}, {"output_bytes": True, "captured_bytes": True},
                   {"output_bytes": -1, "captured_bytes": -1}, {"output_bytes": None},
                   {"output_complete": None}, {"output_invalid_utf8": None}, {"output_truncated": None}]
        for index, change in enumerate(changes):
            with self.subTest(change=change):
                self.assert_rejected({**self.result, **change}, "bytes-" + str(index))

    def test_normal_capture_and_shared_environment_are_preserved(self):
        import build
        import os
        self.fake_capture(self.result)
        before = os.environ.copy()
        build.run_owned(self.source, [sys.executable], {"PYTHONUTF8": "1"}, self.work, "normal", 600)
        self.assertEqual(delivery.load(self.work / "normal.json"), self.result)
        self.assertEqual(os.environ.copy(), before)

    def test_actual_owned_python_korean_stdout_and_stderr(self):
        import build
        import os
        original = Path(__file__).resolve().parents[1] / "검사도구/release_capture.py"
        shutil.copy2(original, self.tools / "release_capture.py")
        code = "import sys; print('한글 표준출력', flush=True); print('한글 오류출력', file=sys.stderr, flush=True)"
        before = os.environ.copy()
        build.run_owned(self.source, [sys.executable, "-B", "-X", "utf8", "-c", code],
                        {"PYTHONUTF8": "1"}, self.work, "actual-korean", 15)
        result = delivery.load(self.work / "actual-korean.json")
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(result["output_complete"])
        self.assertTrue(result["output_bytes_complete"])
        self.assertFalse(result["output_invalid_utf8"])
        self.assertFalse(result["output_truncated"])
        self.assertIn("한글 표준출력", result["output"])
        self.assertIn("한글 오류출력", result["output"])
        self.assertEqual(len(result["output"].encode("utf-8")), result["output_bytes"])
        self.assertEqual(result["output_bytes"], result["captured_bytes"])
        self.assertEqual(os.environ.copy(), before)


class InnoCaptureBudgetTests(unittest.TestCase):
    """독립 Inno 수집기만 상한을 늘리고 경계·오류 거부를 유지한다."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "입력/소스"
        self.source.mkdir(parents=True)
        self.tools = self.source.parent / "검사도구"
        self.tools.mkdir()
        self.work = self.base / "작업"
        self.work.mkdir()

    def fake_capture(self, invalid=False):
        text = ("MAX_CAPTURE_BYTES = 65536\nMAX_DOCUMENT_BYTES = 12345\n"
                "def run_check(check):\n"
                "    import json\n"
                "    text = json.dumps(dict(cap=MAX_CAPTURE_BYTES, document=MAX_DOCUMENT_BYTES))\n"
                "    return dict(status='passed', exit_code=0, output=text, output_complete=True, "
                "output_bytes_complete=True, output_truncated=False, output_invalid_utf8=" + repr(invalid) + ", "
                "output_display_truncated=False, capture_boundary_omitted_bytes=0, "
                "output_bytes=len(text.encode('utf-8')), captured_bytes=len(text.encode('utf-8')))\n")
        (self.tools / "release_capture.py").write_text(text, encoding="utf-8")

    def actual_capture(self, code, identity="inno", reject=False):
        import build
        shutil.copy2(Path(__file__).resolve().parents[1] / "검사도구/release_capture.py", self.tools / "release_capture.py")
        argv = [sys.executable, "-B", "-X", "utf8", "-c", code]
        if reject:
            with self.assertRaises(delivery.DeliveryError):
                build.run_owned(self.source, argv, {"PYTHONUTF8": "1"}, self.work, identity, 15)
        else:
            build.run_owned(self.source, argv, {"PYTHONUTF8": "1"}, self.work, identity, 15)
        return delivery.load(self.work / (identity + ".json"))

    def test_inno_budget_others_default_fresh_modules_and_exception_isolation(self):
        import build
        self.fake_capture()
        created = []
        factory = build.importlib.util.module_from_spec
        def fresh(spec):
            module = factory(spec)
            created.append(module)
            return module
        with patch.object(build.importlib.util, "module_from_spec", side_effect=fresh):
            for identity, expected in (("inno", 256 * 1024), ("pyinstaller", 65536), ("compiler-probe", 65536)):
                build.run_owned(self.source, [sys.executable], {}, self.work, identity, 600)
                result = json.loads(delivery.load(self.work / (identity + ".json"))["output"])
                self.assertEqual(result, {"cap": expected, "document": 12345})
            self.fake_capture(invalid=True)
            rejected_work = self.base / "실패작업"
            rejected_work.mkdir()
            with self.assertRaises(delivery.DeliveryError):
                build.run_owned(self.source, [sys.executable], {}, rejected_work, "inno", 600)
            self.assertTrue(delivery.load(rejected_work / "inno.json")["output_invalid_utf8"])
            self.fake_capture()
            build.run_owned(self.source, [sys.executable], {}, self.work, "after-exception", 600)
            self.assertEqual(json.loads(delivery.load(self.work / "after-exception.json")["output"])["cap"], 65536)
        self.assertEqual(len(created), 5)
        self.assertEqual(len({id(module) for module in created}), 5)
        self.assertEqual([module.MAX_CAPTURE_BYTES for module in created], [262144, 65536, 65536, 262144, 65536])
        self.assertTrue(all(module.MAX_DOCUMENT_BYTES == 12345 for module in created))

    def test_actual_korean_163228_bytes_are_completely_retained(self):
        result = self.actual_capture("import sys; sys.stdout.buffer.write(('한글출력\\n' * 12556).encode('utf-8'))")
        self.assertEqual(result["output_bytes"], 163228)
        self.assertEqual(result["captured_bytes"], 163228)
        self.assertEqual(len(result["output"].encode("utf-8")), 163228)
        self.assertTrue(result["output_complete"] and result["output_bytes_complete"])
        self.assertFalse(result["output_truncated"] or result["output_invalid_utf8"])

    def test_actual_exact_256k_boundary_passes(self):
        result = self.actual_capture("import sys; sys.stdout.buffer.write('한글'.encode('utf-8') + b'A' * (256 * 1024 - 6))")
        self.assertEqual(result["output_bytes"], 256 * 1024)
        self.assertEqual(result["captured_bytes"], 256 * 1024)
        self.assertFalse(result["output_truncated"])

    def test_actual_over_256k_remains_rejected_and_original_json_saved(self):
        result = self.actual_capture("import sys; sys.stdout.buffer.write('한글'.encode('utf-8') + b'A' * (256 * 1024 + 1 - 6))", reject=True)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["output_bytes"], 256 * 1024 + 1)
        self.assertEqual(result["captured_bytes"], 256 * 1024)
        self.assertTrue(result["output_truncated"])

    def test_invalid_utf8_after_64k_remains_rejected(self):
        result = self.actual_capture("import sys; sys.stdout.buffer.write(b'A' * 70000 + bytes([255]))", reject=True)
        self.assertEqual(result["output_bytes"], 70001)
        self.assertEqual(result["captured_bytes"], 70001)
        self.assertFalse(result["output_truncated"])
        self.assertTrue(result["output_invalid_utf8"])

    def test_non_inno_actual_capture_stays_64k(self):
        result = self.actual_capture("import sys; sys.stdout.buffer.write(b'A' * 70000)", identity="pyinstaller", reject=True)
        self.assertEqual(result["output_bytes"], 70000)
        self.assertEqual(result["captured_bytes"], 65536)
        self.assertTrue(result["output_truncated"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
