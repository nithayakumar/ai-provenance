import csv
import json
from pathlib import Path

CSV_FIELDNAMES = [
    "downloaded_at",
    "filename",
    "sha256",
    "size_bytes",
    "mime_type",
    "width",
    "height",
    "source_url",
    "source_page",
    "platform",
    "domain",
    "author",
    "license",
    "license_url",
    "copyright",
    "filepath",
    "sidecar_path",
]


def write_json_sidecar(image_path: str, provenance: dict) -> str:
    path = Path(image_path)
    sidecar = path.with_name(path.stem + ".provenance.json")
    with open(sidecar, "w", encoding="utf-8") as f:
        json.dump(provenance, f, indent=2, ensure_ascii=False, default=str)
    return str(sidecar)


def append_csv_record(csv_path: str, record: dict) -> None:
    path = Path(csv_path)
    write_header = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow(record)


def flatten_for_csv(provenance: dict, sidecar_path: str) -> dict:
    file_meta = provenance.get("file", {})
    source = provenance.get("source", {})
    creator = provenance.get("creator", {})
    rights = provenance.get("rights", {})
    image_info = provenance.get("image", {})
    return {
        "downloaded_at": file_meta.get("downloaded_at", ""),
        "filename": file_meta.get("filename", ""),
        "sha256": file_meta.get("sha256", ""),
        "size_bytes": file_meta.get("size_bytes", ""),
        "mime_type": file_meta.get("mime_type", ""),
        "width": image_info.get("width", ""),
        "height": image_info.get("height", ""),
        "source_url": source.get("url", ""),
        "source_page": source.get("source_page", ""),
        "platform": source.get("platform", ""),
        "domain": source.get("domain", ""),
        "author": creator.get("author", ""),
        "license": rights.get("license", ""),
        "license_url": rights.get("license_url", ""),
        "copyright": rights.get("copyright", ""),
        "filepath": file_meta.get("filepath", ""),
        "sidecar_path": sidecar_path,
    }
