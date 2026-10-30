"""검증한 새 실행본 뒤에만 이전 설치본을 표준 제거하고 D에서 설치를 시험한다."""
from datetime import datetime
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "work/native-release-1.6"
SETUP = ROOT / "설치파일/FlipRing-Setup.exe"
OLD = Path(r"C:\Users\PUVKID\AppData\Local\Programs\FlipRing")
TARGET = OUT / "installed"
TEMP = OUT / "installer-temp"

def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def save(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def run(name, argv):
    started = time.monotonic()
    result = subprocess.run(argv, cwd=ROOT, env=environment, shell=False,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=240)
    record = {"at_kst": datetime.now().astimezone().isoformat(), "argv": argv,
              "cwd": str(ROOT), "exit_code": result.returncode,
              "seconds": round(time.monotonic() - started, 3),
              "stdout": result.stdout.decode("utf-8", errors="replace")[:4096],
              "stderr": result.stderr.decode("utf-8", errors="replace")[:4096]}
    save(name + ".json", record)
    print(json.dumps(record, ensure_ascii=False), flush=True)
    if result.returncode != 0:
        raise SystemExit(result.returncode)
    return record

assert ROOT == Path(r"D:\2026\FilpRing Project")
assert TARGET.resolve().is_relative_to(ROOT)
gate = json.loads((OUT / "portable-ui.json").read_text(encoding="utf-8"))
assert gate["actual_window_observed"] and gate["exe_sha256"] == digest(ROOT / "프로그램/FlipRing/FlipRing.exe")
assert SETUP.is_file() and not TARGET.exists()
TEMP.mkdir(exist_ok=True)
environment = os.environ.copy()
environment.update(TEMP=str(TEMP), TMP=str(TEMP))
if (OLD / "unins000.exe").is_file():
    assert OLD.resolve() == Path(r"C:\Users\PUVKID\AppData\Local\Programs\FlipRing")
    run("이전설치-표준제거", [str(OLD / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=" + str(OUT / "old-uninstall.log")])
run("새설치-실행", [str(SETUP), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/SP-", "/NORESTART", "/NOCLOSEAPPLICATIONS", "/NOICONS", "/TASKS=", "/LANG=korean", "/DIR=" + str(TARGET), "/LOG=" + str(OUT / "install.log")])
assert (TARGET / "FlipRing.exe").is_file()
files = list((ROOT / "프로그램/FlipRing").rglob("*"))
checked = 0
for source in files:
    if source.is_file():
        target = TARGET / source.relative_to(ROOT / "프로그램/FlipRing")
        assert target.is_file() and digest(source) == digest(target), str(target)
        checked += 1
save("설치파일-전수대조.json", {"at_kst": datetime.now().astimezone().isoformat(), "files_checked": checked,
     "all_equal": True, "install_dir": str(TARGET), "setup_sha256": digest(SETUP),
     "exe_sha256": digest(TARGET / "FlipRing.exe"), "actual_launch_passed": False})
print(json.dumps({"설치대조": checked, "실제창시험": "대기"}, ensure_ascii=False))
