import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

import fitz
from docx import Document
from openpyxl import load_workbook
from PIL import Image, ImageOps


@dataclass
class TextPart:
    content: str
    label: str = "document text"


@dataclass
class ImagePart:
    data: bytes
    mime_type: str
    page: int | None = None


@dataclass
class PreparedDocument:
    text_parts: list[TextPart] = field(default_factory=list)
    image_parts: list[ImagePart] = field(default_factory=list)


class DocumentPreprocessor:
    def __init__(self, max_pages: int = 30):
        self.max_pages = max_pages

    def prepare(self, path: Path, mime_type: str) -> PreparedDocument:
        if mime_type.startswith("image/"):
            return self._image(path)
        if mime_type == "application/pdf":
            return self._pdf(path)
        if mime_type in {"text/csv", "application/csv"}:
            return self._csv(path)
        if mime_type in {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
        }:
            return self._word(path)
        if mime_type in {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel",
        }:
            return self._spreadsheet(path)
        raise ValueError("不支持这种文件格式")

    def _image_bytes(self, image: Image.Image) -> bytes:
        output = io.BytesIO()
        normalized = ImageOps.exif_transpose(image).convert("RGB")
        if max(normalized.size) > 3000:
            normalized.thumbnail((3000, 3000))
        # Camera photos encoded as PNG make multi-file model requests needlessly
        # large. A high-quality JPEG keeps small report text legible while
        # substantially reducing upload and inference time. Originals remain
        # untouched in object storage.
        normalized.save(output, format="JPEG", quality=88, optimize=True, progressive=True)
        return output.getvalue()

    def _image(self, path: Path) -> PreparedDocument:
        with Image.open(path) as image:
            data = self._image_bytes(image)
        return PreparedDocument(image_parts=[ImagePart(data=data, mime_type="image/jpeg", page=1)])

    def _pdf(self, path: Path) -> PreparedDocument:
        document = fitz.open(path)
        try:
            if document.page_count > self.max_pages:
                raise ValueError(f"文档超过 {self.max_pages} 页限制")
            images = []
            for number, page in enumerate(document, 1):
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                with Image.open(io.BytesIO(pixmap.tobytes("png"))) as image:
                    data = self._image_bytes(image)
                images.append(ImagePart(data=data, mime_type="image/jpeg", page=number))
            return PreparedDocument(image_parts=images)
        finally:
            document.close()

    def _csv(self, path: Path) -> PreparedDocument:
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("gb18030")
        rows = list(csv.reader(io.StringIO(text)))
        normalized = "\n".join(",".join(cell.strip() for cell in row) for row in rows)
        return PreparedDocument(text_parts=[TextPart(normalized, "CSV cells")])

    def _word(self, path: Path) -> PreparedDocument:
        document = Document(path)
        lines = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
        for table in document.tables:
            for row in table.rows:
                lines.append("\t".join(cell.text.strip() for cell in row.cells))
        images = []
        for relationship in document.part.rels.values():
            if "image" in relationship.reltype:
                blob = relationship.target_part.blob
                with Image.open(io.BytesIO(blob)) as image:
                    images.append(ImagePart(self._image_bytes(image), "image/jpeg"))
        return PreparedDocument(text_parts=[TextPart("\n".join(lines), "Word text")], image_parts=images)

    def _spreadsheet(self, path: Path) -> PreparedDocument:
        workbook = load_workbook(path, read_only=True, data_only=True)
        parts = []
        for sheet in workbook.worksheets:
            lines = []
            for index, row in enumerate(sheet.iter_rows(values_only=True), 1):
                if index > 1000:
                    raise ValueError("单个工作表超过 1000 行限制")
                lines.append("\t".join("" if value is None else str(value) for value in row))
            parts.append(TextPart("\n".join(lines), f"工作表：{sheet.title}"))
        workbook.close()
        return PreparedDocument(text_parts=parts)
