#!/usr/bin/env python3
"""
AI training image provenance collector.

Commands:
  download  <url>   Download an image and capture all provenance data.
  scan      <path>  Process already-downloaded images (file or folder).
  watch     <dir>   Daemon — auto-capture provenance for new images in a folder.

Examples:
  python provenance.py download https://example.com/photo.jpg
  python provenance.py download https://cdn.site.com/img.jpg --source-page https://site.com/post/42
  python provenance.py scan ~/Downloads/training_images/
  python provenance.py watch ~/Downloads/lora_drop/
  python provenance.py watch ~/Downloads/lora_drop/ --csv ~/my_lora_provenance.csv
"""

import argparse
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from lib import metadata, scrapers, storage

DEFAULT_CSV = "provenance_log.csv"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"}


def collect_provenance(
    image_path: str,
    csv_path: str,
    source_url: Optional[str] = None,
    source_page: Optional[str] = None,
    http_meta: Optional[dict] = None,
) -> dict:
    """Core routine: gather all provenance for a local image file and write outputs."""
    now = datetime.now(timezone.utc).isoformat()

    print(f"  Hashing + reading EXIF...")
    file_meta = metadata.collect_file_metadata(image_path, downloaded_at=now)
    dims = metadata.get_image_dimensions(image_path)
    exif = metadata.extract_exif(image_path)

    # Build source block
    source_meta = dict(http_meta) if http_meta else {}
    if source_url:
        source_meta.setdefault("url", source_url)
        source_meta.setdefault("domain", urllib.parse.urlparse(source_url).netloc)
    if source_page:
        source_meta["source_page"] = source_page

    effective_url = source_page or source_url
    if effective_url:
        source_meta["platform"] = scrapers.detect_platform(effective_url)

    # Scrape the source page (skip if URL is a raw image file)
    page_meta = {}
    scrape_target = source_page or (
        source_url
        if source_url and Path(urllib.parse.urlparse(source_url).path).suffix.lower()
        not in IMAGE_EXTENSIONS
        else None
    )
    if scrape_target:
        print(f"  Scraping page metadata from {scrape_target} ...")
        page_meta = scrapers.scrape_page_metadata(scrape_target)

    # Platform-specific enrichment
    platform_specific = {}
    if source_url and "civitai" in source_url:
        platform_specific = scrapers.scrape_civitai(source_url)

    # Build creator + rights from all signals (EXIF > page meta > schema.org > OG)
    creator: dict = {}
    rights: dict = {}

    if exif.get("Artist"):
        creator["author"] = exif["Artist"]
    if exif.get("Copyright"):
        rights["copyright"] = exif["Copyright"]

    if page_meta.get("author"):
        creator.setdefault("author", page_meta["author"])
    if page_meta.get("copyright"):
        rights.setdefault("copyright", page_meta["copyright"])
    if page_meta.get("license_url"):
        rights["license_url"] = page_meta["license_url"]
    if page_meta.get("cc_license"):
        rights.setdefault("license", page_meta["cc_license"])
        rights.setdefault("license_url", page_meta.get("cc_license_url", ""))

    og = page_meta.get("opengraph", {})
    creator.setdefault("platform", og.get("og:site_name", ""))
    for og_key in ("article:author", "og:author"):
        if og.get(og_key):
            creator.setdefault("author", og[og_key])
            break

    for schema in page_meta.get("schema_org", []):
        if not isinstance(schema, dict):
            continue
        author = schema.get("author")
        if author:
            name = author.get("name") if isinstance(author, dict) else str(author)
            creator.setdefault("author", name)
        license_val = schema.get("license")
        if license_val:
            rights.setdefault("license_url", str(license_val))
        ch = schema.get("copyrightHolder")
        if ch:
            holder = ch.get("name") if isinstance(ch, dict) else str(ch)
            rights.setdefault("copyright_holder", holder)
        if schema.get("copyrightYear"):
            rights.setdefault("copyright_year", str(schema["copyrightYear"]))

    provenance = {
        "schema_version": "1.0",
        "file": file_meta,
        "source": source_meta,
        "creator": creator,
        "rights": rights,
        "image": {**dims, "exif": exif},
        "page_metadata": page_meta,
    }
    if platform_specific:
        provenance["platform_specific"] = platform_specific

    sidecar_path = storage.write_json_sidecar(image_path, provenance)
    flat = storage.flatten_for_csv(provenance, sidecar_path)
    storage.append_csv_record(csv_path, flat)

    print(f"  JSON: {sidecar_path}")
    print(f"  CSV:  {csv_path}")
    return provenance


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_download(args):
    url = args.url
    out_dir = Path(args.dir).expanduser() if args.dir else Path.cwd()
    out_dir.mkdir(parents=True, exist_ok=True)

    url_path = urllib.parse.urlparse(url).path
    filename = Path(url_path).name or "image"
    if not Path(filename).suffix:
        filename += ".jpg"
    dest = out_dir / filename
    counter = 1
    while dest.exists():
        stem, suffix = Path(filename).stem, Path(filename).suffix
        dest = out_dir / f"{stem}_{counter}{suffix}"
        counter += 1

    print(f"Downloading: {url}")
    print(f"         -> {dest}")
    http_meta = scrapers.download_image(url, str(dest))
    if args.source_page:
        http_meta["source_page"] = args.source_page

    csv_path = args.csv or str(out_dir / DEFAULT_CSV)
    prov = collect_provenance(
        str(dest),
        csv_path,
        source_url=url,
        source_page=args.source_page,
        http_meta=http_meta,
    )
    print(f"\nDone.  SHA256: {prov['file']['sha256']}")


