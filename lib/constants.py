from pathlib import Path

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".bmp", ".tiff", ".tif", ".avif", ".heic", ".heif",
}

SCHEMA_VERSION = "2.0"
TOOL_VERSION = "0.2.0"

PROVENANCE_DIR = Path.home() / ".provenance"
INDEX_DB = PROVENANCE_DIR / "index.sqlite"
THUMBNAILS_DIR = PROVENANCE_DIR / "thumbnails"
CACHE_DIR = PROVENANCE_DIR / "cache"
