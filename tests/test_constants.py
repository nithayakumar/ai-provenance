from pathlib import Path
from lib.constants import (
    IMAGE_EXTENSIONS,
    SCHEMA_VERSION,
    TOOL_VERSION,
    PROVENANCE_DIR,
    INDEX_DB,
)


def test_image_extensions_are_lowercase():
    for ext in IMAGE_EXTENSIONS:
        assert ext == ext.lower(), f"{ext!r} is not lowercase"


def test_image_extensions_have_leading_dot():
    for ext in IMAGE_EXTENSIONS:
        assert ext.startswith("."), f"{ext!r} missing leading dot"


def test_common_extensions_present():
    for ext in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        assert ext in IMAGE_EXTENSIONS


def test_schema_version_format():
    parts = SCHEMA_VERSION.split(".")
    assert len(parts) == 2
    assert all(p.isdigit() for p in parts)


def test_tool_version_format():
    parts = TOOL_VERSION.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)


def test_index_db_under_provenance_dir():
    assert str(INDEX_DB).startswith(str(PROVENANCE_DIR))


def test_provenance_dir_is_home_relative():
    assert str(PROVENANCE_DIR).startswith(str(Path.home()))
