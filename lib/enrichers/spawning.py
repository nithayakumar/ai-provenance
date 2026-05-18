"""
Spawning DNTR (Do Not Train Registry) enricher (opt-in).

Checks whether the image URL is registered in the Spawning opt-out
registry. No API key required for basic lookups.

API: https://api.spawning.ai/spawning-api/v1/search
Rate limits: ~1 req/s recommended.
"""

import time
from typing import Optional

import requests

_API_URL = "https://api.spawning.ai/spawning-api"


def _check_url(image_url: str) -> Optional[bool]:
    """
    Returns True if URL is opted out, False if explicitly allowed,
    None if not found / API unavailable.
    """
    try:
        resp = requests.post(
            f"{_API_URL}/v1/search",
            json={"urls": [image_url]},
            headers={
                "User-Agent": "ProvenanceCollector/1.0",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        # Response: {"data": [{"url": "...", "haveibeentrained": "yes"|"no"|"unknown"}]}
        entries = data.get("data", [])
        if not entries:
            return None
        status = entries[0].get("haveibeentrained", "unknown")
        if status == "no":
            return True   # opted out of training
        if status == "yes":
            return False  # in training sets / not opted out
    except Exception:
        pass
    return None


def enrich(record: dict) -> dict:
    source_url = record.get("source", {}).get("url")
    if not source_url:
        return record

    # Already checked
    signals = record.get("rights", {}).get("ai_training", {}).get("signals", {})
    if signals.get("spawning_dntr") is not None:
        return record

    time.sleep(0.5)  # rate limit
    result = _check_url(source_url)

    if result is None:
        return record

    out = {**record}
    rights = {**out.get("rights", {})}
    ai_training = {**rights.get("ai_training", {})}
    sig = {**ai_training.get("signals", {}), "spawning_dntr": result}
    ai_training["signals"] = sig

    # If Spawning says opted out, propagate to top-level opt_out
    if result is True and ai_training.get("opt_out") is None:
        ai_training["opt_out"] = True

    rights["ai_training"] = ai_training
    out["rights"] = rights
    return out
