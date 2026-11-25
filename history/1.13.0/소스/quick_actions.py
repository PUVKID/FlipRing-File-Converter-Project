"""빠른 작업: 안전한 폴더 입력, 레시피 연결, 결과 보존과 복원."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import threading
import uuid
import zipfile

import engine
import pdf_tools
import workspace_core as workspace

BUILTINS = [
    {"version": 1, "name": "사진 JPG", "format": "jpg", "quality": 85, "width": 0, "height": 0,
     "max_bytes": 0, "zip": False, "template": "{name}", "extensions": ""},
    {"version": 1, "name": "제출용 JPG + ZIP", "format": "jpg", "quality": 80, "width": 1600, "height": 0,
     "max_bytes": 1024 * 1024, "zip": True, "template": "{name}_{index:03d}", "extensions": ""},
    {"version": 1, "name": "문서 PDF", "format": "pdf", "quality": 85, "width": 0, "height": 0,
     "max_bytes": 0, "zip": False, "template": "{name}", "extensions": ""},
]
for _name, _format, _quality, _width, _limit in (
    ("메일용 JPG · 1600px / 1MiB", "jpg", 80, 1600, 1024 * 1024),
    ("인쇄용 PDF · 원본 크기", "pdf", 95, 0, 0),
    ("웹용 WebP · 1920px / 512KiB", "webp", 80, 1920, 512 * 1024),
):
    BUILTINS.append({**BUILTINS[0], "name": _name, "format": _format,
                     "quality": _quality, "width": _width, "max_bytes": _limit})
MAX_FILES = 10000


def safe_path(raw, *, exists=True):
    """해결 전에 모든 조상의 연결·재분석 지점을 거부한다."""
    path = Path(os.path.abspath(os.fspath(raw)))
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            if part == path and exists:
                raise ValueError("입력이 없거나 이동되었습니다: " + str(path))
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("연결 파일·폴더는 따라가지 않습니다: " + str(part))
    return path


def validate_action(raw):
    if not isinstance(raw, dict) or set(raw) != set(BUILTINS[0]):
        raise ValueError("빠른 작업 JSON 필드를 확인해 주세요.")
    value = copy.deepcopy(raw)
    if type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("지원하는 빠른 작업 버전은 1입니다.")
    recipe = {"version": 1, "name": value["name"], "steps": [
        {"op": "convert", "format": value["format"], "quality": value["quality"]},
        {"op": "rename", "template": value["template"]}]}
    normalized = workspace.validate_recipe(recipe)
    value["name"] = normalized["name"]
    value["format"] = normalized["steps"][0]["format"]
    for key in ("width", "height"):
        workspace._number(value[key], key, 0, 12000)
    workspace._number(value["max_bytes"], "max_bytes", 0, 1024 ** 5)
    if type(value["zip"]) is not bool:
        raise ValueError("ZIP 옵션을 확인해 주세요.")
    if not isinstance(value["extensions"], str) or len(value["extensions"]) > 512:
        raise ValueError("확장자 필터를 확인해 주세요.")
    for ext in value["extensions"].replace(";", ",").split(","):
        if ext.strip() and not ext.strip().lstrip(".").isalnum():
            raise ValueError("확장자는 쉼표로 구분해 주세요.")
    return value


class ActionStore:
    """경로를 포함하지 않는 빠른 작업만 원자 저장한다. 손상된 원본은 보존한다."""
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return []
        if self.path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("빠른 작업 파일은 2MiB 이하여야 합니다.")
        rows = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or len(rows) > 1000:
            raise ValueError("빠른 작업 목록을 확인해 주세요.")
        rows = [validate_action(row) for row in rows]
        if len({row["name"].casefold() for row in rows}) != len(rows):
            raise ValueError("같은 작업 이름이 있습니다.")
        return rows

    def write(self, rows):
        self.load()
        rows = [validate_action(row) for row in rows]
        if len(rows) > 1000 or len({r["name"].casefold() for r in rows}) != len(rows):
            raise ValueError("작업 수 또는 중복 이름을 확인해 주세요.")
        encoded = json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")
        if len(encoded) > 2 * 1024 * 1024:
            raise ValueError("빠른 작업 파일은 2MiB 이하여야 합니다.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
        try:
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def save(self, action, old_name=None):
        action = validate_action(action)
        rows = [r for r in self.load() if r["name"] != old_name]
        if any(r["name"].casefold() == action["name"].casefold() for r in rows):
            raise ValueError("이미 사용 중인 작업 이름입니다.")
        self.write([*rows, action])

    def delete(self, name):
        self.write([r for r in self.load() if r["name"] != name])


def collect_inputs(paths, extensions="", cancel=None):
    allowed = {x.strip().lower().lstrip(".") for x in extensions.replace(";", ",").split(",") if x.strip()}
    records, skipped, seen = [], [], set()

    def add(raw, relative):
        pdf_tools.check_cancel(cancel)
        try:
            path = safe_path(raw)
            info = path.stat()
            if path.name.startswith((".", "~")) or path.suffix.lower() in (".tmp", ".temp", ".part") or getattr(info, "st_file_attributes", 0) & 2:
                return
            if not path.is_file() or (allowed and path.suffix.lower().lstrip(".") not in allowed):
                return
            key = os.path.normcase(str(path))
            if key not in seen:
                seen.add(key)
                records.append({"source": str(path), "relative": str(relative)})
                if len(records) > MAX_FILES:
                    raise ValueError("한 번에 최대 10,000개 파일을 추가할 수 있습니다.")
        except (OSError, ValueError) as error:
            if len(records) > MAX_FILES:
                raise
            skipped.append(str(error))

    for raw in paths:
        pdf_tools.check_cancel(cancel)
        try:
            root = safe_path(raw)
            if root.is_dir():
                for directory, names, files in os.walk(root, followlinks=False):
                    pdf_tools.check_cancel(cancel)
                    retained = []
                    for name in sorted(names):
                        child = Path(directory) / name
                        try:
                            safe_path(child)
                            if not name.startswith((".", "~")) and not getattr(child.stat(), "st_file_attributes", 0) & 2:
                                retained.append(name)
                        except (OSError, ValueError) as error:
                            skipped.append(str(error))
                    names[:] = retained
                    for name in sorted(files):
                        path = Path(directory) / name
                        add(path, Path(root.name) / path.relative_to(root))
            else:
                add(root, Path(root.name))
        except (OSError, ValueError) as error:
            skipped.append(str(error))
    if len(records) > MAX_FILES:
        raise ValueError("한 번에 최대 10,000개 파일을 추가할 수 있습니다.")
    return {"inputs": records, "skipped": skipped}


def output_name(record, action, index):
    source = Path(record["source"])
    name = action["template"].format(name=engine.stem(source), index=index, date=workspace.date.today().isoformat())
    workspace._name(name)
    return name + "." + action["format"]


def _preview_count(record, action, cancel):
    """실제 엔진이 분리하는 결과 수만 확인하고 사용자 폴더에는 발행하지 않는다."""
    source = safe_path(record['source'])
    _, extension = engine.classify(source)
    if (action['width'] or action['height']) and extension not in workspace._IMAGE_FORMATS:
        raise ValueError('크기 조절 입력은 이미지만 지원합니다.')
    target = action['format']
    if target == extension or target not in ('jpg', 'png') or extension in workspace._IMAGE_FORMATS:
        return 1
    before = digest(source, cancel)
    if extension == 'pdf':
        import pypdfium2 as pdfium
        from pdf_lock import PDFIUM_LOCK
        while not PDFIUM_LOCK.acquire(timeout=.1):
            pdf_tools.check_cancel(cancel)
        try:
            with pdfium.PdfDocument(str(source)) as document:
                count = len(document)
        finally:
            PDFIUM_LOCK.release()
    else:
        # 문서 페이지 재배치는 실제 변환 없이 추정하지 않는다.
        with tempfile.TemporaryDirectory(prefix='.flipring-name-preview-') as work:
            count = len(workspace._single(source, {'op': 'convert', 'format': target,
                            'quality': action['quality']}, Path(work), cancel))
    if digest(source, cancel) != before:
        raise ValueError('미리보기 중 입력이 변경되었습니다.')
    if count < 1:
        raise ValueError('예정 결과가 없는 입력입니다.')
    return count


def preview_output_names(records, action, output, cancel=None):
    """디스크와 입력 묶음의 모든 실제 예정 이름에 발행 번호 규칙을 적용한다."""
    action = validate_action(action)
    directory = safe_path(output, exists=False)
    reserved, rows = set(), []
    for index, record in enumerate(records, 1):
        pdf_tools.check_cancel(cancel)
        relative = Path(record['relative'])
        if relative.anchor or relative.drive or '..' in relative.parts:
            raise ValueError('입력 상대 경로를 확인해 주세요.')
        for part in relative.parts:
            workspace._name(part)
        folder = safe_path(directory / relative.parent, exists=False)
        count = _preview_count(record, action, cancel)
        base_name = output_name(record, action, index)
        for part in range(1, count + 1):
            name = (Path(base_name).stem + f'-{part}' + Path(base_name).suffix) if count > 1 else base_name
            suffix = '.tar.gz' if name.lower().endswith('.tar.gz') else Path(name).suffix
            stem = name[:-len(suffix)] if suffix else name
            for number in range(1, 100000):
                pdf_tools.check_cancel(cancel)
                candidate = folder / (name if number == 1 else f'{stem} {number}{suffix}')
                key = os.path.normcase(str(candidate))
                if key not in reserved and not candidate.exists():
                    reserved.add(key)
                    rows.append({'source': record['source'], 'path': str(candidate)})
                    break
            else:
                raise ValueError('새 결과 파일 이름을 만들지 못했습니다.')
    if action['zip']:
        name = '제출용.zip'
        for number in range(1, 100000):
            candidate = directory / (name if number == 1 else f'제출용 {number}.zip')
            if os.path.normcase(str(candidate)) not in reserved and not candidate.exists():
                rows.append({'source': '', 'path': str(candidate)})
                break
        else:
            raise ValueError('묶음 결과 이름을 만들지 못했습니다.')
    return rows


def _tracked_publish(item, folder, name, source, input_hash, emit, cancel, expected_count=1):
    """발행 예정 해시를 먼저 기록하고 배타 생성하여 중단 경계를 복구한다."""
    expected_hash = digest(item, cancel)
    suffix = ".tar.gz" if name.lower().endswith(".tar.gz") else Path(name).suffix
    stem = name[:-len(suffix)] if suffix else name
    for number in range(1, 100000):
        pdf_tools.check_cancel(cancel)
        path = folder / (name if number == 1 else f"{stem} {number}{suffix}")
        if path.exists():
            continue
        owned = {"path": str(path), "source": str(source), "sha256": expected_hash,
                 "size": Path(item).stat().st_size, "constraints_met": True}
        # 이 신호의 수신자는 파일 생성 전에 영속 저장을 마친다.
        emit({"state": "publishing", "source": str(source), "input_sha256": input_hash,
              "owned": owned, "expected": expected_count})
        try:
            stream = path.open("xb")
        except FileExistsError:
            emit({"state": "publication_conflict", "source": str(source), "owned": owned, "expected": expected_count})
            continue
        try:
            with stream, Path(item).open("rb") as origin:
                while block := origin.read(1024 * 1024):
                    pdf_tools.check_cancel(cancel)
                    stream.write(block)
                stream.flush()
                os.fsync(stream.fileno())
            if digest(path) != expected_hash:
                raise ValueError("결과 발행 중 변경을 발견했습니다.")
            return str(path)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
    raise ValueError("새 결과 파일 이름을 만들지 못했습니다.")


def preflight(records, action, output, cancel=None):
    action = validate_action(action)
    directory = safe_path(output, exists=False)
    directory.mkdir(parents=True, exist_ok=True)
    safe_path(directory)
    reports = []
    for index, record in enumerate(records, 1):
        pdf_tools.check_cancel(cancel)
        report = {"source": record["source"], "ok": False, "error": "", "estimated": 0}
        try:
            source = safe_path(record["source"])
            if not source.is_file():
                raise ValueError("일반 파일이 아닙니다.")
            _, extension = engine.classify(source)
            if extension != action["format"] and action["format"] not in engine.targets([source]):
                raise ValueError("지원하지 않는 출력 형식입니다.")
            missing = engine.requirement(source, action["format"])
            if missing:
                raise ValueError(str(missing) + " 도구가 필요합니다.")
            if (action["width"] or action["height"]) and extension not in workspace._IMAGE_FORMATS:
                raise ValueError("크기 조절 입력은 이미지만 지원합니다.")
            if action["max_bytes"] and action["format"] not in workspace._IMAGE_FORMATS | {"pdf"}:
                raise ValueError("목표 용량은 이미지·PDF 출력에서 지원합니다.")
            output_name(record, action, index)
            relative = Path(record["relative"])
            if relative.anchor or relative.drive or ".." in relative.parts or not relative.name:
                raise ValueError("입력 상대 경로를 확인해 주세요.")
            for part in relative.parts:
                workspace._name(part)
            report["estimated"] = source.stat().st_size * (8 if action["zip"] else 4)
            with source.open("rb") as stream:
                stream.read(1)
            report["ok"] = True
        except (OSError, ValueError) as error:
            report["error"] = str(error)
        reports.append(report)
    estimated = sum(row["estimated"] for row in reports) + 64 * 1024 * 1024
    free = shutil.disk_usage(directory).free
    with tempfile.TemporaryFile(dir=directory) as stream:
        stream.write(b"check")
    return {"files": reports, "estimated": estimated, "free": free,
            "ok": bool(records) and all(r["ok"] for r in reports) and free >= estimated,
            "error": "" if free >= estimated else "보수적인 예상 필요 공간보다 여유 공간이 부족합니다."}


def digest(path, cancel=None):
    result = hashlib.sha256()
    with safe_path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            pdf_tools.check_cancel(cancel)
            result.update(chunk)
    return result.hexdigest()


def run_action(records, action, output, cancel=None, on_event=None, completed=None):
    """중간 산출물은 임시 폴더에 두고 최종 결과만 새 이름으로 발행한다."""
    cancel = cancel if cancel is not None else threading.Event()
    action = validate_action(action)
    result = {"status": "running", "outputs": [], "files": [], "error": "", "warnings": [],
              "action": action, "inputs": copy.deepcopy(records), "output_dir": str(output)}
    emit = on_event or (lambda value: None)
    completed = completed or {}
    try:
        report = preflight(records, action, output, cancel)
        result["preflight"] = report
        if not report["ok"]:
            raise ValueError(report["error"] or "\n".join(r["source"] + ": " + r["error"] for r in report["files"] if not r["ok"]))
        directory = safe_path(output)
        for index, record in enumerate(records, 1):
            pdf_tools.check_cancel(cancel)
            emit({"index": index, "total": len(records), "source": record["source"], "state": "running"})
            source = safe_path(record["source"])
            input_hash = digest(source, cancel)
            previous = completed.get(str(source))
            if previous:
                if previous.get("input_sha256") != input_hash:
                    raise ValueError("입력이 변경되어 이어하기를 보류했습니다.")
                if previous.get("state") == "completed" and previous.get("outputs") and all(
                        digest(row["path"], cancel) == row["sha256"] for row in previous["outputs"]):
                    result["outputs"].extend(copy.deepcopy(previous["outputs"]))
                    result["files"].append({"source": str(source), "state": "completed"})
                    emit({"index": index, "total": len(records), "source": str(source), "state": "completed",
                          "input_sha256": input_hash, "outputs": previous["outputs"]})
                    continue
                if previous.get("outputs") or previous.get("intent"):
                    raise ValueError("완료 결과 확인이 필요하여 중복 변환을 보류했습니다.")
            file_outputs = []
            target_dir = directory / Path(record["relative"]).parent
            safe_path(target_dir, exists=False)
            target_dir.mkdir(parents=True, exist_ok=True)
            steps = []
            if action["width"] or action["height"]:
                steps.append({"op": "resize", **{key: action[key] for key in ("width", "height") if action[key]}})
            steps.append({"op": "convert", "format": action["format"], "quality": action["quality"]})
            recipe = {"version": 1, "name": action["name"], "steps": steps}
            target = {"max_bytes": action["max_bytes"], "quality": action["quality"]} if action["max_bytes"] else {}
            with tempfile.TemporaryDirectory(prefix=".flipring-quick-", dir=directory) as work:
                produced = workspace.execute_workspace([str(source)], recipe, target, work, cancel)
                if produced["status"] == "cancelled":
                    raise pdf_tools.Cancelled()
                if produced["status"] != "completed":
                    raise ValueError(produced["error"] or "변환을 완료하지 못했습니다.")
                if digest(source, cancel) != input_hash:
                    raise ValueError("변환 중 입력이 변경되어 발행하지 않았습니다.")
                for number, item in enumerate(produced["outputs"], 1):
                    safe_path(target_dir)
                    name = output_name(record, action, index)
                    if len(produced["outputs"]) > 1:
                        name = Path(name).stem + f"-{number}" + Path(name).suffix
                    destination = _tracked_publish(item, target_dir, name, source, input_hash, emit, cancel, len(produced["outputs"]))
                    # 발행 직후부터 소유 결과로 기록하여 취소 중에도 결과가 유실되지 않는다.
                    owned = {"path": destination, "source": str(source), "sha256": "", "size": Path(destination).stat().st_size}
                    result["outputs"].append(owned)
                    file_outputs.append(owned)
                    owned["sha256"] = digest(destination)
                    owned["constraints_met"] = not action["max_bytes"] or owned["size"] <= action["max_bytes"]
                    if not owned["constraints_met"]:
                        result["warnings"].append(f"목표 용량 미달성: {Path(destination).name}")
            result["files"].append({"source": str(source), "state": "completed"})
            emit({"index": index, "total": len(records), "source": str(source), "state": "completed",
                  "input_sha256": input_hash, "outputs": copy.deepcopy(file_outputs)})
        if action["zip"]:
            result["bundle_pending"] = True
            bundle_point = completed.get('')
            if bundle_point and bundle_point.get('outputs'):
                if bundle_point['state'] != 'completed' or any(digest(r['path']) != r['sha256'] for r in bundle_point['outputs']):
                    raise ValueError("묶음 결과 확인이 필요하여 중복 생성을 보류했습니다.")
                result['outputs'].extend(copy.deepcopy(bundle_point['outputs']))
            else:
                bundle = create_bundle(result["outputs"], directory, cancel, on_event=emit)
                result["outputs"].append(bundle)
                emit({'state': 'completed', 'source': '', 'input_sha256': '0' * 64, 'outputs': [bundle]})
            result["bundle_pending"] = False
        result["status"] = "completed"
    except (pdf_tools.Cancelled, engine.Cancelled):
        result["status"] = "cancelled"
    except Exception as error:
        result["status"], result["error"] = "failed", str(error)
    return result


def create_bundle(rows, output, cancel=None, on_event=None):
    """이미 완료된 결과를 다시 변환하지 않고 ZIP 단계만 재시도할 수 있다."""
    directory = safe_path(output)
    with tempfile.TemporaryDirectory(prefix=".flipring-zip-", dir=directory) as work:
        archive = Path(work) / "submission.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as stream:
            for row in rows:
                pdf_tools.check_cancel(cancel)
                path = safe_path(row["path"])
                if digest(path, cancel) != row["sha256"]:
                    raise ValueError("변경된 결과로 ZIP을 만들지 않았습니다: " + str(path))
                with path.open("rb") as source, stream.open(str(path.relative_to(directory)).replace("\\", "/"), "w") as target:
                    while chunk := source.read(1024 * 1024):
                        pdf_tools.check_cancel(cancel)
                        target.write(chunk)
        path = (_tracked_publish(archive, directory, "제출용.zip", "", "0" * 64, on_event, cancel)
                if on_event else workspace._publish(archive, directory, "제출용.zip", cancel))
        return {"path": path, "source": "", "sha256": digest(path), "size": Path(path).stat().st_size, "constraints_met": True}


class OutputLedger:
    """현재 세션 소유 결과만 해시 검증 후 보관 폴더로 이동한다. 영구 삭제하지 않는다."""
    def __init__(self, on_change=None):
        self.on_change = on_change or (lambda: None)
        self.rows = {}
        self.moves = []

    def register(self, rows):
        for row in rows:
            if row.get("sha256"):
                self.rows[row["path"]] = copy.deepcopy(row)

    def cleanup(self, paths):
        moved, errors = [], []
        for raw in dict.fromkeys(paths):
            try:
                row = self.rows.get(str(raw))
                if not row:
                    raise ValueError("현재 세션에서 생성한 결과만 정리할 수 있습니다.")
                path = safe_path(raw)
                if digest(path) != row["sha256"]:
                    raise ValueError("변경된 결과를 보존했습니다: " + str(path))
                folder = path.parent / ".flipring-undo"
                safe_path(folder, exists=False)
                folder.mkdir(exist_ok=True)
                target = folder / (uuid.uuid4().hex + path.suffix)
                move = {"original": str(path), "stored": str(target), "sha256": row["sha256"]}
                self.moves.append(move)
                try:
                    self.on_change()
                    path.rename(target)
                except BaseException:
                    self.moves.remove(move)
                    raise
                self.on_change()
                moved.append(move)
                if digest(target) != row["sha256"]:
                    raise ValueError("정리 중 변경을 발견했습니다. 보관 파일을 유지합니다: " + str(target))
            except (OSError, ValueError) as error:
                errors.append(str(error))
        return {"moved": moved, "errors": errors}

    def undo(self):
        restored, errors = [], []
        for row in list(reversed(self.moves)):
            try:
                stored = safe_path(row["stored"])
                original = safe_path(row["original"], exists=False)
                if original.exists():
                    raise ValueError("같은 이름의 파일이 있어 덮어쓰지 않았습니다: " + str(original))
                if digest(stored) != row["sha256"]:
                    raise ValueError("보관 결과가 변경되어 복원하지 않았습니다.")
                path = workspace._publish(stored, original.parent, original.name)
                # 원본 경로 충돌 시 새 결과도 보존하며 실제 복원 위치를 알린다.
                if digest(path) != row["sha256"] or digest(stored) != row["sha256"]:
                    raise ValueError("복원 중 변경을 발견했습니다. 두 파일을 모두 보존했습니다.")
                stored.unlink()
                self.moves.remove(row)
                restored.append(path)
                owned = self.rows.pop(row["original"], None)
                if owned:
                    owned["path"] = path
                    self.rows[path] = owned
                self.on_change()
            except (OSError, ValueError) as error:
                errors.append(str(error))
        return {"restored": restored, "errors": errors}
