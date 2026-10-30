from pathlib import Path
import hashlib
import json
import os

# 설치된 모든 고객용 파일을 동결한 배포 해시와 대조한다.
root = Path(__file__).resolve().parent.parent
installed = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "FlipRing"
prefix = "프로그램/FlipRing/"
checked = []
errors = []
for line in (root / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
    digest, relative = line.split("  ", 1)
    if not relative.startswith(prefix):
        continue
    target = installed / relative[len(prefix):]
    actual = hashlib.file_digest(target.open("rb"), "sha256").hexdigest() if target.is_file() else None
    checked.append(relative)
    if actual != digest:
        errors.append({"path": relative, "expected": digest, "actual": actual})
report = {"installed": str(installed), "checked_files": len(checked), "errors": errors}
(root / "evidence" / "새디자인-설치파일대조.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False))
raise SystemExit(0 if checked and not errors else 1)
