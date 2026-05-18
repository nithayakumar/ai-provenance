"""
Read Chrome/Edge download history to match image files to their source URLs.

Chrome History SQLite is locked while Chrome is open, so we always work from
a temporary copy. Chrome timestamps are microseconds since 1601-01-01 UTC.

Auto-detected paths:
  macOS Chrome:  ~/Library/Application Support/Google/Chrome/Default/History
  macOS Edge:    ~/Library/Application Support/Microsoft Edge/Default/History
  Linux Chrome:  ~/.config/google-chrome/Default/History
  Linux Edge:    ~/.config/microsoft-edge/Default/History
  Windows Chrome: %LOCALAPPDATA%/Google/Chrome/User Data/Default/History
  Windows Edge:   %LOCALAPPDATA%/Microsoft/Edge/User Data/Default/History
"""

import contextlib
import os
import shutil
import sqlite3
import tempfile
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_CHROME_EPOCH_OFFSET = 11644473600  # seconds between 1601-01-01 and 1970-01-01


def _chrome_ts_to_unix(ts: int) -> float:
    return (ts / 1_000_000) - _CHROME_EPOCH_OFFSET


def _default_history_paths() -> list[Path]:
    """Return all readable Chrome/Edge history files across every profile."""
    home  = Path.home()
    local = Path(os.environ.get("LOCALAPPDATA", ""))

    # Root dirs that contain profile subdirectories
    roots = [
        home / "Library/Application Support/Google/Chrome",
        home / "Library/Application Support/Google/Chrome Beta",
        home / "Library/Application Support/Google/Chrome Canary",
        home / "Library/Application Support/Microsoft Edge",
        home / ".config/google-chrome",
        home / ".config/microsoft-edge",
        local / "Google/Chrome/User Data",
        local / "Microsoft/Edge/User Data",
    ]

    paths = []
    for root in roots:
        if not root.exists():
            continue
        # Each direct child that contains a History file is a profile
        for child in sorted(root.iterdir()):
            h = child / "History"
            if h.exists():
                paths.append(h)

    return paths


@contextlib.contextmanager
def _history_copy(hist_path: Path):
    """Copy a locked SQLite history file to a temp location and yield a connection."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        shutil.copy2(str(hist_path), tmp.name)
        conn = sqlite3.connect(tmp.name)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    except (OSError, sqlite3.DatabaseError):
        yield None
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def _extract_google_original_url(url: str) -> Optional[str]:
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
    Search Chrome/Edge download history for a file by name and optional timestamp.
    Returns a dict with download_url, referrer, tab_url, mime_type, timestamps,
    original_source_url. Returns None if no match found.
    """
    paths = [Path(history_path)] if history_path else _default_history_paths()
    for path in paths:
        result = _query_one_history(path, filename, file_mtime, time_window_seconds)
        if result:
            return result
    return None


def _query_one_history(
    hist_path: Path,
    filename: str,
    file_mtime: Optional[float],
    time_window_seconds: int,
) -> Optional[dict]:
    with _history_copy(hist_path) as conn:
        if conn is None:
            return None
        rows = _fetch_download_rows(conn, filename, file_mtime, time_window_seconds)

    if not rows:
        return None

    if file_mtime and len(rows) > 1:
        rows = sorted(rows, key=lambda r: abs(_chrome_ts_to_unix(r["end_time"]) - file_mtime))

    row = rows[0]
    download_url = row["url"]

    # data: URIs are base64-embedded images with no real provenance value
    if download_url and download_url.startswith("data:"):
        download_url = None

    referrer = row["referrer"] or ""
    tab_url = row["tab_url"] or ""

    original_source = None
    for candidate in (referrer, tab_url):
        original_source = _extract_google_original_url(candidate)
        if original_source:
            break
    if not original_source:
        for candidate in (referrer, tab_url):
            p = urllib.parse.urlparse(candidate)
            if p.scheme in ("http", "https") and "google." not in p.netloc:
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
        "end_time_utc": datetime.fromtimestamp(end_unix, tz=timezone.utc).isoformat() if end_unix else None,
        "original_source_url": original_source,
        "history_db": str(hist_path),
    }


def _fetch_download_rows(
    conn: sqlite3.Connection,
    filename: str,
    file_mtime: Optional[float],
    time_window_seconds: int,
) -> list:
    if file_mtime:
        chrome_mtime = int((file_mtime + _CHROME_EPOCH_OFFSET) * 1_000_000)
        window = time_window_seconds * 1_000_000
        time_filter = "AND d.end_time BETWEEN ? AND ?"
        time_params = (chrome_mtime - window, chrome_mtime + window)
    else:
        time_filter = ""
        time_params = ()

    sql = f"""
        SELECT d.start_time, d.end_time, d.referrer, d.tab_url, d.mime_type, uc.url
        FROM downloads d
        JOIN downloads_url_chains uc ON uc.id = d.id
        WHERE (d.target_path LIKE ? OR d.target_path LIKE ?)
        {time_filter}
        ORDER BY uc.chain_index DESC
    """
    params = (f"%/{filename}", f"%\\{filename}") + time_params
    try:
        conn.execute("SELECT 1 FROM downloads LIMIT 1")  # verify schema exists
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []


def list_recent_image_downloads(
    history_path: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """Return recent image downloads from all detected Chrome/Edge history files."""
    paths = [Path(history_path)] if history_path else _default_history_paths()
    results = []
    for hist_path in paths:
        with _history_copy(hist_path) as conn:
            if conn is None:
                continue
            try:
                rows = conn.execute(
                    """
                    SELECT d.target_path, d.end_time, d.referrer, d.tab_url, uc.url
                    FROM downloads d
                    JOIN downloads_url_chains uc ON uc.id = d.id
                    WHERE d.mime_type LIKE 'image/%'
                       OR d.target_path LIKE '%.jpg' OR d.target_path LIKE '%.jpeg'
                       OR d.target_path LIKE '%.png' OR d.target_path LIKE '%.webp'
                    ORDER BY d.end_time DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            except sqlite3.OperationalError:
                continue
        for row in rows:
            end_unix = _chrome_ts_to_unix(row["end_time"]) if row["end_time"] else None
            results.append({
                "filename": Path(row["target_path"]).name,
                "download_url": row["url"],
                "tab_url": row["tab_url"],
                "referrer": row["referrer"],
                "end_time_utc": datetime.fromtimestamp(end_unix, tz=timezone.utc).isoformat() if end_unix else None,
            })
    return results
