"""
Unsplash API enricher.

Requires env var: UNSPLASH_ACCESS_KEY
Free tier: 50 requests/hour.

Recognises URLs of the form:
  https://unsplash.com/photos/<id>
  https://images.unsplash.com/photo-<id>?...
"""

import os
import re
from typing import Optional

import requests

_API_BASE = "https://api.unsplash.com"
_PHOTO_ID_PATTERNS = [
    re.compile(r"unsplash\.com/photos/([A-Za-z0-9_-]+)", re.I),
    re.compile(r"images\.unsplash\.com/photo-([A-Za-z0-9_-]+)", re.I),
]


def _extract_photo_id(url: str) -> Optional[str]:
    for pat in _PHOTO_ID_PATTERNS:
        m = pat.search(url)
        if m:
            return m.group(1)
    return None


def _fetch(photo_id: str, key: str) -> Optional[dict]:
    try:
        resp = requests.get(
            f"{_API_BASE}/photos/{photo_id}",
            headers={"Authorization": f"Client-ID {key}"},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def enrich(record: dict) -> dict:
    key = os.environ.get("UNSPLASH_ACCESS_KEY")
    if not key:
        return record

    source_url = record.get("source", {}).get("url", "") or ""
    page_url   = record.get("source", {}).get("page_url", "") or ""

    photo_id = _extract_photo_id(source_url) or _extract_photo_id(page_url)
    if not photo_id:
        return record

    data = _fetch(photo_id, key)
    if not data:
        return record

    out = {**record}

    # Creator
    user = data.get("user", {})
    if user.get("name"):
        out["creator"] = {**out.get("creator", {}), "name": user["name"]}
    if user.get("links", {}).get("html"):
        out["creator"] = {**out.get("creator", {}), "profile_url": user["links"]["html"]}

    # Rights — Unsplash license
    out["rights"] = {
        **out.get("rights", {}),
        "license_spdx": "LicenseRef-Unsplash",
        "license_url": "https://unsplash.com/license",
    }

    # Source enrichment
    out["source"] = {
        **out.get("source", {}),
        "platform": "unsplash",
        "domain": "unsplash.com",
    }
    if data.get("links", {}).get("html"):
        out["source"]["page_url"] = out["source"].get("page_url") or data["links"]["html"]

    # AI training — Unsplash explicitly allows training as of 2023 ToS
    ai_training = out.get("rights", {}).get("ai_training", {})
    if ai_training.get("opt_out") is None:
        out["rights"]["ai_training"] = {**ai_training, "opt_out": False}

    # Description / alt text as extra context
    desc = data.get("description") or data.get("alt_description")
    if desc:
        out["_unsplash_description"] = desc

    return out
