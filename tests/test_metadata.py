import pytest
from pathlib import Path
from PIL import Image


def _make_png(path: str, width=100, height=80) -> None:
    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    img.save(path, "PNG")


class TestCollectFileMetadata:
    def test_basic_fields_present(self, tmp_path):
        img_path = tmp_path / "test.png"
        _make_png(str(img_path))

        from lib.metadata import collect_file_metadata
        result = collect_file_metadata(str(img_path))

        assert result["filename"] == "test.png"
        assert result["size_bytes"] > 0
        assert result["mime_type"] == "image/png"
        assert result["sha256"] and len(result["sha256"]) == 64

    def test_sha256_is_deterministic(self, tmp_path):
        img_path = tmp_path / "test.png"
        _make_png(str(img_path))

        from lib.metadata import collect_file_metadata
        r1 = collect_file_metadata(str(img_path))
        r2 = collect_file_metadata(str(img_path))
        assert r1["sha256"] == r2["sha256"]

    def test_sha256_differs_for_different_files(self, tmp_path):
        img1 = tmp_path / "a.png"
        img2 = tmp_path / "b.png"
        _make_png(str(img1), width=100, height=100)
        _make_png(str(img2), width=200, height=200)

        from lib.metadata import collect_file_metadata
        r1 = collect_file_metadata(str(img1))
        r2 = collect_file_metadata(str(img2))
        assert r1["sha256"] != r2["sha256"]

    def test_captured_at_defaults_to_now(self, tmp_path):
        img_path = tmp_path / "t.png"
        _make_png(str(img_path))

        from lib.metadata import collect_file_metadata
        result = collect_file_metadata(str(img_path))
        assert result["captured_at"] is not None
        assert "T" in result["captured_at"]

    def test_captured_at_can_be_overridden(self, tmp_path):
        img_path = tmp_path / "t.png"
        _make_png(str(img_path))

        from lib.metadata import collect_file_metadata
        ts = "2024-01-01T00:00:00+00:00"
        result = collect_file_metadata(str(img_path), captured_at=ts)
        assert result["captured_at"] == ts

    def test_unknown_mime_type_for_unknown_extension(self, tmp_path):
        p = tmp_path / "test.zz99provtest"
        p.write_bytes(b"fake")

        from lib.metadata import collect_file_metadata
        result = collect_file_metadata(str(p))
        assert result["mime_type"] in ("unknown", None, "application/octet-stream")


class TestGetImageDimensions:
    def test_dimensions_extracted(self, tmp_path):
        img_path = tmp_path / "rect.png"
        _make_png(str(img_path), width=320, height=240)

        from lib.metadata import get_image_dimensions
        dims = get_image_dimensions(str(img_path))
        assert dims == {"width": 320, "height": 240, "mode": "RGB"}

    def test_returns_empty_on_nonimage(self, tmp_path):
        p = tmp_path / "not_an_image.txt"
        p.write_text("hello")

        from lib.metadata import get_image_dimensions
        result = get_image_dimensions(str(p))
        assert result == {}


class TestIsImage:
    def test_image_extensions_recognised(self, tmp_path):
        from lib.metadata import is_image
        for ext in [".jpg", ".png", ".webp", ".gif"]:
            p = tmp_path / f"test{ext}"
            p.touch()
            assert is_image(p), f"{ext} should be recognised as image"

    def test_non_image_extensions_rejected(self, tmp_path):
        from lib.metadata import is_image
        for ext in [".txt", ".pdf", ".mp4", ".py"]:
            p = tmp_path / f"test{ext}"
            p.touch()
            assert not is_image(p), f"{ext} should not be recognised as image"

    def test_provenance_sidecar_rejected(self, tmp_path):
        from lib.metadata import is_image
        p = tmp_path / "test.provenance.json"
        p.touch()
        assert not is_image(p)
