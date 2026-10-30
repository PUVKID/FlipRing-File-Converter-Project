"""공식 DEB의 두 DLL과 원본 DLL을 비교하고 패키징 원문을 읽는다."""
from datetime import datetime, timezone, timedelta
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import sys

root = Path(__file__).resolve().parent
seven = Path(sys.argv[1]).resolve()
vendor = Path(sys.argv[2]).resolve()
deb = root / (sys.argv[3] if len(sys.argv) > 3 else "gcc-mingw-w64-x86-64-win32-runtime_13.2.0-6ubuntu1+26.1_amd64.deb")
prefix = sys.argv[4] if len(sys.argv) > 4 else "ubuntu13"
report = {"korean_time": datetime.now(timezone(timedelta(hours=9))).isoformat(),
          "session": "01a15519-c86d-7880-a2e6-c9070f59067d", "task": "mono-bilingual-20261021",
          "worker": "/root/deep_mono_ui", "cwd": str(Path.cwd()), "argv": sys.argv, "repair_used": 1}
try:
    raw = deb.read_bytes()
    assert raw[:8] == b"!<arch>\n"
    offset = 8
    while offset < len(raw):
        header = raw[offset:offset + 60]
        name = header[:16].decode("ascii").strip().rstrip("/")
        size = int(header[48:58])
        content = raw[offset + 60:offset + 60 + size]
        offset += 60 + size + size % 2
        if name.startswith("data.tar."):
            compressed = root / (prefix + "-" + name)
            compressed.write_bytes(content)
            break
    else:
        raise ValueError("DEB에 data.tar 압축 자료가 없습니다")
    command = [str(seven), "x", "-so", str(compressed)]
    report["extract_command"] = command
    unpacked = subprocess.run(command, capture_output=True, check=False)
    report["extract_exit_code"] = unpacked.returncode
    if unpacked.returncode:
        raise RuntimeError(unpacked.stderr.decode("utf-8", "replace"))
    comparison = []
    with tarfile.open(fileobj=io.BytesIO(unpacked.stdout), mode="r:") as archive:
        for member in archive:
            basename = Path(member.name).name
            if basename in {"libgcc_s_seh-1.dll", "libstdc++-6.dll"} and member.isfile():
                data = archive.extractfile(member).read()
                packaged = hashlib.sha256(data).hexdigest()
                original = hashlib.sha256((vendor / basename).read_bytes()).hexdigest()
                comparison.append({"name": basename, "member": member.name, "size": len(data),
                                   "packaged_sha256": packaged, "vendor_sha256": original,
                                   "matches": packaged == original})
        report["runtime_members"] = [m.name for m in archive.getmembers()]
    report["comparison"] = comparison
    report["both_match"] = len(comparison) == 2 and all(x["matches"] for x in comparison)
    report.update({"status": "success", "exit_code": 0, "vendor_modified": False})
except Exception as exc:
    report.update({"status": "failed", "error": repr(exc), "exit_code": 1})
(root / (prefix + "-runtime-comparison.json")).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({key: value for key, value in report.items() if key != "runtime_members"}, ensure_ascii=False))
sys.exit(report["exit_code"])
