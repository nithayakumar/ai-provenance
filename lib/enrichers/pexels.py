"""
Pexels API enricher.

Requires env var: PEXELS_API_KEY
Free tier: 200 requests/hour, 20,000/month.

Recognises URLs of the form:
  https://www.pexels.com/photo/<slug>-<id>/
  https://images.pexels.com/photos/<id>/...
"""

import os
import re
from typing import Optional

import requests

_API_BASE = "https://api.pexels.com/v1"
_PHOTO_ID_PATTERNS = [
    re.compile(r"pexels\.com/photo/[^/]+-(\d+)/?", re.I),
    re.compile(r"images\.pexels\.com/photos/(\d+)/", re.I),
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
            headers={"Authorization": key},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def enrich(record: dict) -> dict:
    key = os.environ.get("PEXELS_API_KEY")
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
    if data.get("photographer"):
        out["creator"] = {**out.get("creator", {}), "name": data["photographer"]}
    if data.get("photographer_url"):
        out["creator"] = {**out.get("creator", {}), "profile_url": data["photographer_url"]}

    # Rights — Pexels license
    out["rights"] = {
        **out.get("rights", {}),
        "license_spdx": "LicenseRef-Pexels",
        "license_url": "https://www.pexels.com/license/",
    }

    # Source
    out["source"] = {
        **out.get("source", {}),
        "platform": "pexels",
        "domain": "pexels.com",
    }
    if data.get("url"):
        out["source"]["page_url"] = out["source"].get("page_url") or data["url"]

    # AI training — Pexels license permits training (no opt-out clause as of 2025)
    ai_training = out.get("rights", {}).get("ai_training", {})
    if ai_training.get("opt_out") is None:
        out["rights"]["ai_training"] = {**ai_training, "opt_out": False}

    return out
