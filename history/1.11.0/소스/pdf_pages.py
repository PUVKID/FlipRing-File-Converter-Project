"""원본 바이트와 분리된 PDF 페이지 편집 모델. 결과는 새 파일로만 저장한다."""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import io
from pathlib import Path
import tempfile

from pypdf import PdfReader, PdfWriter
import pypdfium2 as pdfium

from pdf_lock import PDFIUM_LOCK
from pdf_tools import PdfToolError, check_cancel, publish, source_context, preflight_output


@dataclass(frozen=True)
class PageRef:
    source_index: int
    rotation: int = 0


class PdfWorkspace:
    """열 때 읽은 PDF만 보관하여 외부 파일 변경과 편집 순서를 분리한다."""

    def __init__(self, source, content, count):
        self.source = Path(source)
        self._content = content
        self.source_sha256 = hashlib.sha256(content).hexdigest()
        self.pages = [PageRef(index) for index in range(count)]

    @classmethod
    def open(cls, path, cancel=None):
        source = Path(path).resolve()
        with source_context(source):
            check_cancel(cancel)
            if not source.is_file():
                raise PdfToolError("input_files")
            content = source.read_bytes()
            check_cancel(cancel)
            try:
                reader = PdfReader(io.BytesIO(content), strict=False)
                if reader.is_encrypted:
                    raise PdfToolError("encrypted_pdf")
                count = len(reader.pages)
                if not count:
                    raise PdfToolError("empty_pdf")
            except PdfToolError:
                raise
            except Exception as error:
                raise PdfToolError("invalid_pdf", str(error)) from error
            check_cancel(cancel)
            return cls(source, content, count)

    @property
    def page_count(self):
        return len(self.pages)

    def _indices(self, values):
        try:
            indices = list(values)
        except TypeError as error:
            raise PdfToolError("page_range") from error
        if not indices or any(type(index) is not int or not 0 <= index < self.page_count for index in indices):
            raise PdfToolError("page_range")
        return sorted(set(indices))

    def reorder(self, indices):
        order = list(indices)
        if len(order) != self.page_count or self._indices(order) != list(range(self.page_count)):
            raise PdfToolError("page_range")
        self.pages = [self.pages[index] for index in order]

    def rotate(self, indices, angle=90):
        chosen = self._indices(indices)
        if type(angle) is not int or angle not in (90, 180, 270):
            raise PdfToolError("rotation")
        for index in chosen:
            self.pages[index] = replace(self.pages[index], rotation=(self.pages[index].rotation + angle) % 360)

    def delete(self, indices):
        chosen = set(self._indices(indices))
        if len(chosen) == self.page_count:
            raise PdfToolError("all_pages_removed")
        self.pages = [page for index, page in enumerate(self.pages) if index not in chosen]

    def render(self, index, edge=180, *, cancel=None):
        """독립 PIL 복사만 반환하고 모든 PDFium 객체는 잠금 안에서 해제한다."""
        self._indices([index])
        if type(edge) is not int or not 32 <= edge <= 1600:
            raise PdfToolError("quality")
        reference = self.pages[index]
        with source_context(self.source), PDFIUM_LOCK:
            check_cancel(cancel)
            document = pdfium.PdfDocument(self._content)
            page = bitmap = None
            try:
                page = document[reference.source_index]
                width, height = page.get_size()
                if width <= 0 or height <= 0:
                    raise PdfToolError("invalid_pdf")
                scale = edge / max(width, height)
                bitmap = page.render(scale=scale, rotation=reference.rotation)
                image = bitmap.to_pil().convert("RGB").copy()
                check_cancel(cancel)
                return image
            finally:
                if bitmap is not None:
                    bitmap.close()
                if page is not None:
                    page.close()
                document.close()

    def preflight_save(self, destination=None, *, selected=None, cancel=None):
        """원본 경로를 다시 읽지 않고 메모리 스냅샷과 실제 결과 위치만 점검한다."""
        check_cancel(cancel)
        if selected is not None:
            self._indices(selected)
        target = Path(destination).resolve() if destination is not None else None
        if target is not None:
            if target.suffix.lower() != ".pdf":
                raise PdfToolError("output_format")
            if target == self.source or target.exists():
                raise PdfToolError("output_exists")
        directory = target.parent if target is not None else self.source.parent
        return [preflight_output(directory, len(self._content) * 4 + 64 * 1024 * 1024, cancel)]

    def save(self, destination=None, *, selected=None, cancel=None, progress=None):
        """현재 순서로 저장한다. 명시 경로 충돌과 원본 덮어쓰기는 거부한다."""
        indices = list(range(self.page_count)) if selected is None else self._indices(selected)
        references = [self.pages[index] for index in indices]
        progress = progress or (lambda done, total, label: None)
        target = Path(destination).resolve() if destination is not None else None
        with source_context(self.source):
            self.preflight_save(target, selected=selected, cancel=cancel)
            directory = target.parent if target is not None else self.source.parent
            with tempfile.TemporaryDirectory(prefix=".flipring-pdf-", dir=directory) as folder:
                produced = Path(folder) / "edited.pdf"
                reader = PdfReader(io.BytesIO(self._content), strict=False)
                writer = PdfWriter()
                try:
                    for number, reference in enumerate(references):
                        check_cancel(cancel)
                        page = writer.add_page(reader.pages[reference.source_index])
                        if reference.rotation:
                            page.rotate(reference.rotation)
                        progress(number + 1, len(references), str(reference.source_index + 1))
                    check_cancel(cancel)
                    with produced.open("wb") as stream:
                        writer.write(stream)
                finally:
                    writer.close()
                check_cancel(cancel)
                if target is None:
                    return publish(produced, self.source, "edited" if selected is None else "extracted", cancel)
                # 배타적 생성 성공 뒤에만 정리 책임을 가진다. 기존 결과는 삭제하지 않는다.
                try:
                    output = target.open("xb")
                except FileExistsError as error:
                    raise PdfToolError("output_exists") from error
                try:
                    with output, produced.open("rb") as source:
                        while block := source.read(1024 * 1024):
                            check_cancel(cancel)
                            output.write(block)
                    check_cancel(cancel)
                    return str(target)
                except BaseException:
                    target.unlink(missing_ok=True)
                    raise
