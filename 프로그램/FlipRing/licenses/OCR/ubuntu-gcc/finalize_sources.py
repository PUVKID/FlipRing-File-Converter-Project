"""확정된 상응 소스와 고지의 출하 목록을 검증해 기록한다."""
from datetime import datetime, timezone, timedelta
import ast
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile

root = Path(__file__).resolve().parent
vendor = Path(sys.argv[1]).resolve()
evidence = Path(sys.argv[2]).resolve()
report = {"korean_time": datetime.now(timezone(timedelta(hours=9))).isoformat(),
          "session": "01a15519-c86d-7880-a2e6-c9070f59067d", "task": "mono-bilingual-20261021",
          "worker": "/root/deep_mono_ui", "cwd": str(Path.cwd()), "argv": sys.argv,
          "role": "deep", "model_request": "gpt-6.1-sol", "effort_request": "xhigh",
          "server_runtime_model": "미확인", "repair_used": 1}
try:
    sources = []
    for name in ("gcc-mingw-w64_27.dsc", "gcc-14_14.2.0-19.dsc"):
        text = (root / name).read_text(encoding="utf-8")
        section = text.split("Checksums-Sha256:\n", 1)[1].split("\nFiles:", 1)[0]
        for line in section.strip().split("\n"):
            digest, size, filename = line.split()
            content = (root / filename).read_bytes()
            assert len(content) == int(size), filename
            assert hashlib.sha256(content).hexdigest() == digest, filename
            sources.append({"path": filename, "size": len(content), "sha256": digest})
    expected = {"libgcc_s_seh-1.dll": "172cfdc9d83703ec0a0ca2cee08f6cf2a166b801717ee51a56b3a63b36bc2f83",
                "libstdc++-6.dll": "5fe5d4d8f6636eb6f2dc55be99dc5dc8a6c40db1abdf592e84480d1e6985abd0"}
    assert all(hashlib.sha256((vendor / name).read_bytes()).hexdigest() == digest for name, digest in expected.items())
    matched = json.loads((root / "debian14-runtime-comparison.json").read_text(encoding="utf-8"))
    assert matched["both_match"] and matched["extract_exit_code"] == 0
    deb_name = "gcc-mingw-w64-x86-64-posix-runtime_14.2.0-19+27+b1_amd64.deb"
    raw = (root / deb_name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "c898d96177574a8a7238564a1e799d8ddfed5a3d2ea005510305f9ad466a6f59"
    offset = 8
    while offset < len(raw):
        header = raw[offset:offset + 60]
        name = header[:16].decode("ascii").strip().rstrip("/")
        size = int(header[48:58])
        content = raw[offset + 60:offset + 60 + size]
        offset += 60 + size + size % 2
        if name.startswith("control.tar."):
            with tarfile.open(fileobj=io.BytesIO(content)) as archive:
                member = next(m for m in archive if m.isfile() and m.name.endswith("/control"))
                control = archive.extractfile(member).read()
            break
    else:
        raise ValueError("패키지 control이 없습니다")
    assert b"Built-Using: gcc-14 (= 14.2.0-19)" in control
    (root / "debian14-runtime-control.txt").write_bytes(control)
    names = ["README.md", "COPYING.txt", "COPYING3.txt", "COPYING.RUNTIME.txt",
             "gcc-mingw-w64_27.dsc", "gcc-mingw-w64_27.tar.xz",
             "gcc-14_14.2.0-19.dsc", "gcc-14_14.2.0.orig.tar.gz", "gcc-14_14.2.0-19.debian.tar.xz",
             "debian14-runtime-comparison.json", "debian14-runtime-control.txt",
             "download_one.py", "inspect_runtime.py", "finalize_sources.py"]
    names += ["debian27/" + name for name in ("rules", "copyright", "control", "changelog")]
    names += ["debian-gcc14/" + name for name in ("rules", "copyright", "README.source", "changelog")]
    names += [name + ".origin.json" for name in ("gcc-mingw-w64_27.dsc", "gcc-mingw-w64_27.tar.xz",
              "gcc-14_14.2.0-19.dsc", "gcc-14_14.2.0.orig.tar.gz", "gcc-14_14.2.0-19.debian.tar.xz", deb_name)]
    entries = []
    for name in names:
        content = (root / name).read_bytes()
        if not name.endswith((".tar.gz", ".tar.xz")):
            decoded = content.decode("utf-8", "strict")
            assert "\ufffd" not in decoded, name
            if name.endswith(".py"):
                ast.parse(decoded)
        entries.append({"path": name, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()})
    manifest = {"actual_origin": "Debian", "package": "gcc-mingw-w64-x86-64-posix-runtime",
                "version": "14.2.0-19+27+b1", "built_using": "gcc-14 (= 14.2.0-19)",
                "files": entries, "include_metadata": ["출하목록.json", "SHA256SUMS.txt"],
                "exclude": ["*.deb", "*-data.tar.*", "Ubuntu13 후보 자료", "실패 출처 기록"],
                "vendor_modified": False, "compiler_rebuild_tested": False, "pgp_signature_verified": False}
    (root / "출하목록.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "SHA256SUMS.txt").write_text("".join(f"{x['sha256']}  {x['path']}\n" for x in entries), encoding="utf-8")
    report.update({"status": "source_frozen", "exit_code": 0, "source_references_verified": len(sources),
                   "ship_file_count": len(entries) + 2, "ship_bytes": sum(x["size"] for x in entries),
                   "both_dlls_match_official_deb": True, "vendor_unchanged": True,
                   "source_archives": sources, "manifest": str(root / "출하목록.json"),
                   "limits": ["GCC 재컴파일은 미실행", "PGP 서명자 검증 미실행", "독립 검증은 부모 담당"]})
except Exception as exc:
    report.update({"status": "failed", "error": repr(exc), "exit_code": 1})
evidence.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False))
sys.exit(report["exit_code"])
