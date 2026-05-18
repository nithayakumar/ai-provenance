#!/usr/bin/env python3
"""
AI training image provenance collector.

Commands:
  download  <url>   Download an image and capture all provenance data.
  scan      <path>  Process already-downloaded images (file or folder).
  watch     <dir>   Daemon — auto-capture provenance for new images in a folder.
  enrich    <path>  Back-fill source URLs from Chrome/Edge browser download history.
  history           Show recent image downloads found in browser history.

Examples:
  python provenance.py download https://example.com/photo.jpg
  python provenance.py download https://cdn.site.com/img.jpg --source-page https://site.com/post/42
  python provenance.py scan ~/Downloads/training_images/
  python provenance.py watch ~/Downloads/lora_drop/
  python provenance.py enrich ~/Downloads/lora_drop/
  python provenance.py history
"""

import argparse
import json
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from lib import metadata, scrapers, storage

DEFAULT_CSV = "provenance_log.csv"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif"}


def _lookup_browser_history(image_path: str) -> tuple[Optional[str], Optional[str]]:
    """
    Check Chrome/Edge download history for a source URL matching this file.
    Returns (download_url, original_source_page).
    """
    try:
        from lib.browser_history import find_download_record
    except ImportError:
        return None, None

    path = Path(image_path)
    mtime = path.stat().st_mtime
    record = find_download_record(path.name, file_mtime=mtime)
    if not record:
        return None, None

    source_url = record.get("download_url")
    source_page = record.get("original_source_url") or record.get("tab_url") or record.get("referrer")
    # Don't return raw Google search pages as the source page — not useful
    if source_page and "google.com/search" in source_page and "imgurl" not in source_page:
        source_page = None
    return source_url, source_page


def collect_provenance(
    image_path: str,
    csv_path: str,
    source_url: Optional[str] = None,
    source_page: Optional[str] = None,
    http_meta: Optional[dict] = None,
    use_browser_history: bool = True,
) -> dict:
    """Gather all provenance for a local image file and write JSON + CSV outputs."""
    now = datetime.now(timezone.utc).isoformat()

    print(f"  Hashing + reading EXIF...")
    file_meta = metadata.collect_file_metadata(image_path, downloaded_at=now)
    dims = metadata.get_image_dimensions(image_path)
    exif = metadata.extract_exif(image_path)

    # Auto-lookup browser history when no URL was supplied
    browser_record = None
    if use_browser_history and not source_url:
        hist_url, hist_page = _lookup_browser_history(image_path)
        if hist_url:
            print(f"  Found in browser history: {hist_url}")
            source_url = hist_url
            source_page = source_page or hist_page
            browser_record = {"matched": True, "download_url": hist_url, "source_page": hist_page}
        else:
            print(f"  Not found in browser history (Chrome may be open — close it and retry, or use 'enrich')")

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

    if browser_record:
        source_meta["browser_history"] = browser_record

    # Scrape the source page (skip if URL points directly to an image file)
    page_meta = {}
    scrape_target = source_page or (
        source_url
        if source_url
        and Path(urllib.parse.urlparse(source_url).path).suffix.lower()
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
        use_browser_history=False,  # URL already known
    )
    print(f"\nDone.  SHA256: {prov['file']['sha256']}")


def cmd_scan(args):
    path = Path(args.path).expanduser()
    csv_path = args.csv or DEFAULT_CSV
    no_history = getattr(args, "no_history", False)

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
    for i, img in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] {img.name}")
        # Companion .url file takes priority over browser history lookup
        url_file = img.with_suffix(".url")
        source_url = source_page = None
        if url_file.exists():
            lines = url_file.read_text(encoding="utf-8").strip().splitlines()
            source_url = lines[0].strip() if lines else None
            source_page = lines[1].strip() if len(lines) > 1 else None
        collect_provenance(
            str(img), csv_path,
            source_url=source_url, source_page=source_page,
            use_browser_history=not no_history and source_url is None,
        )
        print()

    print(f"Done. Processed {len(targets)} image(s).")


