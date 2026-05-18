"""
Read C2PA Content Credentials manifests from image files.
Uses the official c2pa-python library (pip install c2pa-python).
Falls back gracefully if the library is not installed.

C2PA v2.2 includes explicit AI-ML training assertions:
  c2pa.training-mining  →  allowed | constrained | prohibited
"""

from pathlib import Path
from typing import Optional


def read_c2pa(filepath: str) -> dict:
    """
    Parse a C2PA manifest from an image file.

    Returns a dict with:
      manifest_present   bool
      ai_generated       bool | None
      training_opt_out   bool | None   (True = creator prohibits AI training)
      creator_tool       str | None
      actions            list[dict]
      validation_status  'valid' | 'invalid' | 'absent' | 'unavailable'
    """
    try:
        import c2pa
    except ImportError:
        return _absent("unavailable")

    try:
        reader = c2pa.Reader.from_file(filepath)
    except Exception:
        return _absent("absent")

    try:
        manifest_json = reader.get_active_manifest()
        if manifest_json is None:
            return _absent("absent")
    except Exception:
        return _absent("absent")

    import json
    try:
        manifest = json.loads(manifest_json) if isinstance(manifest_json, str) else manifest_json
    except Exception:
        return _absent("invalid")

    # Validation status
    try:
        validation_status = "valid" if reader.validation_status() is None else "invalid"
    except Exception:
        validation_status = "unknown"

    # Extract assertions
    assertions = manifest.get("assertions", [])
    actions = []
    ai_generated: Optional[bool] = None
    training_opt_out: Optional[bool] = None
    creator_tool: Optional[str] = None

    for assertion in assertions:
        label = assertion.get("label", "")
        data  = assertion.get("data", {})

        if label == "c2pa.actions":
            for act in data.get("actions", []):
                actions.append({
                    "action":     act.get("action"),
                    "software_agent": act.get("softwareAgent"),
                    "when":       act.get("when"),
                })
                # c2pa.created with a softwareAgent that signals AI generation
                if act.get("action") == "c2pa.created" and act.get("softwareAgent"):
                    ai_generated = True

        if label == "c2pa.training-mining":
            entries = data.get("entries", {})
            training_val = entries.get("c2pa.ai_generative_training", {}).get("use", "")
            if training_val == "notAllowed":
                training_opt_out = True
                ai_generated = ai_generated or None
            elif training_val == "allowed":
                training_opt_out = False

        if label == "c2pa.software-agent":
            creator_tool = data.get("name") or data.get("product")

    # Fallback: check claim_generator for tool name
    if not creator_tool:
        creator_tool = manifest.get("claim_generator") or manifest.get("claimGenerator")

    return {
        "manifest_present":  True,
        "ai_generated":      ai_generated,
        "training_opt_out":  training_opt_out,
        "creator_tool":      creator_tool,
        "actions":           actions,
        "validation_status": validation_status,
    }


def _absent(status: str) -> dict:
    return {
        "manifest_present":  False,
        "ai_generated":      None,
        "training_opt_out":  None,
        "creator_tool":      None,
        "actions":           [],
        "validation_status": status,
    }