def cmd_scan(args):
    path = Path(args.path).expanduser()
    csv_path = args.csv or DEFAULT_CSV

    if path.is_file():
        targets = [path]
    elif path.is_dir():
        targets = [
            p for p in sorted(path.rglob("*"))
            if p.suffix.lower() in IMAGE_EXTENSIONS
            and not p.name.endswith(".provenance.json")
        ]
    else:
        print(f"Error: {path} does not exist.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(targets)} image(s) to scan.\n")
    for img in targets:
        print(f"[{targets.index(img)+1}/{len(targets)}] {img.name}")
        url_file = img.with_suffix(".url")
        source_url = source_page = None
        if url_file.exists():
            lines = url_file.read_text(encoding="utf-8").strip().splitlines()
            source_url = lines[0].strip() if lines else None
            source_page = lines[1].strip() if len(lines) > 1 else None
        collect_provenance(str(img), csv_path, source_url=source_url, source_page=source_page)
        print()

    print(f"Done. Processed {len(targets)} image(s).")


def cmd_watch(args):
    from lib.watcher import watch_directory
    watch_dir = str(Path(args.dir).expanduser().resolve())
    csv_path = args.csv or str(Path(watch_dir) / DEFAULT_CSV)
    watch_directory(watch_dir, csv_path, collect_provenance)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="provenance.py",
        description="Automate AI training image provenance collection.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- download ---
    p_dl = sub.add_parser("download", help="Download an image and capture provenance.")
    p_dl.add_argument("url", help="Direct URL of the image to download.")
    p_dl.add_argument("--dir", "-d", metavar="PATH", help="Output directory (default: current dir).")
    p_dl.add_argument(
        "--source-page", "-p", metavar="URL",
        help="URL of the page where the image was found (enables richer metadata scraping).",
    )
    p_dl.add_argument("--csv", metavar="PATH", help=f"CSV log path (default: <dir>/{DEFAULT_CSV}).")

    # --- scan ---
    p_sc = sub.add_parser("scan", help="Capture provenance for already-downloaded image(s).")
    p_sc.add_argument("path", help="Image file or folder to scan.")
    p_sc.add_argument("--csv", metavar="PATH", help=f"CSV log path (default: ./{DEFAULT_CSV}).")

    # --- watch ---
    p_wt = sub.add_parser("watch", help="Watch a folder; auto-capture provenance for new images.")
    p_wt.add_argument("dir", help="Directory to watch.")
    p_wt.add_argument("--csv", metavar="PATH", help=f"CSV log path (default: <dir>/{DEFAULT_CSV}).")

    args = parser.parse_args()
    {"download": cmd_download, "scan": cmd_scan, "watch": cmd_watch}[args.command](args)


if __name__ == "__main__":
    main()