def cmd_enrich(args):
    """
    Back-fill source URLs into existing .provenance.json sidecars using
    Chrome/Edge download history.  Only updates records that have no source URL.
    """
    from lib.browser_history import find_download_record

    path = Path(args.path).expanduser()
    sidecars = (
        [path] if path.name.endswith(".provenance.json")
        else list(path.rglob("*.provenance.json"))
    )
    if not sidecars:
        print("No .provenance.json files found.")
        return

    csv_path = args.csv or DEFAULT_CSV
    updated = skipped = no_match = 0

    for sidecar in sorted(sidecars):
        with open(sidecar, encoding="utf-8") as f:
            prov = json.load(f)

        # Skip if source URL already populated
        if prov.get("source", {}).get("url"):
            skipped += 1
            continue

        filename = prov.get("file", {}).get("filename", "")
        filepath = prov.get("file", {}).get("filepath", "")
        mtime = Path(filepath).stat().st_mtime if filepath and Path(filepath).exists() else None

        record = find_download_record(filename, file_mtime=mtime)
        if not record:
            print(f"  no history match: {filename}")
            no_match += 1
            continue

        source_url = record["download_url"]
        source_page = (
            record.get("original_source_url")
            or record.get("tab_url")
            or record.get("referrer")
        )
        print(f"  matched: {filename}  ->  {source_url}")

        prov["source"]["url"] = source_url
        prov["source"]["domain"] = urllib.parse.urlparse(source_url).netloc
        prov["source"]["platform"] = scrapers.detect_platform(source_url)
        if source_page:
            prov["source"].setdefault("source_page", source_page)
        prov["source"]["browser_history"] = record

        # Scrape the source page for richer metadata if it's not a raw image URL
        scrape_target = source_page or (
            source_url
            if Path(urllib.parse.urlparse(source_url).path).suffix.lower()
            not in IMAGE_EXTENSIONS
            else None
        )
        if scrape_target and not args.no_scrape:
            print(f"    scraping {scrape_target} ...")
            prov["page_metadata"] = scrapers.scrape_page_metadata(scrape_target)

        with open(sidecar, "w", encoding="utf-8") as f:
            json.dump(prov, f, indent=2, ensure_ascii=False, default=str)

        # Re-append to CSV with enriched data
        flat = storage.flatten_for_csv(prov, str(sidecar))
        storage.append_csv_record(csv_path, flat)
        updated += 1

    print(f"\nEnrich complete: {updated} updated, {skipped} already had URLs, {no_match} no history match.")


def cmd_history(args):
    """Print recent image downloads found in Chrome/Edge history."""
    from lib.browser_history import list_recent_image_downloads
    hist_path = getattr(args, "db", None)
    rows = list_recent_image_downloads(history_path=hist_path, limit=args.limit)
    if not rows:
        print("No Chrome/Edge history found (or Chrome is open — close it first).")
        return
    print(f"{'Filename':<40} {'Time (UTC)':<26} {'URL'}")
    print("-" * 100)
    for r in rows:
        ts = (r["end_time_utc"] or "")[:19]
        url = (r["download_url"] or "")[:60]
        print(f"{r['filename']:<40} {ts:<26} {url}")


def cmd_watch(args):
    from lib.watcher import watch_directory
    watch_dir = str(Path(args.dir).expanduser().resolve())
    csv_path = args.csv or str(Path(watch_dir) / DEFAULT_CSV)
    no_history = getattr(args, "no_history", False)

    def process(image_path, csv, source_url=None, source_page=None):
        collect_provenance(
            image_path, csv,
            source_url=source_url, source_page=source_page,
            use_browser_history=not no_history and source_url is None,
        )

    watch_directory(watch_dir, csv_path, process)


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
    p_sc.add_argument("--no-history", action="store_true", help="Skip browser history lookup.")

    # --- watch ---
    p_wt = sub.add_parser("watch", help="Watch a folder; auto-capture provenance for new images.")
    p_wt.add_argument("dir", help="Directory to watch.")
    p_wt.add_argument("--csv", metavar="PATH", help=f"CSV log path (default: <dir>/{DEFAULT_CSV}).")
    p_wt.add_argument("--no-history", action="store_true", help="Skip browser history lookup.")

    # --- enrich ---
    p_en = sub.add_parser(
        "enrich",
        help="Back-fill source URLs from Chrome/Edge download history into existing provenance records.",
    )
    p_en.add_argument("path", help="Folder (or single .provenance.json file) to enrich.")
    p_en.add_argument("--csv", metavar="PATH", help=f"CSV log path for updated records.")
    p_en.add_argument("--no-scrape", action="store_true", help="Skip page scraping after URL lookup.")

    # --- history ---
    p_hi = sub.add_parser("history", help="Show recent image downloads from Chrome/Edge history.")
    p_hi.add_argument("--limit", type=int, default=50, help="Number of records to show (default: 50).")
    p_hi.add_argument("--db", metavar="PATH", help="Path to Chrome History SQLite file (auto-detected if omitted).")

    args = parser.parse_args()
    {
        "download": cmd_download,
        "scan": cmd_scan,
        "watch": cmd_watch,
        "enrich": cmd_enrich,
        "history": cmd_history,
    }[args.command](args)


if __name__ == "__main__":
    main()
