"""로컬 작업 레시피 실행기. 원본과 기존 결과를 덮어쓰지 않는다."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date
import io
import json
import math
import os
from pathlib import Path
import re
import string
import tempfile
import threading

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageSequence
from pypdf import PdfReader, PdfWriter, Transformation
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

import engine
import pdf_tools
from pdf_lock import PDFIUM_LOCK


_FIELDS = {
    "convert": {"format", "quality", "dpi"},
    "resize": {"width", "height"},
    "watermark": {"text", "image", "opacity", "position", "font_size"},
    "ocr": {"format", "language"}, "redact": {"rectangles"},
    "rename": {"template", "start"}, "combine_pdf": {"dpi", "page_size"},
    "collage": {"columns", "cell_width", "cell_height", "padding", "format"},
    "gif": {"duration", "loop", "width", "height"},
    "receipts_xlsx": {"language"}, "compress_pdf": {"quality", "dpi", "mode"},
    "normalize_pages": {"page_size", "dpi"}, "audit": set(),
}
SUPPORTED_OPERATIONS = tuple(_FIELDS)
_FORMATS = {value for _, outputs in engine.TABLE.values() for value in outputs.split()}
_IMAGE_FORMATS = {"png", "jpg", "webp", "tiff", "avif", "bmp", "gif"}
_STORE_LOCK = threading.RLock()
_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)", re.I)
_INVALID_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MAX_PIXELS = 40_000_000
_MAX_FRAMES = 500
_MAX_RECIPES = 1000
_MAX_RECIPE_BYTES = 2 * 1024 * 1024


def _number(value, label, low, high, *, integer=True):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label}: 숫자를 입력해 주세요.")
    if not math.isfinite(value) or not low <= value <= high or (integer and int(value) != value):
        raise ValueError(f"{label}: 허용 범위 {low}~{high}를 확인해 주세요.")
    return int(value) if integer else float(value)


def _name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError("파일 이름은 1~200자의 문자열이어야 합니다.")
    if value in (".", "..") or value != value.rstrip(" .") or _INVALID_NAME.search(value) or _RESERVED.match(value):
        raise ValueError("경로 문자·예약 이름·끝 공백이나 마침표를 사용할 수 없습니다.")
    return value


def _template(template):
    if not isinstance(template, str) or len(template) > 180 or not template:
        raise ValueError("이름 규칙을 입력해 주세요.")
    try:
        for _, field, spec, conversion in string.Formatter().parse(template):
            if field is None:
                continue
            if field not in ("name", "index", "date") or conversion:
                raise ValueError("이름 규칙은 {name}, {index}, {date}만 지원합니다.")
            if spec and (field != "index" or re.fullmatch(r"0?[1-9]?[0-9]?d", spec) is None):
                raise ValueError("번호 자리수는 1~99 범위의 정수 형식만 지원합니다.")
        _name(template.format(name="파일", index=1, date="2026-01-01"))
    except (KeyError, IndexError, AttributeError, TypeError) as error:
        raise ValueError("이름 규칙을 확인해 주세요.") from error
    return template


def _rectangles(value):
    if not isinstance(value, list) or len(value) > 10000:
        raise ValueError("가림 영역 목록을 확인해 주세요.")
    result = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"page", "rect"}:
            raise ValueError("가림 영역에는 page와 rect만 사용할 수 있습니다.")
        page = _number(item["page"], "페이지", 0, 100000)
        rect = item["rect"]
        if not isinstance(rect, (list, tuple)) or len(rect) != 4:
            raise ValueError("가림 영역은 [x, y, 폭, 높이]입니다.")
        x, y, width, height = [_number(v, "가림 좌표", 0, 1, integer=False) for v in rect]
        if width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
            raise ValueError("가림 영역은 페이지 내부의 양수 크기여야 합니다.")
        result.append({"page": page, "rect": [x, y, width, height]})
    return result


def _options(raw, operation):
    if not isinstance(raw, dict) or set(raw) - ({"op"} | _FIELDS[operation]):
        raise ValueError(f"{operation}: 지원하지 않는 옵션입니다.")
    options = dict(raw)
    bounds = {"quality": (20, 95), "dpi": (60, 600), "width": (1, 12000),
              "height": (1, 12000), "columns": (1, 100), "cell_width": (1, 12000),
              "cell_height": (1, 12000), "padding": (0, 1000), "duration": (20, 60000),
              "loop": (0, 65535), "font_size": (6, 1000), "start": (1, 1000000000)}
    for field, (low, high) in bounds.items():
        if field in options:
            options[field] = _number(options[field], field, low, high)
    if "opacity" in options:
        options["opacity"] = _number(options["opacity"], "opacity", 0, 1, integer=False)
    if "format" in options:
        if not isinstance(options["format"], str):
            raise ValueError("출력 형식을 확인해 주세요.")
        options["format"] = engine.ALIASES.get(options["format"].lower(), options["format"].lower())
        allowed = {"txt", "pdf", "docx", "xlsx"} if operation == "ocr" else _IMAGE_FORMATS if operation == "collage" else _FORMATS
        if options["format"] not in allowed:
            raise ValueError("지원하지 않는 출력 형식입니다.")
    if operation == "convert" and "format" not in options:
        raise ValueError("변환 단계에는 출력 format이 필요합니다.")
    if "language" in options and options["language"] not in ("kor", "eng", "kor+eng", "eng+kor"):
        raise ValueError("OCR 언어를 확인해 주세요.")
    if options.get("language") == "eng+kor":
        options["language"] = "kor+eng"
    if "page_size" in options and options["page_size"] not in ("A4", "original"):
        raise ValueError("페이지 크기는 A4 또는 original입니다.")
    if "mode" in options and options["mode"] not in ("lossless", "images"):
        raise ValueError("PDF 압축 방식은 lossless 또는 images입니다.")
    if "position" in options and options["position"] not in ("center", "top_left", "top_right", "bottom_left", "bottom_right"):
        raise ValueError("워터마크 위치를 확인해 주세요.")
    if "text" in options and (not isinstance(options["text"], str) or len(options["text"]) > 10000):
        raise ValueError("워터마크 문구는 10000자 이하 문자열이어야 합니다.")
    if "image" in options and (not isinstance(options["image"], str) or not options["image"]):
        raise ValueError("워터마크 이미지 경로를 확인해 주세요.")
    if operation == "watermark" and not (options.get("text") or options.get("image")):
        raise ValueError("워터마크 문구 또는 이미지가 필요합니다.")
    if "template" in options:
        _template(options["template"])
    if "rectangles" in options:
        options["rectangles"] = _rectangles(options["rectangles"])
    if operation == "redact" and not options.get("rectangles"):
        raise ValueError("사용자가 검토한 가림 영역이 필요합니다.")
    return options


def validate_recipe(recipe: dict) -> dict:
    """코드·셸·임의 필드를 허용하지 않는 버전 1 JSON 레시피를 정규화한다."""
    if not isinstance(recipe, dict) or set(recipe) != {"version", "name", "steps"}:
        raise ValueError("레시피에는 version, name, steps가 필요합니다.")
    if type(recipe["version"]) is not int or recipe["version"] != 1:
        raise ValueError("지원하는 레시피 버전은 1입니다.")
    name = recipe["name"]
    if not isinstance(name, str) or not name.strip() or len(name) > 100 or any(ord(c) < 32 for c in name):
        raise ValueError("레시피 이름은 1~100자의 문자열이어야 합니다.")
    steps = recipe["steps"]
    if not isinstance(steps, list) or len(steps) > 100:
        raise ValueError("레시피 단계는 최대 100개의 목록이어야 합니다.")
    normalized = []
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("op"), str) or step["op"] not in _FIELDS:
            raise ValueError("지원하지 않는 레시피 단계입니다.")
        normalized.append(_options(step, step["op"]))
    return {"version": 1, "name": name.strip(), "steps": normalized}


def _target(raw):
    if raw is None:
        return {}
    if not isinstance(raw, dict) or set(raw) - {"format", "max_bytes", "page_size", "quality", "dpi", "rectangles"}:
        raise ValueError("지원하지 않는 목표 옵션입니다.")
    result = dict(raw)
    shared = {key: value for key, value in result.items() if key in {"format", "quality", "dpi"}}
    if shared:
        result.update({key: value for key, value in _options({"op": "convert", "format": shared.get("format", "pdf"), **shared}, "convert").items()
                       if key != "op" and (key != "format" or "format" in raw)})
    if "max_bytes" in result:
        result["max_bytes"] = _number(result["max_bytes"], "용량 상한", 1, 1024 ** 5)
    if "page_size" in result and result["page_size"] not in ("A4", "original"):
        raise ValueError("목표 페이지 크기는 A4 또는 original입니다.")
    if "rectangles" in result:
        result["rectangles"] = _rectangles(result["rectangles"])
    if result.get("page_size") == "A4" and result.get("format", "pdf") != "pdf":
        raise ValueError("A4 페이지 목표의 출력 형식은 PDF여야 합니다.")
    return result


def _input_paths(paths):
    if not isinstance(paths, (list, tuple)) or not paths or len(paths) > 10000:
        raise ValueError("작업할 파일을 선택해 주세요.")
    result = []
    for raw in paths:
        path = Path(raw).resolve(strict=True)
        if not path.is_file():
            raise ValueError("작업 공간은 일반 파일만 지원합니다.")
        result.append(path)
    return result


def preview_names(paths, template, start=1) -> list[dict]:
    """규칙에 확장자를 붙여 미리 보여 주며 경로 탈출과 Windows 예약 이름을 거부한다."""
    _template(template)
    start = _number(start, "시작 번호", 1, 1000000000)
    result = []
    for index, path in enumerate(_input_paths(paths), start):
        suffix = ".tar.gz" if path.name.lower().endswith(".tar.gz") else path.suffix
        name = template.format(name=engine.stem(path), index=index, date=date.today().isoformat())
        _name(name)
        if suffix and not name.lower().endswith(suffix.lower()):
            name += suffix
        result.append({"source": str(path), "name": _name(name)})
    return result


def _directory(path, fallback):
    directory = Path(path).resolve() if path is not None else Path(fallback).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if not directory.is_dir():
        raise ValueError("결과 폴더를 확인해 주세요.")
    return directory


def _publish(produced, directory, name, cancel=None):
    """배타적 생성으로 충돌을 회피하고 현재 호출이 만든 미완료 파일만 정리한다."""
    produced = Path(produced)
    name = _name(name)
    if not produced.is_file():
        raise ValueError("유효한 결과 파일을 만들지 못했습니다.")
    suffix = ".tar.gz" if name.lower().endswith(".tar.gz") else Path(name).suffix
    stem = name[:-len(suffix)] if suffix else name
    for index in range(1, 100000):
        pdf_tools.check_cancel(cancel)
        candidate = directory / (name if index == 1 else f"{stem} {index}{suffix}")
        try:
            stream = candidate.open("xb")
        except FileExistsError:
            continue
        try:
            with stream, produced.open("rb") as source:
                while block := source.read(1024 * 1024):
                    pdf_tools.check_cancel(cancel)
                    stream.write(block)
            pdf_tools.check_cancel(cancel)
            return str(candidate)
        except BaseException:
            candidate.unlink(missing_ok=True)
            raise
    raise ValueError("새 결과 파일 이름을 만들지 못했습니다.")


def rename_copies(paths, template="{name}_{index}", start=1, output_dir=None, cancel=None, on_event=None):
    """이름 변경은 복사본에만 적용하며 원본 이름과 내용은 보존한다."""
    names = preview_names(paths, template, start)
    result = []
    for index, item in enumerate(names, 1):
        source = Path(item["source"])
        directory = _directory(output_dir, source.parent)
        output = _publish(source, directory, item["name"], cancel)
        result.append(output)
        if on_event:
            on_event({"state": "file_completed", "step": index, "total": len(names), "label": "rename", "path": output})
    return result


class RecipeStore:
    """손상된 저장소는 보존하고 유효한 레시피만 원자 교체한다."""
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        with _STORE_LOCK:
            if not self.path.exists():
                return []
            try:
                if self.path.stat().st_size > _MAX_RECIPE_BYTES:
                    raise ValueError("레시피 저장소 크기가 너무 큽니다.")
                raw = json.loads(self.path.read_text(encoding="utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
                if not isinstance(raw, list) or len(raw) > _MAX_RECIPES:
                    raise ValueError("레시피 저장소 목록을 확인해 주세요.")
                recipes = [validate_recipe(item) for item in raw]
                if len({item["name"] for item in recipes}) != len(recipes):
                    raise ValueError("중복된 레시피 이름입니다.")
                return recipes
            except (OSError, UnicodeError, ValueError, TypeError) as error:
                raise ValueError("레시피 저장소가 손상되었거나 읽을 수 없습니다. 원본 파일을 보존했습니다.") from error

    def _write(self, recipes):
        if not isinstance(recipes, list) or len(recipes) > _MAX_RECIPES:
            raise ValueError("레시피 저장소는 최대 1000개까지 저장할 수 있습니다. 기존 파일을 보존했습니다.")
        encoded = (json.dumps(recipes, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")
        if len(encoded) > _MAX_RECIPE_BYTES:
            raise ValueError("레시피 저장소는 최대 2MiB까지 저장할 수 있습니다. 기존 파일을 보존했습니다.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            # 사전 검사한 UTF-8 바이트를 그대로 써서 Windows 개행 변환으로 한도를 넘지 않는다.
            with tempfile.NamedTemporaryFile(mode="wb", dir=self.path.parent,
                                             prefix=".flipring-recipes-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def save(self, recipe):
        normalized = validate_recipe(recipe)
        with _STORE_LOCK:
            recipes = self.load()
            found = next((i for i, item in enumerate(recipes) if item["name"] == normalized["name"]), None)
            if found is None:
                recipes.append(normalized)
            else:
                recipes[found] = normalized
            self._write(recipes)
        return normalized

    def delete(self, name):
        with _STORE_LOCK:
            recipes = self.load()
            remaining = [item for item in recipes if item["name"] != name]
            if len(remaining) != len(recipes):
                self._write(remaining)
                return True
            return False


@contextmanager
def _engine_cancel(cancel):
    previous = getattr(engine._CONTEXT, "cancel", None)
    engine._CONTEXT.cancel = cancel
    try:
        yield
    finally:
        engine._CONTEXT.cancel = previous


def _image(path):
    with Image.open(path) as source:
        if source.width * source.height > _MAX_PIXELS:
            raise ValueError("이미지가 너무 큽니다. 4000만 픽셀 이하를 사용해 주세요.")
        transparent = "A" in source.getbands() or "transparency" in source.info
        return ImageOps.exif_transpose(source).convert("RGBA" if transparent else "RGB")


def _flat(image):
    """투명도를 지원하지 않는 형식은 기존 변환 엔진처럼 흰 배경에 합성한다."""
    rgba = image.convert("RGBA")
    background = Image.new("RGB", image.size, "white")
    background.paste(rgba, mask=rgba.getchannel("A"))
    return background


def _save_image(image, destination, quality=85, dpi=150):
    if image.width * image.height > _MAX_PIXELS:
        raise ValueError("결과 이미지가 4000만 픽셀을 초과합니다.")
    if destination.suffix.lower() in (".jpg", ".bmp", ".pdf"):
        image = _flat(image)
    image.save(destination, format={"jpg": "JPEG", "tiff": "TIFF"}.get(destination.suffix[1:], destination.suffix[1:].upper()),
               quality=quality, dpi=(dpi, dpi), optimize=True)


def _reencode_image(path, destination, quality=85, dpi=150, cancel=None, *, transform=None, output_size=None):
    """프레임별 처리를 적용하고 프레임·시간·반복 정보를 함께 보존한다."""
    pdf_tools.check_cancel(cancel)
    with Image.open(path) as source:
        count = getattr(source, "n_frames", 1)
        if count > _MAX_FRAMES:
            raise ValueError(f"이미지 프레임 수가 상한 {_MAX_FRAMES}개를 초과합니다.")
        if source.width * source.height * count > _MAX_PIXELS:
            raise ValueError("이미지 전체 프레임의 합계가 4000만 픽셀을 초과합니다.")
        if output_size is not None and output_size[0] * output_size[1] * count > _MAX_PIXELS:
            raise ValueError("처리 결과 전체 프레임의 합계가 4000만 픽셀을 초과합니다.")
        if count == 1:
            image = _image(path)
            pdf_tools.check_cancel(cancel)
            if transform is not None:
                image = transform(image)
            pdf_tools.check_cancel(cancel)
            _save_image(image, destination, quality, dpi)
            pdf_tools.check_cancel(cancel)
            return
        source_format = engine.ALIASES.get(source.format.lower(), source.format.lower())
        target_format = engine.ALIASES.get(destination.suffix[1:].lower(), destination.suffix[1:].lower())
        # 다른 형식의 프레임·반복 의미를 같다고 추정하지 않는다.
        if target_format != source_format or target_format not in {"gif", "webp", "png", "tiff"}:
            raise ValueError("다중 프레임 이미지는 GIF·WebP·APNG·TIFF의 동일 형식 재저장만 지원합니다. 프레임을 버리는 변환은 실행하지 않았습니다.")
        information = dict(source.info)
        poster = bool(information.get("default_image", False)) if source_format == "png" else False
        frames, durations, pixels, output_pixels = [], [], 0, 0
        for index, frame in enumerate(ImageSequence.Iterator(source)):
            pdf_tools.check_cancel(cancel)
            pixels += frame.width * frame.height
            if pixels > _MAX_PIXELS:
                raise ValueError("이미지 전체 프레임의 합계가 4000만 픽셀을 초과합니다.")
            # 로더가 합성한 전체 프레임을 복사하므로 이전 객체의 수명에 의존하지 않는다.
            copied = ImageOps.exif_transpose(frame).convert("RGBA")
            if transform is not None:
                copied = transform(copied)
            pdf_tools.check_cancel(cancel)
            output_pixels += copied.width * copied.height
            if output_pixels > _MAX_PIXELS:
                raise ValueError("처리 결과 전체 프레임의 합계가 4000만 픽셀을 초과합니다.")
            frames.append(copied)
            if not (poster and index == 0):
                duration = frame.info.get("duration", 0)
                if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration < 0:
                    raise ValueError("이미지 프레임 표시 시간이 올바르지 않습니다.")
                durations.append(duration)
        pdf_tools.check_cancel(cancel)
        if len(frames) != count:
            raise ValueError("이미지 프레임을 모두 읽지 못했습니다.")
        options = {"save_all": True, "append_images": frames[1:], "quality": quality, "dpi": (dpi, dpi)}
        if source_format != "tiff":
            options["duration"] = durations
            if "loop" in information:
                options["loop"] = information["loop"]
        if source_format == "png":
            # 이미 합성된 픽셀을 그대로 대체하여 disposal·blend의 이중 적용을 막는다.
            options.update(default_image=poster, disposal=0, blend=0)
        elif source_format == "gif":
            options.update(disposal=2, optimize=False)
        frames[0].save(destination, format={"tiff": "TIFF"}.get(source_format, source_format.upper()), **options)
        pdf_tools.check_cancel(cancel)
        # 인코더가 프레임을 합치거나 시간을 바꾼 경우 완료로 게시하지 않는다.
        with Image.open(destination) as output:
            if getattr(output, "n_frames", 1) != count:
                raise ValueError("저장기가 다중 프레임 수를 보존하지 못했습니다. 결과를 게시하지 않았습니다.")
            if source_format != "tiff":
                if output.info.get("loop") != information.get("loop") or bool(output.info.get("default_image", False)) != poster:
                    raise ValueError("저장기가 애니메이션 반복·기본 이미지를 보존하지 못했습니다.")
                saved_durations = []
                for index, frame in enumerate(ImageSequence.Iterator(output)):
                    pdf_tools.check_cancel(cancel)
                    frame.load()
                    if not (poster and index == 0):
                        saved_durations.append(frame.info.get("duration", 0))
                if saved_durations != durations:
                    raise ValueError("저장기가 프레임 표시 시간을 보존하지 못했습니다. 결과를 게시하지 않았습니다.")


def _image_pdf(path, destination, dpi, cancel):
    document = canvas.Canvas(str(destination))
    with Image.open(path) as source:
        for frame in ImageSequence.Iterator(source):
            pdf_tools.check_cancel(cancel)
            if frame.width * frame.height > _MAX_PIXELS:
                raise ValueError("이미지가 너무 큽니다.")
            image = _flat(ImageOps.exif_transpose(frame))
            width, height = (dimension * 72 / dpi for dimension in image.size)
            document.setPageSize((width, height))
            document.drawImage(ImageReader(image), 0, 0, width=width, height=height)
            document.showPage()
    document.save()


def _write_pdf(writer, destination, cancel):
    try:
        pdf_tools.check_cancel(cancel)
        if not writer.pages:
            raise ValueError("페이지가 없는 PDF를 저장할 수 없습니다.")
        writer.write(str(destination))
        pdf_tools.check_cancel(cancel)
    finally:
        writer.close()


def _combine(paths, destination, work, options, cancel):
    writer = PdfWriter()
    try:
        for index, path in enumerate(paths):
            pdf_tools.check_cancel(cancel)
            source = path
            if path.suffix.lower() != ".pdf":
                source = work / f"image-{index}.pdf"
                _image_pdf(path, source, options.get("dpi", 150), cancel)
            writer.append(pdf_tools.reader_for(source))
        _write_pdf(writer, destination, cancel)
    except BaseException:
        writer.close()
        raise
    if options.get("page_size") == "A4":
        normalized = work / "a4.pdf"
        _normalize(destination, normalized, cancel)
        return normalized
    return destination


def _normalize(path, destination, cancel):
    reader = pdf_tools.reader_for(path)
    source_writer = PdfWriter()
    writer = PdfWriter()
    try:
        for original in reader.pages:
            pdf_tools.check_cancel(cancel)
            # 회전 정규화는 원본 Reader가 아닌 Writer에 복제한 페이지에 적용한다.
            page = source_writer.add_page(original)
            page.transfer_rotation_to_content()
            width, height = float(page.mediabox.width), float(page.mediabox.height)
            if not all(math.isfinite(v) and v > 0 for v in (width, height)):
                raise ValueError("PDF 페이지 크기를 확인해 주세요.")
            scale = min(A4[0] / width, A4[1] / height)
            transform = Transformation().translate(-float(page.mediabox.left), -float(page.mediabox.bottom)).scale(scale).translate(
                (A4[0] - width * scale) / 2, (A4[1] - height * scale) / 2)
            target = writer.add_blank_page(width=A4[0], height=A4[1])
            target.merge_transformed_page(page, transform)
        _write_pdf(writer, destination, cancel)
    except BaseException:
        writer.close()
        raise
    finally:
        source_writer.close()


def _compress(path, destination, options, cancel):
    writer = PdfWriter()
    try:
        for original in pdf_tools.reader_for(path).pages:
            pdf_tools.check_cancel(cancel)
            page = writer.add_page(original)
            if options.get("mode", "images") == "images":
                cap = max(1, int(max(float(page.mediabox.width), float(page.mediabox.height)) * options.get("dpi", 150) / 72))
                for item in list(page.images):
                    pdf_tools.check_cancel(cancel)
                    image = item.image.copy()
                    if image.width * image.height > _MAX_PIXELS:
                        raise ValueError("PDF 안의 이미지가 너무 큽니다.")
                    image.thumbnail((cap, cap))
                    item.replace(image, quality=options.get("quality", 80))
            page.compress_content_streams(level=6)
        writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
        _write_pdf(writer, destination, cancel)
    except BaseException:
        writer.close()
        raise


def _position(container, item, position, margin=8):
    width, height = container
    item_width, item_height = item
    x = max(0, (width - item_width) / 2)
    y = max(0, (height - item_height) / 2)
    if "left" in position:
        x = min(margin, max(0, width - item_width))
    elif "right" in position:
        x = max(0, width - item_width - margin)
    if "top" in position:
        y = min(margin, max(0, height - item_height))
    elif "bottom" in position:
        y = max(0, height - item_height - margin)
    return x, y


def _watermark_image(image, options):
    overlay = Image.new("RGBA", image.size)
    position = options.get("position", "bottom_right")
    opacity = options.get("opacity", 0.45)
    if options.get("image"):
        with Image.open(options["image"]) as original:
            if original.width * original.height > _MAX_PIXELS:
                raise ValueError("워터마크 이미지가 너무 큽니다.")
            mark = ImageOps.exif_transpose(original).convert("RGBA")
        mark.thumbnail((max(1, image.width // 3), max(1, image.height // 3)))
        mark.putalpha(mark.getchannel("A").point(lambda alpha: round(alpha * opacity)))
        x, y = _position(image.size, mark.size, position)
        overlay.alpha_composite(mark, (int(x), int(y)))
    if options.get("text"):
        font = ImageFont.truetype(str(engine.asset("NanumGothicBold.ttf")), options.get("font_size", 24))
        draw = ImageDraw.Draw(overlay)
        box = draw.textbbox((0, 0), options["text"], font=font)
        x, y = _position(image.size, (box[2] - box[0], box[3] - box[1]), position)
        draw.text((x - box[0], y - box[1]), options["text"], font=font, fill=(0, 0, 0, round(255 * opacity)))
    return Image.alpha_composite(image.convert("RGBA"), overlay)


def _watermark(path, destination, options, cancel):
    if path.suffix.lower() != ".pdf":
        _reencode_image(path, destination, cancel=cancel,
                        transform=lambda image: _watermark_image(image, options))
        return
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    font = "FlipRingWorkspace"
    if font not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(font, str(engine.asset("NanumGothicBold.ttf"))))
    writer = PdfWriter()
    try:
        for original in pdf_tools.reader_for(path).pages:
            pdf_tools.check_cancel(cancel)
            page = writer.add_page(original)
            page.transfer_rotation_to_content()
            width, height = float(page.mediabox.width), float(page.mediabox.height)
            buffer = io.BytesIO()
            stamp = canvas.Canvas(buffer, pagesize=(width, height))
            stamp.setFillAlpha(options.get("opacity", 0.45))
            position = options.get("position", "bottom_right")
            if options.get("image"):
                image = _flat(_image(options["image"]))
                factor = min(width / (3 * image.width), height / (3 * image.height))
                size = image.width * factor, image.height * factor
                x, y = _position((width, height), size, position)
                stamp.drawImage(ImageReader(image), x, height - y - size[1], width=size[0], height=size[1])
            if options.get("text"):
                size = options.get("font_size", 24)
                stamp.setFont(font, size)
                x, y = _position((width, height), (pdfmetrics.stringWidth(options["text"], font, size), size), position)
                stamp.drawString(x, height - y - size, options["text"])
            stamp.save()
            buffer.seek(0)
            page.merge_page(PdfReader(buffer).pages[0])
        _write_pdf(writer, destination, cancel)
    except BaseException:
        writer.close()
        raise


def _recognize(path, language="kor+eng", cancel=None):
    from inspection_tools import recognize_editable
    return recognize_editable(str(path), language=language, cancel=cancel)


def _receipts(paths, destination, options, cancel):
    import xlsxwriter
    book = xlsxwriter.Workbook(str(destination), {"strings_to_formulas": False, "strings_to_urls": False})
    try:
        sheet = book.add_worksheet("영수증 OCR")
        row_index = 0
        for path in paths:
            pdf_tools.check_cancel(cancel)
            content = _recognize(path, options.get("language", "kor+eng"), cancel)
            sheet.write_string(row_index, 0, path.name)
            row_index += 1
            words = content.get("words", [])
            pages = sorted({word.get("page", 0) for word in words})
            rows = []
            for page in pages:
                converted = []
                for word in words:
                    if word.get("page", 0) != page:
                        continue
                    x, y, width, height = word["rect"]
                    converted.append(pdf_tools.Word(str(word["text"]), x * 1000, y * 1000, (x + width) * 1000, (y + height) * 1000))
                rows.extend(pdf_tools.structured_rows(pdf_tools.PageContent("", converted, 1000, 1000)))
            if not rows:
                rows = [line.split("\t") for line in content.get("text", "").splitlines()] or [[""]]
            for row in rows:
                pdf_tools.check_cancel(cancel)
                for column, value in enumerate(row):
                    sheet.write_string(row_index, column, str(value))
                row_index += 1
            row_index += 1
        sheet.set_column(0, 30, 22)
    finally:
        book.close()


def _single(path, options, work, cancel):
    operation = options["op"]
    if operation == "_quality":
        _, source_format = engine.classify(path)
        output = work / ("quality." + source_format)
        if source_format == "pdf":
            _compress(path, output, {**options, "mode": "images"}, cancel)
        elif source_format in _IMAGE_FORMATS:
            _reencode_image(path, output, options.get("quality", 85), options.get("dpi", 150), cancel)
        else:
            raise ValueError("품질·DPI 목표는 이미지와 PDF 파일에서 지원합니다.")
        return [output]
    if operation == "convert":
        destination_format = options["format"]
        _, source_format = engine.classify(path)
        if destination_format == source_format:
            if source_format in _IMAGE_FORMATS:
                output = work / f"result.{destination_format}"
                _reencode_image(path, output, options.get("quality", 85), options.get("dpi", 150), cancel)
                return [output]
            return [path]
        if destination_format not in engine.targets([path]):
            raise ValueError("이 파일에 사용할 수 없는 출력 형식입니다.")
        missing = engine.requirement(path, destination_format)
        if missing:
            raise ValueError(f"{missing} 도구가 필요합니다.")
        output = work / f"result.{destination_format}"
        if source_format in _IMAGE_FORMATS and destination_format in _IMAGE_FORMATS:
            _reencode_image(path, output, options.get("quality", 85), options.get("dpi", 150), cancel)
        elif source_format in _IMAGE_FORMATS and destination_format == "pdf":
            _image_pdf(path, output, options.get("dpi", 150), cancel)
        else:
            with _engine_cancel(cancel):
                output = engine.produce(path, destination_format, work)
        return sorted(output.iterdir()) if output.is_dir() else [output]
    if operation == "resize":
        # 전체 프레임을 디코딩하기 전에 출력 크기와 저장 형식을 결정한다.
        with Image.open(path) as header:
            original_width, original_height = header.size
            if header.getexif().get(274) in (5, 6, 7, 8):
                original_width, original_height = original_height, original_width
            extension = engine.ALIASES.get(header.format.lower(), header.format.lower()) if getattr(header, "n_frames", 1) > 1 else "png"
        width = options.get("width")
        height = options.get("height")
        if width is None and height is None:
            width, height = 1280, max(1, round(original_height * 1280 / original_width))
        elif width is None:
            width = max(1, round(original_width * height / original_height))
        elif height is None:
            height = max(1, round(original_height * width / original_width))
        if width * height > _MAX_PIXELS:
            raise ValueError("크기 변경 결과가 4000만 픽셀을 초과합니다.")
        output = work / ("resized." + extension)
        _reencode_image(path, output, cancel=cancel, output_size=(width, height),
                        transform=lambda image: image.resize((width, height), Image.Resampling.LANCZOS))
        return [output]
    if operation == "watermark":
        extension = "pdf"
        if path.suffix.lower() != ".pdf":
            with Image.open(path) as header:
                extension = engine.ALIASES.get(header.format.lower(), header.format.lower()) if getattr(header, "n_frames", 1) > 1 else "png"
        output = work / ("watermark." + extension)
        _watermark(path, output, options, cancel)
        return [output]
    if operation == "ocr":
        from inspection_tools import export_edited_text
        recognized = _recognize(path, options.get("language", "kor+eng"), cancel)
        pdf_tools.check_cancel(cancel)
        return [Path(export_edited_text(recognized["text"], str(work), "ocr", format=options.get("format", "txt")))]
    if operation == "redact":
        from inspection_tools import redact_file
        return [Path(redact_file(str(path), options["rectangles"], str(work), cancel=cancel))]
    if operation == "compress_pdf":
        output = work / "compressed.pdf"
        _compress(path, output, options, cancel)
        return [output]
    if operation == "normalize_pages":
        output = work / "normalized.pdf"
        if options.get("page_size", "A4") == "original":
            return [path]
        _normalize(path, output, cancel)
        return [output]
    raise ValueError("지원하지 않는 단일 파일 단계입니다.")


def _combined(paths, options, work, cancel):
    operation = options["op"]
    if operation == "combine_pdf":
        return _combine(paths, work / "combined.pdf", work, options, cancel)
    if operation == "receipts_xlsx":
        output = work / "receipts.xlsx"
        _receipts(paths, output, options, cancel)
        return output
    # 전체 헤더 합계를 먼저 확인하여 거부할 조합을 디코딩하지 않는다.
    pixels = 0
    for path in paths:
        pdf_tools.check_cancel(cancel)
        with Image.open(path) as header:
            pixels += header.width * header.height
        if pixels > _MAX_PIXELS:
            raise ValueError("조합 입력의 합계가 4000만 픽셀을 초과합니다.")
    images = []
    for path in paths:
        pdf_tools.check_cancel(cancel)
        images.append(_image(path))
    if operation == "collage":
        columns = options.get("columns", 2)
        width, height, padding = options.get("cell_width", 480), options.get("cell_height", 360), options.get("padding", 12)
        rows = math.ceil(len(images) / columns)
        size = columns * width + (columns + 1) * padding, rows * height + (rows + 1) * padding
        if size[0] * size[1] > _MAX_PIXELS:
            raise ValueError("콜라주가 4000만 픽셀을 초과합니다.")
        combined = Image.new("RGB", size, "white")
        for index, image in enumerate(images):
            pdf_tools.check_cancel(cancel)
            image.thumbnail((width, height), Image.Resampling.LANCZOS)
            x = padding + index % columns * (width + padding) + (width - image.width) // 2
            y = padding + index // columns * (height + padding) + (height - image.height) // 2
            combined.paste(image, (x, y), image.getchannel("A") if image.mode == "RGBA" else None)
        output = work / ("collage." + options.get("format", "png"))
        _save_image(combined, output)
        return output
    if operation == "gif":
        width, height = options.get("width", 640), options.get("height", 480)
        if width * height * len(images) > _MAX_PIXELS:
            raise ValueError("GIF 전체 프레임이 4000만 픽셀을 초과합니다.")
        frames = []
        for image in images:
            pdf_tools.check_cancel(cancel)
            frames.append(ImageOps.pad(_flat(image), (width, height), color="white"))
        output = work / "animation.gif"
        frames[0].save(output, format="GIF", save_all=True, append_images=frames[1:],
                       duration=options.get("duration", 250), loop=options.get("loop", 0), disposal=2)
        return output
    raise ValueError("지원하지 않는 조합입니다.")


def execute_workspace(paths: list[str], recipe: dict, target: dict | None = None,
                      output_dir: str | None = None, cancel=None, on_event=None) -> dict:
    """단계를 순서대로 실행하고 중간 실패·취소에서도 완료한 새 결과를 반환한다."""
    recipe = validate_recipe(recipe)
    target = _target(target)
    current = _input_paths(paths)
    directory = _directory(output_dir, current[0].parent)
    cancel = cancel if cancel is not None else threading.Event()
    result = {"outputs": [], "steps": [], "checks": [], "constraints_met": True,
              "warnings": [], "status": "running", "error": ""}
    stages = list(recipe["steps"])
    if target.get("rectangles"):
        stages.append({"op": "redact", "rectangles": target["rectangles"]})
    target_format = target.get("format") or ("pdf" if target.get("page_size") == "A4" else None)
    if target_format:
        stages.append({"op": "convert", "format": target_format,
                       "quality": target.get("quality", 85), "dpi": target.get("dpi", 150)})
    if target.get("page_size") == "A4":
        stages.append({"op": "normalize_pages", "page_size": "A4"})
    if ("quality" in target or "dpi" in target) and target_format not in _IMAGE_FORMATS:
        # 형식 선택 없이 요청한 품질·DPI도 실제 재인코딩 단계로 실행한다.
        stages.append({"op": "_quality", "quality": target.get("quality", 85), "dpi": target.get("dpi", 150)})
    if target.get("max_bytes"):
        stages.append({"op": "_size", **target})
    if not stages:
        stages.append({"op": "rename", "template": "{name}-copy"})
    total = len(stages)

    def event(state, step, label, path=None):
        if on_event:
            value = {"state": state, "step": step, "total": total, "label": label}
            if path is not None:
                value["path"] = str(path)
            on_event(value)

    active = None
    try:
        pdf_tools.check_cancel(cancel)
        event("started", 0, recipe["name"])
        # 기존 엔진·검사·PDFium과 같은 재진입 잠금을 사용한다.
        with PDFIUM_LOCK:
            for number, options in enumerate(stages, 1):
                pdf_tools.check_cancel(cancel)
                operation = options["op"]
                active = {"op": operation, "state": "running", "outputs": [], "error": ""}
                result["steps"].append(active)
                event("processing", number, operation)
                if operation == "audit":
                    from inspection_tools import audit_file
                    for source in current:
                        pdf_tools.check_cancel(cancel)
                        result["checks"].extend({**item, "path": str(source)} for item in audit_file(str(source), cancel=cancel))
                    active["state"] = "completed"
                    event("step_completed", number, operation)
                    continue
                next_paths = []

                def complete(produced, name):
                    output = _publish(produced, directory, name, cancel)
                    next_paths.append(Path(output))
                    active["outputs"].append(output)
                    result["outputs"] = list(active["outputs"])
                    event("file_completed", number, operation, output)

                if operation == "rename":
                    for item in preview_names(current, options.get("template", "{name}_{index}"), options.get("start", 1)):
                        complete(item["source"], item["name"])
                elif operation in ("combine_pdf", "collage", "gif", "receipts_xlsx"):
                    with tempfile.TemporaryDirectory(prefix=".flipring-workspace-", dir=directory) as folder:
                        produced = _combined(current, options, Path(folder), cancel)
                        complete(produced, f"{engine.stem(current[0])}-{operation}{produced.suffix}")
                    if operation == "receipts_xlsx":
                        result["warnings"].append("영수증 OCR 표는 인식 후보입니다. 항목과 금액을 검토해 주세요.")
                else:
                    for source in current:
                        pdf_tools.check_cancel(cancel)
                        with tempfile.TemporaryDirectory(prefix=".flipring-workspace-", dir=directory) as folder:
                            work = Path(folder)
                            if operation == "_size":
                                produced = _size_candidate(source, work, options, cancel)
                                outputs = [produced]
                            else:
                                outputs = _single(source, options, work, cancel)
                            for index, produced in enumerate(outputs, 1):
                                extra = f"-{index}" if len(outputs) > 1 else ""
                                complete(produced, f"{engine.stem(source)}-{operation.lstrip('_')}{extra}{produced.suffix}")
                current = next_paths
                active["state"] = "completed"
                event("step_completed", number, operation)
            pdf_tools.check_cancel(cancel)
        for output in result["outputs"]:
            size = Path(output).stat().st_size
            if target.get("max_bytes") and size > target["max_bytes"]:
                result["constraints_met"] = False
                result["warnings"].append(f"목표 용량 미달성: {Path(output).name} · {size} / {target['max_bytes']} 바이트. 결과를 보존했습니다.")
        result["status"] = "completed"
        event("completed", total, recipe["name"])
    except (pdf_tools.Cancelled, engine.Cancelled):
        result["status"] = "cancelled"
        result["constraints_met"] = False
        if active is not None and active["state"] == "running":
            active["state"] = "cancelled"
        result["warnings"].append("작업을 취소했습니다. 원본과 이미 완료한 결과는 보존했습니다.")
        event("cancelled", len(result["steps"]), recipe["name"])
    except Exception as error:
        result["status"] = "failed"
        result["constraints_met"] = False
        result["error"] = str(error)
        if active is not None:
            active["state"] = "failed"
            active["error"] = str(error)
        result["warnings"].append("중간 단계에서 실패했습니다. 원본과 이미 완료한 결과는 보존했습니다.")
        event("failed", len(result["steps"]), str(error))
    return result


def _size_candidate(source, work, options, cancel):
    """요청한 DPI·품질을 시작점으로 유한 후보를 실제 비교하며 달성 여부를 숨기지 않는다."""
    limit = options["max_bytes"]
    best = source
    if source.stat().st_size <= limit:
        return source
    quality = options.get("quality", 85)
    dpi = options.get("dpi", 150)
    _, source_format = engine.classify(source)
    suffix = "." + source_format
    for index, candidate_quality in enumerate(sorted({quality, max(20, quality - 20), 20}, reverse=True)):
        pdf_tools.check_cancel(cancel)
        destination = work / f"candidate-{index}{suffix}"
        if suffix == ".pdf":
            _compress(source, destination, {"mode": "images", "quality": candidate_quality, "dpi": dpi}, cancel)
        elif source_format in _IMAGE_FORMATS:
            _reencode_image(source, destination, candidate_quality, dpi, cancel)
        else:
            break
        if destination.stat().st_size < best.stat().st_size:
            best = destination
        if best.stat().st_size <= limit:
            break
    return best
