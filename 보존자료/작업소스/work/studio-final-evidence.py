"""새 설치본의 실제 실행 확인 뒤 배포 해시 근거를 갱신한다."""
from pathlib import Path
from datetime import datetime
import argparse
import hashlib
import json
import os

parser = argparse.ArgumentParser()
parser.add_argument("--installer-exit-code", type=int, required=True)
parser.add_argument("--native-window-id", type=int, required=True)
parser.add_argument("--installed-pid", type=int, required=True)
args = parser.parse_args()
assert args.installer_exit_code == 0
root = Path(__file__).resolve().parents[1]
installed = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "FlipRing"
prefix = "프로그램/FlipRing/"
entries = []
installed_checked = 0
for line in (root / "SHA256SUMS.txt").read_text(encoding="utf-8").split("\n"):
    if not line:
        continue
    expected, relative = line.split("  ", 1)
    actual = hashlib.file_digest((root / relative).open("rb"), "sha256").hexdigest()
    assert actual == expected, relative
    entries.append({"path": relative, "sha256": actual})
    if relative.startswith(prefix):
        local = installed / relative[len(prefix):]
        assert hashlib.file_digest(local.open("rb"), "sha256").hexdigest() == expected, str(local)
        installed_checked += 1
assert installed_checked > 0
destination = root / "evidence" / "배포검증.json"
previous = destination.with_name("이전-1.4-배포검증.json")
if destination.exists() and not previous.exists():
    previous.write_bytes(destination.read_bytes())
report = {
    "time_kst": datetime.now().astimezone().isoformat(),
    "session": "01a15519-c86d-7880-a2e6-c9070f59067d",
    "task": "studio-redesign-20261021",
    "release": "1.5.0",
    "installer_exit_code": args.installer_exit_code,
    "actual_launch_passed": True,
    "actual_window": {"window_id": args.native_window_id, "installed_pid": args.installed_pid,
                      "evidence": "부모의 실제 설치본 Sky 창 관찰 뒤 이 도구에 전달한 값"},
    "installed_exe_sha256": hashlib.file_digest((installed / "FlipRing.exe").open("rb"), "sha256").hexdigest(),
    "installed_files_checked": installed_checked,
    "physical_shift_status": "이 릴리스의 사용자 실제 Shift 확인은 별도 기록과 구분한다.",
    "files": entries,
}
destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"files": len(entries), "installed_checked": installed_checked,
                  "exe_sha256": report["installed_exe_sha256"]}, ensure_ascii=False))
