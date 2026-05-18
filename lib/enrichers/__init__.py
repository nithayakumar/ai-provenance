"""
Platform API enrichers — fill in license, photographer, and description
from authoritative sources when a source URL is recognised.

Usage:
    from lib.enrichers import enrich

    updated = enrich(provenance_record)   # returns updated copy, never mutates

Each sub-module exposes a single function:
    enrich(record: dict) -> dict   — returns updated copy or original unchanged
"""

from lib.enrichers.unsplash import enrich as _unsplash
from lib.enrichers.pexels import enrich as _pexels
from lib.enrichers.wayback import enrich as _wayback
from lib.enrichers.spawning import enrich as _spawning


_ENRICHERS = [_unsplash, _pexels, _wayback, _spawning]


def enrich(record: dict, *, wayback: bool = False, spawning: bool = False) -> dict:
    """
    Run all applicable enrichers against a provenance record.

    Args:
        record:   provenance dict (schema v2.0)
        wayback:  opt-in — submit URL to Wayback Machine for archival
        spawning: opt-in — check Spawning DNTR registry

    Returns a new dict; the input is never mutated.
    """
    out = dict(record)
    for fn in _ENRICHERS:
        if fn is _wayback and not wayback:
            continue
        if fn is _spawning and not spawning:
            continue
        try:
            out = fn(out)
        except Exception:
            pass  # enrichers are advisory — never block on failure
    return out
