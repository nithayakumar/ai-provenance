"""
Wayback Machine archival enricher (opt-in).

Submits the source page URL to the Internet Archive Save API and stores
the resulting snapshot URL in the provenance record.

Free, no API key required. Rate-limited: ~1 req/s.
Only runs when explicitly opted-in via enrich(record, wayback=True).
"""

import time
from typing import Optional

import requests

_SAVE_API = "https://web.archive.org/save/"
_AVAIL_API = "https://archive.org/wayback/available"


def _check_existing(url: str) -> Optional[str]:
    """Return most recent snapshot URL if one already exists."""
    try:
        resp = requests.get(
            _AVAIL_API,
            params={"url": url},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            snap = data.get("archived_snapshots", {}).get("closest", {})
            if snap.get("available") and snap.get("url"):
                return snap["url"]
    except Exception:
        pass
    return None


def _submit(url: str) -> Optional[str]:
    """Submit URL for archival. Returns snapshot URL or None."""
    try:
        resp = requests.get(
            f"{_SAVE_API}{url}",
            headers={"User-Agent": "ProvenanceCollector/1.0"},
            timeout=30,
            allow_redirects=True,
        )
        # Wayback returns the snapshot URL in the Content-Location header
        loc = resp.headers.get("Content-Location", "")
        if loc.startswith("/web/"):
            return f"https://web.archive.org{loc}"
        # Also check the final URL
        if "web.archive.org/web/" in resp.url:
            return resp.url
    except Exception:
        pass
    return None


def enrich(record: dict) -> dict:
    page_url = record.get("source", {}).get("page_url") or record.get("source", {}).get("url")
    if not page_url:
        return record

    # Don't re-archive if we already have a snapshot
    if record.get("source", {}).get("wayback_url"):
        return record

    # Check for existing snapshot first (avoids redundant submits)
    snapshot = _check_existing(page_url)

    if not snapshot:
        time.sleep(0.5)  # be polite to Wayback
        snapshot = _submit(page_url)

    if not snapshot:
        return record

    out = {**record}
    out["source"] = {**out.get("source", {}), "wayback_url": snapshot}
    return out
