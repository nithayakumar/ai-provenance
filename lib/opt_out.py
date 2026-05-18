"""
Check AI training opt-out signals for a given URL or domain.

Signals checked (in priority order):
  1. IPTC PLUS DataMining field (embedded in the file — highest trust)
  2. tdm-reservation HTTP header (per-URL, EU AI Act Art. 53)
  3. ai.txt (domain-level declaration, Spawning.ai standard)
  4. robots.txt AI-crawler clauses (User-agent: GPTBot, CCBot, etc.)

Results are cached to disk for 24 hours to avoid hammering source sites.
"""

import json
import re
import time
import urllib.parse
from pathlib import Path
from typing import Optional

import requests

from lib.constants import CACHE_DIR

_CACHE_TTL = 86400  # 24 hours


def _cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\-.]", "_", key)[:120]
    return CACHE_DIR / f"{safe}.json"


def _cache_get(key: str) -> Optional[dict]:
    p = _cache_path(key)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        if time.time() - data.get("_cached_at", 0) < _CACHE_TTL:
            return data
    except Exception:
        pass
    return None


def _cache_set(key: str, value: dict) -> None:
    value["_cached_at"] = time.time()
    try:
        _cache_path(key).write_text(json.dumps(value))
    except Exception:
        pass


def _get(url: str, timeout: int = 8) -> Optional[requests.Response]:
    try:
        return requests.get(
            url,
            headers={"User-Agent": "ProvenanceCollector/1.0"},
            timeout=timeout,
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Per-signal checks
# ---------------------------------------------------------------------------

def check_tdm_reservation(url: str) -> Optional[int]:
    """
    HEAD the URL and read the tdm-reservation header.
    Returns 1 (reserved/opt-out), 0 (allowed), or None (header absent).
    """
    try:
        resp = requests.head(
            url,
            headers={"User-Agent": "ProvenanceCollector/1.0"},
            timeout=8,
            allow_redirects=True,
        )
        val = resp.headers.get("tdm-reservation")
        if val is not None:
            return int(val.strip()) if val.strip() in ("0", "1") else None
    except Exception:
        pass
    return None


def check_ai_txt(domain: str) -> Optional[bool]:
    """
    Fetch https://<domain>/ai.txt and check for blanket AI training prohibition.
    Returns True (opt-out), False (opted-in / no restriction), None (file absent).
    Cached 24h.
    """
    cache_key = f"ai_txt_{domain}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached.get("opt_out")

    resp = _get(f"https://{domain}/ai.txt")
    if resp is None or resp.status_code != 200:
        _cache_set(cache_key, {"opt_out": None})
        return None

    text = resp.text.lower()
    # Look for blanket disallow patterns in ai.txt
    opt_out = bool(
        re.search(r"disallow\s*:\s*/", text)
        or "training" in text and "no" in text
        or "noai" in text
    )
    _cache_set(cache_key, {"opt_out": opt_out})
    return opt_out


def check_robots_ai_clauses(domain: str) -> Optional[bool]:
    """
    Fetch robots.txt and look for AI crawler directives.
    Returns True if any known AI agent is disallowed from /, else False, else None.
    Cached 24h.
    """
    cache_key = f"robots_{domain}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached.get("opt_out")

    resp = _get(f"https://{domain}/robots.txt")
    if resp is None or resp.status_code != 200:
        _cache_set(cache_key, {"opt_out": None})
        return None

    _AI_AGENTS = {
        "gptbot", "ccbot", "claudebot", "anthropic-ai", "google-extended",
        "diffbot", "bytespider", "omgili", "omgilibot", "facebot",
        "ia_archiver", "magpie-crawler",
    }
    text = resp.text.lower()
    current_agents: set[str] = set()
    opt_out = False

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("user-agent:"):
            agent = line.split(":", 1)[1].strip().lower()
            current_agents = {agent} if agent != "*" else set()
        elif line.startswith("disallow:"):
            path = line.split(":", 1)[1].strip()
            if path == "/" and (not current_agents or current_agents & _AI_AGENTS):
                opt_out = True
                break

    _cache_set(cache_key, {"opt_out": opt_out})
    return opt_out


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------

def check_all(
    url: Optional[str],
    iptc_data_mining: Optional[str] = None,
    c2pa_training_opt_out: Optional[bool] = None,
) -> dict:
    """
    Run all applicable opt-out checks and return an aggregated result.

    Returns:
      opt_out   bool | None   — True if ANY signal says no, None if all unknown
      signals   dict          — individual signal results
    """
    signals: dict = {
        "iptc_data_mining":    iptc_data_mining,
        "c2pa_training":       c2pa_training_opt_out,
        "tdm_reservation":     None,
        "ai_txt":              None,
        "robots_ai":           None,
    }

    if url:
        domain = urllib.parse.urlparse(url).netloc
        signals["tdm_reservation"] = check_tdm_reservation(url)
        if domain:
            signals["ai_txt"]     = check_ai_txt(domain)
            signals["robots_ai"]  = check_robots_ai_clauses(domain)

    # Determine aggregate opt_out
    # IPTC DataMining field: any "Prohibited" value is an opt-out
    iptc_opt_out: Optional[bool] = None
    if iptc_data_mining:
        iptc_opt_out = "prohibited" in iptc_data_mining.lower()

    any_true = any(
        v is True for v in [
            iptc_opt_out,
            c2pa_training_opt_out,
            signals["tdm_reservation"] == 1,
            signals["ai_txt"],
            signals["robots_ai"],
        ]
    )
    all_none = all(
        v is None for v in [
            iptc_opt_out, c2pa_training_opt_out,
            signals["tdm_reservation"], signals["ai_txt"], signals["robots_ai"],
        ]
    )

    return {
        "opt_out":  True if any_true else (None if all_none else False),
        "signals":  signals,
    }
