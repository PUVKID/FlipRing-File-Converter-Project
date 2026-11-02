"""확인된 공식 URL의 원본 자료를 수집하며 실패 시 즉시 기록하고 종료한다."""
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

root = Path(__file__).resolve().parent
url, filename = sys.argv[1:3]
destination = root / filename
# 공개·출하 사본에는 자료 검증 결과만 기록하고 사적 운영 식별자는 포함하지 않습니다.
report = {'korean_time': datetime.now(timezone(timedelta(hours=9))).isoformat(), 'url': url, 'destination': str(destination)}
try:
    if destination.exists():
        raise FileExistsError(str(destination))
    request = urllib.request.Request(url, headers={"User-Agent": "FlipRing-license-audit/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        content = response.read()
        report["final_url"] = response.url
        report["content_type"] = response.headers.get("Content-Type")
    if len(sys.argv) > 3:
        assert hashlib.sha256(content).hexdigest() == sys.argv[3], "공식 SHA256과 다릅니다"
    destination.write_bytes(content)
    report.update({"status": "success", "size": len(content),
                   "sha256": hashlib.sha256(content).hexdigest(), "changed": True, "exit_code": 0})
except Exception as exc:
    report.update({"status": "failed", "error": repr(exc), "changed": destination.exists(), "exit_code": 1})
log = root / (filename.replace("/", "_") + ".origin.json")
log.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False))
sys.exit(report["exit_code"])
