import os
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone


# Chrome stores timestamps as microseconds since 1601-01-01
_CHROME_EPOCH_OFFSET = 11644473600  # seconds


def _to_chrome_time(dt: datetime) -> int:
    return int(dt.timestamp() * 1_000_000) + int(_CHROME_EPOCH_OFFSET * 1_000_000)


def _make_chrome_db(path: str, rows: list[dict]) -> None:
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE downloads (
            id INTEGER PRIMARY KEY,
            target_path TEXT,
            start_time INTEGER,
            end_time INTEGER,
            tab_url TEXT,
            referrer TEXT,
            mime_type TEXT,
            total_bytes INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE downloads_url_chains (
            id INTEGER,
            chain_index INTEGER,
            url TEXT
        )
    """)
    for row in rows:
        conn.execute(
            "INSERT INTO downloads VALUES (?,?,?,?,?,?,?,?)",
            (row["id"], row["target_path"], row["start_time"], row["end_time"],
             row.get("tab_url", ""), row.get("referrer", ""),
             row.get("mime_type", "image/jpeg"), row.get("total_bytes", 100000)),
        )
        if row.get("chain_url"):
            conn.execute(
                "INSERT INTO downloads_url_chains VALUES (?,?,?)",
                (row["id"], 0, row["chain_url"]),
            )
    conn.commit()
    conn.close()


class TestFindDownloadRecord:
    def test_finds_by_filename(self, tmp_path):
        from lib.browser_history import find_download_record

        db_path = str(tmp_path / "History")
        now = datetime.now(timezone.utc)
        chain_url = "https://images.unsplash.com/photo-abc123?w=1080"
        _make_chrome_db(db_path, [{
            "id": 1,
            "target_path": "/Users/test/Downloads/photo.jpg",
            "start_time": _to_chrome_time(now),
            "end_time": _to_chrome_time(now),
            "tab_url": "https://unsplash.com/photos/abc123",
            "referrer": "https://unsplash.com/",
            "chain_url": chain_url,
        }])

        result = find_download_record("photo.jpg", history_path=db_path)

        assert result is not None
        assert result["download_url"] == chain_url

    def test_returns_none_when_not_found(self, tmp_path):
        from lib.browser_history import find_download_record

        db_path = str(tmp_path / "History")
        _make_chrome_db(db_path, [])

        result = find_download_record("nonexistent.jpg", history_path=db_path)
        assert result is None

    def test_extracts_google_imgurl(self, tmp_path):
        from lib.browser_history import find_download_record

        db_path = str(tmp_path / "History")
        now = datetime.now(timezone.utc)
        imgurl = "https://example.com/actual_image.jpg"
        google_url = f"https://www.google.com/imgres?imgurl={imgurl}&tbnid=xyz"
        _make_chrome_db(db_path, [{
            "id": 2,
            "target_path": "/tmp/actual_image.jpg",
            "start_time": _to_chrome_time(now),
            "end_time": _to_chrome_time(now),
            "referrer": google_url,
            "chain_url": google_url,
        }])

        result = find_download_record("actual_image.jpg", history_path=db_path)

        assert result is not None
        assert result["original_source_url"] == imgurl

    def test_result_has_expected_keys(self, tmp_path):
        from lib.browser_history import find_download_record

        db_path = str(tmp_path / "History")
        now = datetime.now(timezone.utc)
        _make_chrome_db(db_path, [{
            "id": 3,
            "target_path": "/tmp/photo.png",
            "start_time": _to_chrome_time(now),
            "end_time": _to_chrome_time(now),
            "chain_url": "https://example.com/photo.png",
        }])

        result = find_download_record("photo.png", history_path=db_path)
        assert result is not None
        for key in ["download_url", "referrer", "tab_url", "start_time_utc"]:
            assert key in result


class TestDefaultHistoryPaths:
    def test_returns_list(self):
        from lib.browser_history import _default_history_paths
        paths = _default_history_paths()
        assert isinstance(paths, list)
        for p in paths:
            assert isinstance(p, Path)
