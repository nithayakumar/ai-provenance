#!/usr/bin/env python3
"""
AI training image provenance collector.

Commands:
  download <url>     Download an image and capture full provenance.
  scan <path>        Process already-downloaded images (file or folder).
  watch <dir>        Daemon — capture provenance for new images in a folder.
  enrich <path>      Back-fill missing data from browser history, APIs, Wayback.
  history            Show recent image downloads from Chrome/Edge history.
  audit [path]       Gap report — files missing key provenance fields.
  migrate <path>     Upgrade v1.0 .provenance.json sidecars to v2.0.
  export [csv_path]  Export full collection to CSV.
  report [out.html]  Generate a self-contained HTML provenance report.

Examples:
  python provenance.py download https://civitai.com/images/123456
  python provenance.py scan ~/Downloads/lora-dataset/ --skip-existing
  python provenance.py watch ~/Downloads/lora-drop/
  python provenance.py enrich ~/Downloads/lora-dataset/
  python provenance.py audit ~/Downloads/lora-dataset/
  python provenance.py export ~/provenance_export.csv
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
from lib.browser_history import find_download_record
from lib.c2pa_reader import read_c2pa
from lib.completeness import compute as compute_completeness
from lib.constants import IMAGE_EXTENSIONS, SCHEMA_VERSION, TOOL_VERSION
from lib.embedded_metadata import read_all_embedded, extract_ai_training_signals
from lib.license_spdx import to_spdx
from lib.opt_out import check_all as check_opt_out

DEFAULT_CSV = "provenance_log.csv"


# ---------------------------------------------------------------------------
# Core pipeline — split into focused steps
# ---------------------------------------------------------------------------

def gather_signals(
    image_path: str,
    source_url: Optional[str] = None,
    source_page: Optional[str] = None,
    http_meta: Optional[dict] = None,
    use_browser_history: bool = True,
) -> dict:
    """Collect every raw signal for an image. No writes."""
    path = Path(image_path)
    now = datetime.now(timezone.utc).isoformat()

    # File basics
    file_meta = metadata.collect_file_metadata(image_path, captured_at=now)
    dims = metadata.get_image_dimensions(image_path)

    # Browser history lookup
    browser_record = None
    if use_browser_history and not source_url:
        mtime = path.stat().st_mtime
        rec = find_download_record(path.name, file_mtime=mtime)
        if rec:
            source_url  = rec["download_url"]
            source_page = source_page or rec.get("original_source_url") or rec.get("tab_url")
            browser_record = rec
            # Filter bare Google search pages — not useful as a source page
            if source_page and "google.com/search" in source_page and "imgurl" not in source_page:
                source_page = None

    # Embedded metadata (EXIF, XMP, IPTC, C2PA)
    embedded = read_all_embedded(image_path)
    c2pa     = read_c2pa(image_path)
    embedded_signals = extract_ai_training_signals(embedded)

    # Source page scrape
    page_meta = {}
    scrape_target = source_page or (
        source_url
        if source_url
        and Path(urllib.parse.urlparse(source_url).path).suffix.lower() not in IMAGE_EXTENSIONS
        else None
    )
    if scrape_target:
        page_meta = scrapers.scrape_page_metadata(scrape_target)

    # Platform-specific enrichment (CivitAI only in Phase 1)
    platform_extra = {}
    if source_url and "civitai" in source_url:
        platform_extra = scrapers.scrape_civitai(source_url)

    return {
        "now":              now,
        "file_meta":        file_meta,
        "dims":             dims,
        "source_url":       source_url,
        "source_page":      source_page,
        "http_meta":        http_meta or {},
        "browser_record":   browser_record,
        "embedded":         embedded,
        "embedded_signals": embedded_signals,
        "c2pa":             c2pa,
        "page_meta":        page_meta,
        "platform_extra":   platform_extra,
    }


def resolve_canonical(signals: dict, image_path: str = "") -> dict:
    """Build the canonical provenance record from raw signals."""
    file_meta = signals["file_meta"]
    dims      = signals["dims"]
    esig      = signals["embedded_signals"]
    c2pa      = signals["c2pa"]
    pg        = signals["page_meta"]
    source_url  = signals["source_url"]
    source_page = signals["source_page"]
    http_meta   = signals["http_meta"]

    # --- source ---
    source: dict = {}
    if source_url and not source_url.startswith("data:"):
        source["url"]      = source_url
        source["domain"]   = urllib.parse.urlparse(source_url).netloc
        source["platform"] = scrapers.detect_platform(source_url)
    if source_page:
        source["page_url"] = source_page
        source.setdefault("platform", scrapers.detect_platform(source_page))
    if signals["browser_record"]:
        source["via"] = "browser"
    elif http_meta.get("url"):
        source["via"] = "download"
    else:
        source["via"] = "scan"
    if signals["platform_extra"]:
        source["platform_data"] = signals["platform_extra"]
    # tdm-reservation from HTTP response headers
    tdm = http_meta.get("response_headers", {}).get("tdm-reservation")

    # --- creator ---
    creator: dict = {}
    author = esig.get("author")
    if not author:
        # Fallback: Schema.org author
        for schema in pg.get("schema_org", []):
            if not isinstance(schema, dict):
                continue
            a = schema.get("author")
            if a:
                author = a.get("name") if isinstance(a, dict) else str(a)
                break
    if not author:
        og = pg.get("opengraph", {})
        author = og.get("article:author") or og.get("og:author")
    if author:
        creator["name"] = author
    if not author and pg.get("author"):
        creator["name"] = pg["author"]

    # --- rights: license ---
    license_url  = esig.get("license_url") or pg.get("license_url") or pg.get("cc_license_url")
    license_text = pg.get("cc_license")
    if not license_text:
        for schema in pg.get("schema_org", []):
            if isinstance(schema, dict) and schema.get("license"):
                license_url = license_url or str(schema["license"])
    license_spdx = to_spdx(license_text=license_text, license_url=license_url)

    copyright_ = (
        esig.get("copyright")
        or pg.get("copyright")
        or signals["embedded"].get("exif", {}).get("Copyright")
    )

    # --- rights: AI training opt-out ---
    opt_out_result = check_opt_out(
        url=source_url,
        iptc_data_mining=signals["embedded"].get("xmp", {}).get("plus_data_mining"),
        c2pa_training_opt_out=c2pa.get("training_opt_out"),
    )

    rights: dict = {}
    if license_spdx:
        rights["license_spdx"] = license_spdx
    if license_url:
        rights["license_url"] = license_url
    if copyright_:
        rights["copyright"] = copyright_
    rights["ai_training"] = opt_out_result

    # --- AI generation status ---
    is_ai_generated = c2pa.get("ai_generated")
    ai_source = "c2pa" if c2pa["manifest_present"] else None
    if is_ai_generated is None and esig.get("is_ai_generated") is not None:
        is_ai_generated = esig["is_ai_generated"]
        ai_source = "iptc"
    ai: dict = {"is_ai_generated": is_ai_generated, "source": ai_source}
    if c2pa.get("creator_tool"):
        ai["tool"] = c2pa["creator_tool"]
    if esig.get("ai_system"):
        ai.setdefault("tool", esig["ai_system"])
    if esig.get("ai_prompt"):
        ai["prompt"] = esig["ai_prompt"]

    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version":   TOOL_VERSION,
        "captured_at":    signals["now"],
        "downloaded_at":  file_meta.get("downloaded_at", signals["now"]),
        "file": {
            "filename":   file_meta["filename"],
            "filepath":   str(Path(image_path).resolve()),
            "sha256":     file_meta["sha256"],
            "size_bytes": file_meta["size_bytes"],
            "mime_type":  file_meta["mime_type"],
        },
        "image":   {k: v for k, v in dims.items() if v is not None},
        "source":  source,
        "creator": creator,
        "rights":  rights,
        "ai":      ai,
        "c2pa":    {k: v for k, v in c2pa.items() if v not in (None, [], False)},
    }


def collect_provenance(
    image_path: str,
    csv_path: str,
    source_url: Optional[str] = None,
    source_page: Optional[str] = None,
    http_meta: Optional[dict] = None,
    use_browser_history: bool = True,
    dry_run: bool = False,
) -> dict:
    """Full pipeline: gather → resolve → enrich → score → persist."""
    from lib.enrichers import enrich as api_enrich
    signals  = gather_signals(image_path, source_url, source_page, http_meta, use_browser_history)
    prov     = resolve_canonical(signals, image_path)
    prov     = api_enrich(prov)          # Wikimedia, Unsplash, Pexels (if API keys set)
    prov["completeness"] = compute_completeness(prov)

    score    = prov["completeness"]["score"]
    src      = prov["source"].get("url", "")
    ai_flag  = prov["ai"].get("is_ai_generated")
    opt_flag = prov["rights"]["ai_training"].get("opt_out")

    src_display = src[:60] if src else "—  (run enrich to back-fill)"
    ai_display  = "yes" if ai_flag else "no" if ai_flag is False else "?"
    opt_display = "yes" if opt_flag else "no" if opt_flag is False else "?"
    bar         = "█" * int(score * 10) + "░" * (10 - int(score * 10))
    print(f"  [{bar}] {score:.0%}  url={'✓' if src else '✗'}  "
          f"ai={ai_display}  opt_out={opt_display}  {src_display}")

    if not dry_run:
        sidecar = storage.persist(image_path, prov)
        print(f"  -> {sidecar}")
    else:
        print("  [dry-run — nothing written]")
    return prov


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_download(args):
    url     = args.url
    out_dir = Path(args.dir).expanduser() if args.dir else Path.cwd()
    out_dir.mkdir(parents=True, exist_ok=True)

    filename = Path(urllib.parse.urlparse(url).path).name or "image"
    if not Path(filename).suffix:
        filename += ".jpg"
    dest = out_dir / filename
    counter = 1
    while dest.exists():
        stem, suf = Path(filename).stem, Path(filename).suffix
        dest = out_dir / f"{stem}_{counter}{suf}"
        counter += 1

    print(f"Downloading: {url}\n      -> {dest}")
    http_meta = scrapers.download_image(url, str(dest))

    csv_path = args.csv or str(out_dir / DEFAULT_CSV)
    prov = collect_provenance(
        str(dest), csv_path,
        source_url=url, source_page=getattr(args, "source_page", None),
        http_meta=http_meta, use_browser_history=False,
        dry_run=getattr(args, "dry_run", False),
    )
    print(f"\nDone.  SHA256: {prov['file']['sha256']}")


def _chrome_is_running() -> bool:
    import subprocess
    try:
        out = subprocess.run(["pgrep", "-x", "Google Chrome"], capture_output=True)
        return out.returncode == 0
    except Exception:
        return False


def cmd_scan(args):
    path          = Path(args.path).expanduser()
    csv_path      = args.csv or DEFAULT_CSV
    skip_existing = getattr(args, "skip_existing", False)
    force         = getattr(args, "force", False)
    dry_run       = getattr(args, "dry_run", False)
    no_history    = getattr(args, "no_history", False)

    if path.is_file():
        targets = [path] if metadata.is_image(path) else []
    elif path.is_dir():
        targets = sorted(p for p in path.rglob("*") if metadata.is_image(p))
    else:
        print(f"Error: {path} not found.", file=sys.stderr); sys.exit(1)

    chrome_open = not no_history and _chrome_is_running()
    if chrome_open:
        print("⚠  Chrome is running — browser history is locked.")
        print("   Source URLs will be missing. Close Chrome and run:")
        print(f"   python provenance.py enrich {path}\n")

    print(f"Scanning {len(targets)} image(s)...\n")
    skipped = no_url = 0
    for i, img in enumerate(targets, 1):
        existing = storage.read_sidecar(str(img))
        if skip_existing and not force and existing and existing.get("schema_version") == SCHEMA_VERSION:
            skipped += 1
            continue
        print(f"[{i}/{len(targets)}] {img.name}")
        url_file = img.with_suffix(".url")
        src_url = src_page = None
        if url_file.exists():
            lines = url_file.read_text(encoding="utf-8").strip().splitlines()
            src_url  = lines[0].strip() if lines else None
            src_page = lines[1].strip() if len(lines) > 1 else None
        prov = collect_provenance(
            str(img), csv_path,
            source_url=src_url, source_page=src_page,
            use_browser_history=not no_history and src_url is None,
            dry_run=dry_run,
        )
        if not prov.get("source", {}).get("url"):
            no_url += 1

    processed = len(targets) - skipped
    print(f"\n{'─'*50}")
    print(f"  Scanned:          {processed}")
    print(f"  Skipped:          {skipped}")
    print(f"  Missing source URL: {no_url}/{processed}")
    if no_url and not dry_run:
        action = f"python provenance.py enrich {path}"
        if chrome_open:
            print(f"\n  → Close Chrome, then run:  {action}")
        else:
            print(f"\n  → Run to back-fill URLs:   {action}")
    print(f"  → View results:    python provenance.py report")


def cmd_watch(args):
    from lib.watcher import watch_directory
    watch_dir = str(Path(args.dir).expanduser().resolve())
    csv_path  = args.csv or str(Path(watch_dir) / DEFAULT_CSV)
    no_history = getattr(args, "no_history", False)

    def process(image_path, csv, source_url=None, source_page=None):
        collect_provenance(image_path, csv, source_url=source_url, source_page=source_page,
                           use_browser_history=not no_history and source_url is None)
    watch_directory(watch_dir, csv_path, process)


def cmd_enrich(args):
    path    = Path(args.path).expanduser()
    force   = getattr(args, "force", False)
    dry_run = getattr(args, "dry_run", False)

    if _chrome_is_running():
        print("⚠  Chrome is running — history file is locked. Close Chrome and try again.")
        sys.exit(1)

    sidecars = [path] if path.name.endswith(".provenance.json") \
        else sorted(path.rglob("*.provenance.json"))
    if not sidecars:
        print("No .provenance.json files found."); return

    updated = skipped = no_match = 0
    for sidecar in sidecars:
        try:
            prov = json.loads(sidecar.read_text(encoding="utf-8"))
        except Exception:
            continue

        already_has_url = bool(prov.get("source", {}).get("url"))
        if already_has_url and not force:
            skipped += 1; continue

        filename = prov.get("file", {}).get("filename", "")
        filepath = prov.get("file", {}).get("filepath") or str(sidecar.parent / filename)
        mtime = Path(filepath).stat().st_mtime if filepath and Path(filepath).exists() else None

        rec = find_download_record(filename, file_mtime=mtime)
        if not rec:
            print(f"  no match: {filename}"); no_match += 1; continue

        source_url  = rec["download_url"]
        source_page = rec.get("original_source_url") or rec.get("tab_url") or rec.get("referrer")
        print(f"  matched: {filename} -> {source_url}")

        prov.setdefault("source", {})
        prov["source"]["url"]      = source_url
        prov["source"]["domain"]   = urllib.parse.urlparse(source_url).netloc
        prov["source"]["platform"] = scrapers.detect_platform(source_url)
        prov["source"]["via"]      = "browser"
        if source_page:
            prov["source"].setdefault("page_url", source_page)
        prov["source"]["browser_history"] = rec

        if not getattr(args, "no_scrape", False):
            scrape_target = source_page or (
                source_url if Path(urllib.parse.urlparse(source_url).path).suffix.lower()
                not in IMAGE_EXTENSIONS else None
            )
            if scrape_target:
                print(f"    scraping {scrape_target}")
                pg = scrapers.scrape_page_metadata(scrape_target)
                # Re-resolve license from scraped page
                lurl = pg.get("license_url") or pg.get("cc_license_url")
                ltext = pg.get("cc_license")
                spdx = to_spdx(license_text=ltext, license_url=lurl)
                if spdx:
                    prov.setdefault("rights", {})["license_spdx"] = spdx
                if lurl:
                    prov.setdefault("rights", {})["license_url"] = lurl

        # Platform API enrichment (Unsplash, Pexels) + optional Wayback + Spawning
        use_wayback  = getattr(args, "wayback",  False)
        use_spawning = getattr(args, "spawning", False)
        if use_wayback or use_spawning or _platform_apis_configured():
            from lib.enrichers import enrich as api_enrich
            prov = api_enrich(prov, wayback=use_wayback, spawning=use_spawning)

        prov["completeness"] = compute_completeness(prov)
        if not dry_run:
            sidecar.write_text(json.dumps(prov, indent=2, ensure_ascii=False, default=str),
                               encoding="utf-8")
            storage.upsert_asset(prov, str(sidecar))
        updated += 1

    print(f"\nEnrich done: {updated} updated, {skipped} skipped, {no_match} no history match.")


def cmd_history(args):
    from lib.browser_history import list_recent_image_downloads, _default_history_paths
    paths = _default_history_paths()
    if not paths:
        print("No Chrome/Edge history files found on this machine.")
        print("\nExpected locations:")
        print("  ~/Library/Application Support/Google/Chrome/<profile>/History")
        print("  ~/Library/Application Support/Microsoft Edge/<profile>/History")
        print("\nFix: grant Full Disk Access to Terminal in")
        print("  System Settings → Privacy & Security → Full Disk Access")
        return

    print(f"Found {len(paths)} history file(s):")
    for p in paths:
        print(f"  {p}")
    print()

    rows = list_recent_image_downloads(
        history_path=getattr(args, "db", None),
        limit=getattr(args, "limit", 50),
    )
    if not rows:
        print("History files found but no image downloads recorded.")
        print("Chrome may still be running, or no images have been downloaded recently.")
        return
    print(f"{'Filename':<40} {'Time (UTC)':<22} {'URL'}")
    print("-" * 100)
    for r in rows:
        ts  = (r["end_time_utc"] or "")[:19]
        url = (r["download_url"] or "")[:58]
        print(f"{r['filename']:<40} {ts:<22} {url}")


def cmd_audit(args):
    gaps = storage.audit_gaps()
    print("=== Provenance Audit ===")
    print(f"  Total assets:         {gaps['total']}")
    print(f"  Avg completeness:     {gaps['avg_completeness']:.0%}")
    print(f"  Missing source URL:   {gaps['missing_source_url']}")
    print(f"  Missing license:      {gaps['missing_license']}")
    print(f"  AI status unknown:    {gaps['missing_ai_status']}")
    print(f"  Training opt-out:     {gaps['opted_out']}")
    if hasattr(args, "path") and args.path:
        path = Path(args.path).expanduser()
        rows = storage.query_assets(missing="source_url", limit=20)
        if rows:
            print(f"\nFirst {len(rows)} assets missing source URL:")
            for p in rows:
                print(f"  {p.get('file', {}).get('filename', '?')}")


def cmd_migrate(args):
    path = Path(args.path).expanduser()
    sidecars = sorted(path.rglob("*.provenance.json"))
    if not sidecars:
        print("No .provenance.json files found."); return
    migrated = skipped = 0
    for sidecar in sidecars:
        try:
            prov = json.loads(sidecar.read_text(encoding="utf-8"))
        except Exception:
            continue
        if prov.get("schema_version") == SCHEMA_VERSION:
            skipped += 1; continue

        # Back up original
        backup = sidecar.with_suffix(".json.v1backup")
        if not backup.exists():
            backup.write_bytes(sidecar.read_bytes())

        # Migrate: rename keys
        new_prov: dict = {
            "schema_version": SCHEMA_VERSION,
            "tool_version":   TOOL_VERSION,
            "captured_at":    prov.get("file", {}).get("downloaded_at", ""),
            "downloaded_at":  prov.get("file", {}).get("downloaded_at", ""),
            "file": {
                "filename":  prov.get("file", {}).get("filename", ""),
                "sha256":    prov.get("file", {}).get("sha256", ""),
                "size_bytes": prov.get("file", {}).get("size_bytes", 0),
                "mime_type": prov.get("file", {}).get("mime_type", ""),
                "filepath":  prov.get("file", {}).get("filepath"),
            },
            "image":  prov.get("image", {}),
            "source": {
                "url":      prov.get("source", {}).get("url"),
                "page_url": prov.get("source", {}).get("source_page"),
                "platform": prov.get("source", {}).get("platform"),
                "domain":   prov.get("source", {}).get("domain"),
                "via":      "scan",
            },
            "creator": {"name": prov.get("creator", {}).get("author")},
            "rights": {
                "license_spdx": to_spdx(
                    license_text=prov.get("rights", {}).get("license"),
                    license_url=prov.get("rights", {}).get("license_url"),
                ),
                "license_url":  prov.get("rights", {}).get("license_url"),
                "copyright":    prov.get("rights", {}).get("copyright"),
                "ai_training":  {"opt_out": None, "signals": {}},
            },
            "ai": {"is_ai_generated": None, "source": None},
            "c2pa": {"manifest_present": False},
        }
        new_prov["completeness"] = compute_completeness(new_prov)

        if not getattr(args, "dry_run", False):
            sidecar.write_text(json.dumps(new_prov, indent=2, ensure_ascii=False, default=str),
                               encoding="utf-8")
            storage.upsert_asset(new_prov, str(sidecar))
        migrated += 1
        print(f"  migrated: {sidecar.name}")

    print(f"\nMigrate done: {migrated} migrated, {skipped} already v2.0.")


def cmd_export(args):
    csv_path = getattr(args, "csv_path", None) or DEFAULT_CSV
    count = storage.export_csv(csv_path)
    print(f"Exported {count} records -> {csv_path}")


def cmd_report(args):
    from lib.report import generate
    out = getattr(args, "output", None) or "provenance_report.html"
    limit = getattr(args, "limit", 5000)
    count = generate(out, limit=limit)
    print(f"Report: {count} assets -> {out}")


def _platform_apis_configured() -> bool:
    import os
    return bool(os.environ.get("UNSPLASH_ACCESS_KEY") or os.environ.get("PEXELS_API_KEY"))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="provenance.py",
        description="AI training image provenance collector.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_csv(p): p.add_argument("--csv", metavar="PATH")
    def add_dry(p): p.add_argument("--dry-run", dest="dry_run", action="store_true")

    # download
    p = sub.add_parser("download", help="Download an image and capture provenance.")
    p.add_argument("url")
    p.add_argument("--dir", "-d", metavar="PATH")
    p.add_argument("--source-page", "-p", dest="source_page", metavar="URL")
    add_csv(p); add_dry(p)

    # scan
    p = sub.add_parser("scan", help="Capture provenance for existing images.")
    p.add_argument("path")
    p.add_argument("--skip-existing", dest="skip_existing", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--no-history", dest="no_history", action="store_true")
    add_csv(p); add_dry(p)

    # watch
    p = sub.add_parser("watch", help="Watch a folder for new images.")
    p.add_argument("dir")
    p.add_argument("--no-history", dest="no_history", action="store_true")
    add_csv(p)

    # enrich
    p = sub.add_parser("enrich", help="Back-fill from Chrome/Edge history + platform APIs.")
    p.add_argument("path")
    p.add_argument("--force", action="store_true")
    p.add_argument("--no-scrape", dest="no_scrape", action="store_true")
    p.add_argument("--wayback",  action="store_true", help="Archive source URLs to Wayback Machine.")
    p.add_argument("--spawning", action="store_true", help="Check Spawning DNTR opt-out registry.")
    add_dry(p)

    # history
    p = sub.add_parser("history", help="Show recent Chrome/Edge image downloads.")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--db", metavar="PATH")

    # audit
    p = sub.add_parser("audit", help="Gap report.")
    p.add_argument("path", nargs="?")

    # migrate
    p = sub.add_parser("migrate", help="Upgrade v1.0 sidecars to v2.0.")
    p.add_argument("path")
    add_dry(p)

    # export
    p = sub.add_parser("export", help="Export full collection to CSV.")
    p.add_argument("csv_path", nargs="?", default=DEFAULT_CSV)

    # report
    p = sub.add_parser("report", help="Generate a self-contained HTML provenance report.")
    p.add_argument("output", nargs="?", default="provenance_report.html",
                   help="Output HTML file path (default: provenance_report.html)")
    p.add_argument("--limit", type=int, default=5000, help="Max assets to include.")

    args = parser.parse_args()
    {
        "download": cmd_download,
        "scan":     cmd_scan,
        "watch":    cmd_watch,
        "enrich":   cmd_enrich,
        "history":  cmd_history,
        "audit":    cmd_audit,
        "migrate":  cmd_migrate,
        "export":   cmd_export,
        "report":   cmd_report,
    }[args.command](args)


if __name__ == "__main__":
    main()
