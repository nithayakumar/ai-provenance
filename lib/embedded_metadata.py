"""
Read embedded metadata from image files: EXIF, IPTC, and XMP.
Includes IPTC 2025.1 AI-specific fields.

Requires: python-xmp-toolkit (pip) + libexempi (brew install exempi / apt install libexempi-dev)
Falls back gracefully to exiftool subprocess if python-xmp-toolkit is unavailable.
"""

import json
import subprocess
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# XMP
# ---------------------------------------------------------------------------

def _read_xmp_via_toolkit(filepath: str) -> dict:
    from libxmp import XMPFiles, consts  # noqa: F401 — import guarded
    xf = XMPFiles(file_path=filepath)
    xmp = xf.get_xmp()
    xf.close_file()
    if xmp is None:
        return {}

    def get(ns, prop):
        try:
            return xmp.get_property(ns, prop) or None
        except Exception:
            return None

    DC   = "http://purl.org/dc/elements/1.1/"
    XR   = "http://ns.adobe.com/xap/1.0/rights/"
    PLUS = "http://ns.useplus.org/ldf/xmp/1.0/"
    IPTC4 = "http://iptc.org/std/Iptc4xmpExt/2008-02-29/"

    return {k: v for k, v in {
        # Dublin Core
        "dc_creator":        get(DC, "creator[1]"),
        "dc_rights":         get(DC, "rights[1]"),
        "dc_source":         get(DC, "source"),
        # xmpRights
        "xmp_rights_marked":      get(XR, "Marked"),
        "xmp_rights_owner":       get(XR, "Owner[1]"),
        "xmp_rights_usage_terms": get(XR, "UsageTerms[1]"),
        "xmp_rights_web_stmt":    get(XR, "WebStatement"),
        # PLUS — AI training opt-out
        "plus_data_mining":       get(PLUS, "DataMining"),
        # IPTC 2025.1 AI fields
        "iptc_digital_source_type": get(IPTC4, "DigitalSourceType"),
        "iptc_ai_prompt":           get(IPTC4, "AIPrompt"),
        "iptc_ai_system":           get(IPTC4, "AISystemUsed[1]"),
        "iptc_ai_system_version":   get(IPTC4, "AISystemVersionUsed"),
        "iptc_ai_prompt_writer":    get(IPTC4, "AIPromptWriter"),
    }.items() if v is not None}


def _read_xmp_via_exiftool(filepath: str) -> dict:
    try:
        out = subprocess.run(
            ["exiftool", "-json", "-XMP:all", filepath],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return {}
        data = json.loads(out.stdout)[0]
    except Exception:
        return {}

    mapping = {
        "Creator":          "dc_creator",
        "Rights":           "dc_rights",
        "Source":           "dc_source",
        "Marked":           "xmp_rights_marked",
        "Owner":            "xmp_rights_owner",
        "UsageTerms":       "xmp_rights_usage_terms",
        "WebStatement":     "xmp_rights_web_stmt",
        "DataMining":       "plus_data_mining",
        "DigitalSourceType": "iptc_digital_source_type",
        "AIPrompt":         "iptc_ai_prompt",
        "AISystemUsed":     "iptc_ai_system",
        "AISystemVersionUsed": "iptc_ai_system_version",
    }
    return {v: str(data[k]) for k, v in mapping.items() if k in data and data[k]}


def read_xmp(filepath: str) -> dict:
    try:
        return _read_xmp_via_toolkit(filepath)
    except ImportError:
        return _read_xmp_via_exiftool(filepath)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# IPTC (IIM embedded in JPEG)
# ---------------------------------------------------------------------------

def read_iptc(filepath: str) -> dict:
    try:
        from iptcinfo3 import IPTCInfo
        info = IPTCInfo(filepath, force=True)
        result = {}
        # object_name=5, keywords=25, by_line=80, by_line_title=85,
        # copyright_notice=116, source=115, usage_terms=not standard IIM
        for iim_key, our_key in [
            ("object name",      "iptc_object_name"),
            ("by-line",          "iptc_by_line"),
            ("by-line title",    "iptc_by_line_title"),
            ("copyright notice", "iptc_copyright_notice"),
            ("source",           "iptc_source"),
            ("credit",           "iptc_credit"),
        ]:
            val = info.data.get(iim_key)
            if val:
                if isinstance(val, (list, tuple)):
                    val = val[0] if val else None
                if isinstance(val, bytes):
                    val = val.decode("utf-8", errors="replace")
                if val:
                    result[our_key] = val
        return result
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Unified reader + canonical mapping
# ---------------------------------------------------------------------------

def read_all_embedded(filepath: str) -> dict:
    from lib.metadata import extract_exif
    return {
        "exif": extract_exif(filepath),
        "xmp":  read_xmp(filepath),
        "iptc": read_iptc(filepath),
    }


# PLUS DataMining → plain opt-out flag
_PLUS_OPT_OUT_VALUES = {
    "DMI-PROHIBITED",
    "DMI-PROHIBITED-EXCEPTRESEARCH",
    "DMI-PROHIBITED-GENERATIVEAI",
    "DMI-PROHIBITED-EXCEPTRESEARCHAI",
}


def extract_ai_training_signals(embedded: dict) -> dict:
    """Pull AI-training-relevant signals out of embedded metadata."""
    xmp  = embedded.get("xmp",  {})
    iptc = embedded.get("iptc", {})
    exif = embedded.get("exif", {})

    # Author: prefer XMP dc:creator, fall back to IPTC by-line, EXIF Artist
    author = (
        xmp.get("dc_creator")
        or iptc.get("iptc_by_line")
        or exif.get("Artist")
    )

    # Copyright
    copyright_ = (
        xmp.get("dc_rights")
        or iptc.get("iptc_copyright_notice")
        or exif.get("Copyright")
    )

    # License URL
    license_url = xmp.get("xmp_rights_web_stmt") or xmp.get("xmp_rights_usage_terms")

    # AI training opt-out via IPTC PLUS DataMining
    data_mining = xmp.get("plus_data_mining", "")
    iptc_opt_out = data_mining.upper().replace(" ", "-") in _PLUS_OPT_OUT_VALUES if data_mining else None

    # AI generation status via IPTC 2025.1 DigitalSourceType
    digital_source = xmp.get("iptc_digital_source_type", "")
    # trainedAlgorithmicMedia or compositeWithTrainedAlgorithmicMedia → AI-generated
    is_ai_generated: Optional[bool] = None
    if digital_source:
        dst_lower = digital_source.lower()
        if "trainedalgorithmic" in dst_lower:
            is_ai_generated = True
        elif dst_lower in ("digitally_captured", "digitallyCapture", "photograph"):
            is_ai_generated = False

    return {
        "author":           author,
        "copyright":        copyright_,
        "license_url":      license_url,
        "iptc_opt_out":     iptc_opt_out,
        "is_ai_generated":  is_ai_generated,
        "ai_source_type":   digital_source or None,
        "ai_prompt":        xmp.get("iptc_ai_prompt"),
        "ai_system":        xmp.get("iptc_ai_system"),
        "ai_system_version": xmp.get("iptc_ai_system_version"),
    }
