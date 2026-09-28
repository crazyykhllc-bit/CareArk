from pathlib import Path

from PIL import Image

from app.services.preprocess import DocumentPreprocessor


def test_csv_keeps_cell_values_without_visual_ocr():
    result = DocumentPreprocessor(max_pages=30).prepare(
        Path("tests/fixtures/sample.csv"), "text/csv"
    )

    assert result.text_parts[0].content == "项目,结果,单位\nTSH,0.01,mIU/L"
    assert result.image_parts == []


def test_image_becomes_visual_input(tmp_path):
    image_path = tmp_path / "report.png"
    Image.new("RGB", (100, 80), "white").save(image_path)

    result = DocumentPreprocessor(max_pages=30).prepare(image_path, "image/png")

    assert len(result.image_parts) == 1
    assert result.image_parts[0].mime_type == "image/jpeg"
    assert result.image_parts[0].data.startswith(b"\xff\xd8")
    assert result.text_parts == []


def test_photo_input_is_compacted_for_batch_model_requests(tmp_path):
    image_path = tmp_path / "photo.png"
    image = Image.effect_noise((1086, 1448), 80).convert("RGB")
    image.save(image_path, format="PNG")
    original_size = image_path.stat().st_size

    result = DocumentPreprocessor(max_pages=30).prepare(image_path, "image/png")

    assert len(result.image_parts[0].data) < original_size / 2


def test_unsupported_format_has_clear_error(tmp_path):
    source = tmp_path / "binary.exe"
    source.write_bytes(b"unknown")

    try:
        DocumentPreprocessor(max_pages=30).prepare(source, "application/octet-stream")
    except ValueError as error:
        assert str(error) == "不支持这种文件格式"
    else:
        raise AssertionError("unsupported format should fail")
