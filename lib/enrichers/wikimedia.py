"""
Wikimedia Commons enricher.

For images hosted on upload.wikimedia.org, constructs the Commons page URL
and scrapes the license, author, and description.

No API key required. Uses the MediaWiki API (free, open).

Example:
  upload.wikimedia.org/wikipedia/commons/a/a8/Steam_phase_eruption.jpg
  → commons.wikimedia.org/wiki/File:Steam_phase_eruption.jpg
"""

import re
import urllib.parse
from typing import Optional

import requests

_COMMONS_API = "https://commons.wikimedia.org/w/api.php"

# Map Wikimedia license template names to SPDX identifiers
_LICENSE_MAP = {
    "cc-by-sa-4.0": "CC-BY-SA-4.0",
    "cc-by-sa-3.0": "CC-BY-SA-3.0",
    "cc-by-sa-2.5": "CC-BY-SA-2.5",
    "cc-by-sa-2.0": "CC-BY-SA-2.0",
    "cc-by-sa-1.0": "CC-BY-SA-1.0",
    "cc-by-4.0":    "CC-BY-4.0",
    "cc-by-3.0":    "CC-BY-3.0",
    "cc-by-2.5":    "CC-BY-2.5",
    "cc-by-2.0":    "CC-BY-2.0",
    "cc-zero":      "CC0-1.0",
    "cc0":          "CC0-1.0",
    "pd":           "CC0-1.0",
    "public domain": "CC0-1.0",
}


def _extract_filename(url: str) -> Optional[str]:
    """Extract the Commons filename from an upload.wikimedia.org URL."""
    if "wikimedia.org" not in url and "wikipedia.org" not in url:
        return None
    # https://upload.wikimedia.org/wikipedia/commons/a/a8/Some_file.jpg
    m = re.search(r"wikipedia/(?:commons|en|de|fr|[a-z]+)/[a-f0-9]/[a-f0-9]{2}/(.+?)(?:\?|$)", url, re.I)
    if m:
        return urllib.parse.unquote(m.group(1))
    # Fallback: last path segment for wikimedia URLs
    path = urllib.parse.urlparse(url).path
    name = path.rstrip("/").split("/")[-1]
    if "." in name:
        return urllib.parse.unquote(name)
    return None


def _query_commons(filename: str) -> Optional[dict]:
    """Query the MediaWiki API for file metadata."""
    try:
        resp = requests.get(
            _COMMONS_API,
            params={
                "action": "query",
                "titles": f"File:{filename}",
                "prop": "imageinfo|revisions",
                "iiprop": "extmetadata",
                "rvprop": "content",
                "format": "json",
            },
            headers={"User-Agent": "ProvenanceCollector/1.0"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        pages = data.get("query", {}).get("pages", {})
        page = next(iter(pages.values()), {})
        imageinfo = page.get("imageinfo", [{}])[0]
        return imageinfo.get("extmetadata", {})
    except Exception:
        return None


def _parse_metadata(meta: dict) -> dict:
    """Extract license, author, description from Commons extmetadata."""
    result = {}

    # License — normalise spaces/dashes before matching
    license_short = re.sub(r"[\s_]+", "-", (meta.get("LicenseShortName", {}).get("value") or "")).lower()
    license_url   = meta.get("LicenseUrl", {}).get("value")
    for key, spdx in _LICENSE_MAP.items():
        if key in license_short:
            result["license_spdx"] = spdx
            break
    if license_url:
        result["license_url"] = license_url

    # Author — strip HTML tags
    raw_author = meta.get("Artist", {}).get("value") or meta.get("Credit", {}).get("value") or ""
    if raw_author:
        clean = re.sub(r"<[^>]+>", "", raw_author).strip()
        if clean:
            result["author"] = clean

    # Copyright
    raw_copy = meta.get("UsageTerms", {}).get("value") or meta.get("Copyrighted", {}).get("value") or ""
    if raw_copy:
        result["copyright"] = re.sub(r"<[^>]+>", "", raw_copy).strip()

    # Description
    desc = meta.get("ImageDescription", {}).get("value") or ""
    if desc:
        result["description"] = re.sub(r"<[^>]+>", "", desc).strip()[:200]

    return result


def enrich(record: dict) -> dict:
    source_url = record.get("source", {}).get("url", "") or ""

    # Only handle upload.wikimedia.org
    if "wikimedia.org" not in source_url and "wikipedia.org" not in source_url:
        return record

    filename = _extract_filename(source_url)
    if not filename:
        return record

    meta = _query_commons(filename)
    if not meta:
        return record

    parsed = _parse_metadata(meta)
    if not parsed:
        return record

    out = {**record}

    # License
    if parsed.get("license_spdx") and not out.get("rights", {}).get("license_spdx"):
        out["rights"] = {**out.get("rights", {}), "license_spdx": parsed["license_spdx"]}
    if parsed.get("license_url") and not out.get("rights", {}).get("license_url"):
        out["rights"] = {**out.get("rights", {}), "license_url": parsed["license_url"]}
    if parsed.get("copyright") and not out.get("rights", {}).get("copyright"):
        out["rights"] = {**out.get("rights", {}), "copyright": parsed["copyright"]}

    # Author
    if parsed.get("author") and not out.get("creator", {}).get("name"):
        out["creator"] = {**out.get("creator", {}), "name": parsed["author"]}
        # Commons page as profile URL
        page = f"https://commons.wikimedia.org/wiki/File:{urllib.parse.quote(filename)}"
        out["creator"] = {**out["creator"], "profile_url": page}

    # Source page (Commons file page)
    if not out.get("source", {}).get("page_url"):
        page = f"https://commons.wikimedia.org/wiki/File:{urllib.parse.quote(filename)}"
        out["source"] = {**out.get("source", {}), "page_url": page}

    # Platform
    out["source"] = {**out.get("source", {}), "platform": "wikimedia"}

    return out
