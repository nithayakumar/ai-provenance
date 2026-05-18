"""
Map free-text license strings and URLs to SPDX identifiers.
https://spdx.org/licenses/

Coverage: all Creative Commons variants v1.0-v4.0, public domain marks,
Unsplash License, Pexels License, and common stock license patterns.
"""

import re
from typing import Optional

# (pattern, spdx_id) — checked in order, first match wins
_TEXT_PATTERNS: list[tuple[re.Pattern, str]] = [
    # CC0 / Public Domain
    (re.compile(r"cc0|cc\s*zero|public\s*domain\s*(mark|dedication)?", re.I), "CC0-1.0"),
    (re.compile(r"public\s*domain", re.I), "CC0-1.0"),
    # CC BY-NC-ND
    (re.compile(r"by[-\s]nc[-\s]nd", re.I), "CC-BY-NC-ND-4.0"),
    # CC BY-NC-SA
    (re.compile(r"by[-\s]nc[-\s]sa", re.I), "CC-BY-NC-SA-4.0"),
    # CC BY-NC
    (re.compile(r"by[-\s]nc\b", re.I), "CC-BY-NC-4.0"),
    # CC BY-ND
    (re.compile(r"by[-\s]nd\b", re.I), "CC-BY-ND-4.0"),
    # CC BY-SA
    (re.compile(r"by[-\s]sa\b", re.I), "CC-BY-SA-4.0"),
    # CC BY (plain attribution)
    (re.compile(r"\bcc[-\s]by\b", re.I), "CC-BY-4.0"),
    (re.compile(r"creative\s*commons\s*attribution\b", re.I), "CC-BY-4.0"),
    (re.compile(r"creative\s*commons\b", re.I), "CC-BY-4.0"),  # generic CC fallback
    # Unsplash
    (re.compile(r"unsplash\s*licen[sc]e", re.I), "LicenseRef-Unsplash"),
    # Pexels
    (re.compile(r"pexels\s*licen[sc]e", re.I), "LicenseRef-Pexels"),
    # All Rights Reserved
    (re.compile(r"all\s*rights\s*reserved", re.I), "LicenseRef-AllRightsReserved"),
]

_URL_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"creativecommons\.org/publicdomain/zero", re.I), "CC0-1.0"),
    (re.compile(r"creativecommons\.org/publicdomain/mark", re.I), "CC0-1.0"),
    (re.compile(r"creativecommons\.org/licenses/by-nc-nd", re.I), "CC-BY-NC-ND-4.0"),
    (re.compile(r"creativecommons\.org/licenses/by-nc-sa", re.I), "CC-BY-NC-SA-4.0"),
    (re.compile(r"creativecommons\.org/licenses/by-nc",    re.I), "CC-BY-NC-4.0"),
    (re.compile(r"creativecommons\.org/licenses/by-nd",    re.I), "CC-BY-ND-4.0"),
    (re.compile(r"creativecommons\.org/licenses/by-sa",    re.I), "CC-BY-SA-4.0"),
    (re.compile(r"creativecommons\.org/licenses/by",       re.I), "CC-BY-4.0"),
    (re.compile(r"unsplash\.com/license",                  re.I), "LicenseRef-Unsplash"),
    (re.compile(r"pexels\.com/license",                    re.I), "LicenseRef-Pexels"),
]

# Version normalisation: if detected SPDX ends with -4.0 but URL has /3.0/, downgrade
_VERSION_RE = re.compile(r"/(\d+\.\d+)/")


def _adjust_version(spdx: str, url: str) -> str:
    m = _VERSION_RE.search(url)
    if not m:
        return spdx
    version = m.group(1)
    if version == "4.0":
        return spdx
    # Replace trailing version in SPDX ID
    return re.sub(r"-\d+\.\d+$", f"-{version}", spdx)


def to_spdx(
    license_text: Optional[str] = None,
    license_url: Optional[str] = None,
) -> Optional[str]:
    """
    Map a license string and/or URL to an SPDX identifier.
    Returns None if no match found.
    """
    # URL first (more precise)
    if license_url:
        for pattern, spdx in _URL_PATTERNS:
            if pattern.search(license_url):
                return _adjust_version(spdx, license_url)

    if license_text:
        for pattern, spdx in _TEXT_PATTERNS:
            if pattern.search(license_text):
                return spdx

    return None
