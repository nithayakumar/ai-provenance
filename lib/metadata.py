import hashlib
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PIL import Image
from PIL.ExifTags import TAGS


def sha256_of_file(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_exif(filepath: str) -> dict:
    try:
        img = Image.open(filepath)
        raw = img._getexif()
        if not raw:
            return {}
        return {
            TAGS.get(tag_id, str(tag_id)): str(value)
            for tag_id, value in raw.items()
            if tag_id in TAGS
        }
    except Exception:
        return {}


def get_image_dimensions(filepath: str) -> dict:
    try:
        img = Image.open(filepath)
        return {"width": img.width, "height": img.height, "mode": img.mode}
    except Exception:
        return {}


def collect_file_metadata(filepath: str, downloaded_at: Optional[str] = None) -> dict:
    path = Path(filepath)
    mime, _ = mimetypes.guess_type(str(path))
    return {
        "filename": path.name,
        "filepath": str(path.resolve()),
        "sha256": sha256_of_file(filepath),
        "size_bytes": path.stat().st_size,
        "mime_type": mime or "unknown",
        "downloaded_at": downloaded_at or datetime.now(timezone.utc).isoformat(),
    }
