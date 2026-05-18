"""
Compute a completeness score for a provenance record.
Pure function — no I/O, no side effects.

Weights reflect how much each field matters for AI training dataset audits.
"""

_WEIGHTS = {
    "has_source_url":     0.20,
    "has_sha256":         0.10,
    "has_author":         0.10,
    "has_license_spdx":   0.20,
    "ai_status_known":    0.15,
    "opt_out_checked":    0.15,
    "has_platform":       0.05,
    "has_copyright":      0.05,
}


def compute(provenance: dict) -> dict:
    """
    Return a dict with:
      score         float 0.0–1.0
      has_*         individual boolean flags
    """
    source  = provenance.get("source",  {})
    creator = provenance.get("creator", {})
    rights  = provenance.get("rights",  {})
    ai      = provenance.get("ai",      {})
    file_   = provenance.get("file",    {})

    flags = {
        "has_source_url":   bool(source.get("url")),
        "has_sha256":       bool(file_.get("sha256")),
        "has_author":       bool(creator.get("name")),
        "has_license_spdx": bool(rights.get("license_spdx")),
        "ai_status_known":  ai.get("is_ai_generated") is not None,
        "opt_out_checked":  rights.get("ai_training", {}).get("opt_out") is not None,
        "has_platform":     bool(source.get("platform") and source["platform"] != "unknown"),
        "has_copyright":    bool(rights.get("copyright")),
    }

    score = round(sum(_WEIGHTS[k] for k, v in flags.items() if v), 4)
    return {"score": score, **flags}
