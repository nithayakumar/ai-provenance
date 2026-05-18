"""
Read Chrome/Edge download history to match image files to their source URLs.

Chrome stores its History database at (copy the path for your OS):
  Linux:   ~/.config/google-chrome/Default/History
           ~/.config/microsoft-edge/Default/History
  macOS:   ~/Library/Application Support/Google/Chrome/Default/History
           ~/Library/Application Support/Microsoft Edge/Default/History
  Windows: %LOCALAPPDATA%\Google\Chrome\User Data\Default\History
           %LOCALAPPDATA%\Microsoft\Edge\User Data\Default\History

The DB is locked while Chrome is open, so we always work from a temp copy.
"""

import os
import re
import shutil
import sqlite3
import tempfile
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# Chrome timestamps = microseconds since 1601-01-01 00:00:00 UTC
_CHROME_EPOCH_OFFSET_SECONDS = 11644473600


def _chrome_ts_to_unix(chrome_ts: int) -> float:
    return (chrome_ts / 1_000_000) - _CHROME_EPOCH_OFFSET_SECONDS


def _default_history_paths() -> list[Path]:
    home = Path.home()
    candidates = [
        # Linux Chrome
        home / ".config/google-chrome/Default/History",
        home / ".config/google-chrome/Profile 1/History",
        # Linux Edge
        home / ".config/microsoft-edge/Default/History",
        # macOS Chrome
        home / "Library/Application Support/Google/Chrome/Default/History",
        # macOS Edge
        home / "Library/Application Support/Microsoft Edge/Default/History",
        # Windows Chrome
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Google/Chrome/User Data/Default/History",
        # Windows Edge
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Microsoft/Edge/User Data/Default/History",
    ]
    return [p for p in candidates if p.exists()]


def _extract_google_original_url(url: str) -> Optional[str]:
    """Pull the original image URL out of a Google Images referrer/tab URL."""
    parsed = urllib.parse.urlparse(url)
    if "google." not in parsed.netloc:
        return None
    params = urllib.parse.parse_qs(parsed.query)
    for key in ("imgurl", "url", "imgrefurl"):
        if params.get(key):
            return params[key][0]
    return None


def find_download_record(
    filename: str,
    file_mtime: Optional[float] = None,
    history_path: Optional[str] = None,
    time_window_seconds: int = 120,
) -> Optional[dict]:
    """
    Look up a filename in Chrome/Edge download history.

    Returns a dict with keys: download_url, referrer, tab_url, mime_type,
    start_time_utc, end_time_utc, original_source_url (if deducible).
    Returns None if no match is found.
    """
    paths = [Path(history_path)] if history_path else _default_history_paths()
    if not paths:
        return None

    for hist_path in paths:
        result = _query_history(hist_path, filename, file_mtime, time_window_seconds)
        if result:
            return result
    return None


def _query_history(
    hist_path: Path,
    filename: str,
    file_mtime: Optional[float],
    time_window_seconds: int,
) -> Optional[dict]:
    # Copy to temp file because Chrome holds a lock on the original
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    try:
        shutil.copy2(str(hist_path), tmp.name)
        tmp.close()
        conn = sqlite3.connect(tmp.name)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        rows = _fetch_rows(cur, filename, file_mtime, time_window_seconds)
        conn.close()
    except sqlite3.DatabaseError:
        return None
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    if not rows:
        return None

    # Pick the best match: prefer rows whose end_time is closest to file_mtime
    if file_mtime and len(rows) > 1:
        rows.sort(key=lambda r: abs(_chrome_ts_to_unix(r["end_time"]) - file_mtime))

    row = rows[0]
    download_url = row["url"]  # from url_chains (actual fetched URL)
    referrer = row["referrer"] or ""
    tab_url = row["tab_url"] or ""

    # Try to surface the original source page (not just the raw image URL)
    original_source = None
    for candidate in (referrer, tab_url):
        original_source = _extract_google_original_url(candidate)
        if original_source:
            break
    # If referrer/tab_url is a meaningful (non-Google) page URL, keep it
    if not original_source:
        for candidate in (referrer, tab_url):
            parsed = urllib.parse.urlparse(candidate)
            if parsed.scheme in ("http", "https") and "google." not in parsed.netloc:
                original_source = candidate
                break

    start_unix = _chrome_ts_to_unix(row["start_time"])
    end_unix = _chrome_ts_to_unix(row["end_time"]) if row["end_time"] else None

    return {
        "download_url": download_url,
        "referrer": referrer,
        "tab_url": tab_url,
        "mime_type": row["mime_type"] or "",
        "start_time_utc": datetime.fromtimestamp(start_unix, tz=timezone.utc).isoformat(),
        "end_time_utc": (
            datetime.fromtimestamp(end_unix, tz=timezone.utc).isoformat()
            if end_unix
            else None
        ),
        "original_source_url": original_source,
        "history_db": str(hist_path),
    }


def _fetch_rows(
    cur: sqlite3.Cursor,
    filename: str,
    file_mtime: Optional[float],
    time_window_seconds: int,
) -> list:
    # Build timestamp window in Chrome epoch microseconds
    if file_mtime:
        chrome_mtime = int((file_mtime + _CHROME_EPOCH_OFFSET_SECONDS) * 1_000_000)
        window = time_window_seconds * 1_000_000
        time_clause = (
            f"AND d.end_time BETWEEN {chrome_mtime - window} AND {chrome_mtime + window}"
        )
    else:
        time_clause = ""

    sql = f"""
        SELECT
            d.id,
            d.target_path,
            d.start_time,
            d.end_time,
            d.referrer,
            d.tab_url,
            d.mime_type,
            uc.url
        FROM downloads d
        JOIN downloads_url_chains uc ON uc.id = d.id
        WHERE (
            d.target_path LIKE ? OR d.target_path LIKE ?
        )
        {time_clause}
        ORDER BY uc.chain_index DESC
    """
    # Match filename with both forward-slash and backslash separators
    pattern_fwd = f"%/{filename}"
    pattern_back = f"%\\{filename}"
    try:
        cur.execute(sql, (pattern_fwd, pattern_back))
        return cur.fetchall()
    except sqlite3.OperationalError:
        return []


def list_recent_image_downloads(
    history_path: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """Return the most recent image downloads from Chrome history (for debugging)."""
    paths = [Path(history_path)] if history_path else _default_history_paths()
    if not paths:
        return []

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    try:
        shutil.copy2(str(paths[0]), tmp.name)
        tmp.close()
        conn = sqlite3.connect(tmp.name)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT d.target_path, d.end_time, d.referrer, d.tab_url, uc.url
            FROM downloads d
            JOIN downloads_url_chains uc ON uc.id = d.id
            WHERE d.mime_type LIKE 'image/%' OR d.target_path LIKE '%.jpg'
               OR d.target_path LIKE '%.png' OR d.target_path LIKE '%.webp'
            ORDER BY d.end_time DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
        conn.close()
    except (sqlite3.DatabaseError, OSError):
        return []
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    results = []
    for row in rows:
        end_unix = _chrome_ts_to_unix(row["end_time"]) if row["end_time"] else None
        results.append(
            {
                "filename": Path(row["target_path"]).name,
                "download_url": row["url"],
                "tab_url": row["tab_url"],
                "referrer": row["referrer"],
                "end_time_utc": (
                    datetime.fromtimestamp(end_unix, tz=timezone.utc).isoformat()
                    if end_unix
                    else None
                ),
            }
        )
    return results
