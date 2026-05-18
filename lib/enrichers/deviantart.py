"""
DeviantArt enricher.

Two sources of data:
1. Filename parsing — DeviantArt files follow the pattern:
       <title>_by_<author>_<shortid>-pre.jpg
   This gives us the author username reliably without any API call.

2. oEmbed API (no auth required) — returns title, author, thumbnail URL,
   and the canonical artwork page URL.
   https://backend.deviantart.com/oembed?url=https://www.deviantart.com/art/<shortid>

3. robots.txt — DeviantArt explicitly blocks AI training crawlers (GPTBot, CCBot etc.)
   so opt_out is True for all DeviantArt images.
"""

import re
import urllib.parse
from typing import Optional

import requests

_OEMBED_URL = "https://backend.deviantart.com/oembed"
_DA_FILENAME_RE = re.compile(
    r"^(.+?)_by_([a-z0-9_-]+)_([a-z0-9]+)(?:-pre)?\.(?:jpg|jpeg|png|gif|webp)$",
    re.I,
)


def _parse_filename(filename: str) -> Optional[dict]:
    """Extract title, author, shortid from a DeviantArt filename."""
    m = _DA_FILENAME_RE.match(filename)
    if not m:
        return None
    return {
        "title":   m.group(1).replace("_", " "),
        "author":  m.group(2),
        "shortid": m.group(3),
    }


def _oembed(author: str, title: str, shortid: str) -> Optional[dict]:
    """
    Try DeviantArt's oEmbed endpoint to get the canonical page URL.
    Constructs a plausible artwork URL from the known parts.
    """
    try:
        # DeviantArt art URLs: https://www.deviantart.com/<author>/art/<title-slug>-<numeric-id>
        # We don't have the numeric id, but oEmbed accepts the shortid form too
        art_url = f"https://www.deviantart.com/{author}/art/{shortid}"
        resp = requests.get(
            _OEMBED_URL,
            params={"url": art_url, "format": "json"},
            headers={"User-Agent": "ProvenanceCollector/1.0"},
            timeout=8,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def _is_deviantart(record: dict) -> bool:
    source = record.get("source", {})
    url    = source.get("url", "") or ""
    platform = source.get("platform", "")
    return platform == "deviantart" or "wixmp.com" in url or "deviantart.com" in url


def enrich(record: dict) -> dict:
    if not _is_deviantart(record):
        return record

    filename = record.get("file", {}).get("filename", "")
    parsed   = _parse_filename(filename)

    out = {**record}

    # --- Author from filename (always available, no network call) ---
    if parsed and not out.get("creator", {}).get("name"):
        author = parsed["author"]
        out["creator"] = {
            **out.get("creator", {}),
            "name": author,
            "profile_url": f"https://www.deviantart.com/{author}",
        }

    # --- Canonical page URL via oEmbed ---
    page_url = out.get("source", {}).get("page_url", "")
    if parsed and (not page_url or page_url.rstrip("/") == "https://www.deviantart.com"):
        oembed = _oembed(parsed["author"], parsed["title"], parsed["shortid"])
        if oembed:
            # oEmbed returns author_url and the artwork URL in oembed["url"]
            if oembed.get("url"):
                out["source"] = {**out.get("source", {}), "page_url": oembed["url"]}
            if oembed.get("author_name") and not out["creator"].get("name"):
                out["creator"] = {**out.get("creator", {}), "name": oembed["author_name"]}
            if oembed.get("author_url"):
                out["creator"] = {**out.get("creator", {}), "profile_url": oembed["author_url"]}

    # --- Build page_url from author + shortid if oEmbed failed ---
    page_url = out.get("source", {}).get("page_url", "")
    if parsed and (not page_url or page_url.rstrip("/") == "https://www.deviantart.com"):
        out["source"] = {
            **out.get("source", {}),
            "page_url": f"https://www.deviantart.com/{parsed['author']}/art/{parsed['shortid']}",
        }

    # --- DeviantArt opts out of AI training (announced 2022, robots.txt blocks crawlers) ---
    ai_training = out.get("rights", {}).get("ai_training", {})
    if ai_training.get("opt_out") is None:
        signals = {**ai_training.get("signals", {}), "robots_ai": True}
        out["rights"] = {
            **out.get("rights", {}),
            "ai_training": {**ai_training, "opt_out": True, "signals": signals},
        }

    return out
