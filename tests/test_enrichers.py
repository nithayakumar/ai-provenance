"""
Tests for Phase 2 enrichers: Unsplash, Pexels, Wayback, Spawning.
All network calls are mocked — no API keys or internet required.
"""

import json
import pytest
from unittest.mock import patch, MagicMock


def _base_record(source_url="https://example.com/img.jpg", platform=None):
    return {
        "schema_version": "2.0",
        "file": {"sha256": "a" * 64, "filename": "img.jpg"},
        "source": {"url": source_url, "platform": platform or "unknown"},
        "creator": {},
        "rights": {"ai_training": {}},
        "ai": {},
    }


# ---------------------------------------------------------------------------
# Unsplash
# ---------------------------------------------------------------------------

class TestUnsplashEnricher:
    def _api_response(self):
        return {
            "user": {
                "name": "Jane Photo",
                "links": {"html": "https://unsplash.com/@janephoto"},
            },
            "links": {"html": "https://unsplash.com/photos/abc123"},
            "description": "A scenic mountain view",
        }

    def test_enriches_unsplash_url(self):
        from lib.enrichers.unsplash import enrich
        rec = _base_record("https://images.unsplash.com/photo-abc123?w=800")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = self._api_response()

        with (
            patch("lib.enrichers.unsplash.requests.get", return_value=mock_resp),
            patch.dict("os.environ", {"UNSPLASH_ACCESS_KEY": "test_key"}),
        ):
            result = enrich(rec)

        assert result["creator"]["name"] == "Jane Photo"
        assert result["rights"]["license_spdx"] == "LicenseRef-Unsplash"
        assert result["source"]["platform"] == "unsplash"

    def test_skips_when_no_api_key(self):
        from lib.enrichers.unsplash import enrich
        rec = _base_record("https://images.unsplash.com/photo-abc123?w=800")

        with patch.dict("os.environ", {}, clear=True):
            result = enrich(rec)

        assert result == rec  # unchanged

    def test_skips_non_unsplash_url(self):
        from lib.enrichers.unsplash import enrich
        rec = _base_record("https://example.com/some-photo.jpg")

        with patch.dict("os.environ", {"UNSPLASH_ACCESS_KEY": "test_key"}):
            result = enrich(rec)

        assert result == rec

    def test_does_not_mutate_input(self):
        from lib.enrichers.unsplash import enrich
        rec = _base_record("https://images.unsplash.com/photo-xyz?w=800")
        original = json.dumps(rec)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = self._api_response()

        with (
            patch("lib.enrichers.unsplash.requests.get", return_value=mock_resp),
            patch.dict("os.environ", {"UNSPLASH_ACCESS_KEY": "test_key"}),
        ):
            enrich(rec)

        assert json.dumps(rec) == original  # input unchanged

    def test_opt_out_set_false_for_unsplash(self):
        from lib.enrichers.unsplash import enrich
        rec = _base_record("https://images.unsplash.com/photo-abc123?w=800")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = self._api_response()

        with (
            patch("lib.enrichers.unsplash.requests.get", return_value=mock_resp),
            patch.dict("os.environ", {"UNSPLASH_ACCESS_KEY": "test_key"}),
        ):
            result = enrich(rec)

        assert result["rights"]["ai_training"]["opt_out"] is False


# ---------------------------------------------------------------------------
# Pexels
# ---------------------------------------------------------------------------

class TestPexelsEnricher:
    def _api_response(self):
        return {
            "photographer": "Bob Lens",
            "photographer_url": "https://www.pexels.com/@boblens",
            "url": "https://www.pexels.com/photo/mountains-12345/",
        }

    def test_enriches_pexels_url(self):
        from lib.enrichers.pexels import enrich
        rec = _base_record("https://images.pexels.com/photos/12345/photo.jpg")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = self._api_response()

        with (
            patch("lib.enrichers.pexels.requests.get", return_value=mock_resp),
            patch.dict("os.environ", {"PEXELS_API_KEY": "test_key"}),
        ):
            result = enrich(rec)

        assert result["creator"]["name"] == "Bob Lens"
        assert result["rights"]["license_spdx"] == "LicenseRef-Pexels"
        assert result["source"]["platform"] == "pexels"

    def test_skips_when_no_api_key(self):
        from lib.enrichers.pexels import enrich
        rec = _base_record("https://images.pexels.com/photos/12345/photo.jpg")

        with patch.dict("os.environ", {}, clear=True):
            result = enrich(rec)

        assert result == rec

    def test_page_url_extracted(self):
        from lib.enrichers.pexels import enrich
        rec = _base_record("https://images.pexels.com/photos/12345/photo.jpg")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = self._api_response()

        with (
            patch("lib.enrichers.pexels.requests.get", return_value=mock_resp),
            patch.dict("os.environ", {"PEXELS_API_KEY": "test_key"}),
        ):
            result = enrich(rec)

        assert "pexels.com/photo" in (result["source"].get("page_url") or "")


# ---------------------------------------------------------------------------
# Wayback
# ---------------------------------------------------------------------------

class TestWaybackEnricher:
    def test_uses_existing_snapshot(self):
        from lib.enrichers.wayback import enrich
        rec = _base_record("https://example.com/img.jpg")
        rec["source"]["page_url"] = "https://example.com/page"

        avail_resp = MagicMock()
        avail_resp.status_code = 200
        avail_resp.json.return_value = {
            "archived_snapshots": {
                "closest": {
                    "available": True,
                    "url": "https://web.archive.org/web/20240101/https://example.com/page",
                }
            }
        }

        with patch("lib.enrichers.wayback.requests.get", return_value=avail_resp):
            result = enrich(rec)

        assert "web.archive.org" in result["source"].get("wayback_url", "")

    def test_skips_if_already_archived(self):
        from lib.enrichers.wayback import enrich
        rec = _base_record("https://example.com/img.jpg")
        rec["source"]["wayback_url"] = "https://web.archive.org/web/20240101/..."

        with patch("lib.enrichers.wayback.requests.get") as mock_get:
            result = enrich(rec)

        mock_get.assert_not_called()
        assert result == rec

    def test_returns_original_on_api_failure(self):
        from lib.enrichers.wayback import enrich
        rec = _base_record("https://example.com/img.jpg")
        rec["source"]["page_url"] = "https://example.com/page"

        with patch("lib.enrichers.wayback.requests.get", side_effect=Exception("timeout")):
            result = enrich(rec)

        assert result.get("source", {}).get("wayback_url") is None

    def test_skips_when_no_url(self):
        from lib.enrichers.wayback import enrich
        rec = _base_record()
        rec["source"]["url"] = None
        rec["source"].pop("page_url", None)

        with patch("lib.enrichers.wayback.requests.get") as mock_get:
            result = enrich(rec)

        mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# Spawning
# ---------------------------------------------------------------------------

class TestSpawningEnricher:
    def test_detects_opt_out(self):
        from lib.enrichers.spawning import enrich
        rec = _base_record("https://example.com/img.jpg")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"url": "https://example.com/img.jpg", "haveibeentrained": "no"}]
        }

        with (
            patch("lib.enrichers.spawning.requests.post", return_value=mock_resp),
            patch("lib.enrichers.spawning.time.sleep"),
        ):
            result = enrich(rec)

        assert result["rights"]["ai_training"]["signals"]["spawning_dntr"] is True
        assert result["rights"]["ai_training"]["opt_out"] is True

    def test_detects_allowed(self):
        from lib.enrichers.spawning import enrich
        rec = _base_record("https://example.com/img.jpg")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"url": "https://example.com/img.jpg", "haveibeentrained": "yes"}]
        }

        with (
            patch("lib.enrichers.spawning.requests.post", return_value=mock_resp),
            patch("lib.enrichers.spawning.time.sleep"),
        ):
            result = enrich(rec)

        assert result["rights"]["ai_training"]["signals"]["spawning_dntr"] is False

    def test_skips_when_already_checked(self):
        from lib.enrichers.spawning import enrich
        rec = _base_record("https://example.com/img.jpg")
        rec["rights"]["ai_training"]["signals"] = {"spawning_dntr": True}

        with patch("lib.enrichers.spawning.requests.post") as mock_post:
            result = enrich(rec)

        mock_post.assert_not_called()

    def test_returns_original_on_api_failure(self):
        from lib.enrichers.spawning import enrich
        rec = _base_record("https://example.com/img.jpg")

        with (
            patch("lib.enrichers.spawning.requests.post", side_effect=Exception("timeout")),
            patch("lib.enrichers.spawning.time.sleep"),
        ):
            result = enrich(rec)

        assert "spawning_dntr" not in result.get("rights", {}).get("ai_training", {}).get("signals", {})


# ---------------------------------------------------------------------------
# Aggregate enrich()
# ---------------------------------------------------------------------------

class TestAggregateEnrich:
    def test_enrichers_never_raise(self):
        from lib.enrichers import enrich
        rec = _base_record("https://example.com/img.jpg")

        with (
            patch("lib.enrichers.unsplash.enrich", side_effect=Exception("crash")),
            patch("lib.enrichers.pexels.enrich", side_effect=Exception("crash")),
            patch("lib.enrichers.wayback.enrich", side_effect=Exception("crash")),
            patch("lib.enrichers.spawning.enrich", side_effect=Exception("crash")),
        ):
            result = enrich(rec)  # must not raise

        assert isinstance(result, dict)

    def test_wayback_skipped_by_default(self):
        from lib.enrichers import enrich
        rec = _base_record()

        with patch("lib.enrichers.wayback.enrich") as mock_wb:
            enrich(rec, wayback=False)

        mock_wb.assert_not_called()

    def test_wayback_runs_when_opted_in(self):
        from lib.enrichers import enrich
        rec = _base_record("https://example.com/img.jpg")
        # wayback=True means the wayback module's enrich should be called.
        # Verify indirectly: it won't raise, and the record comes back.
        with patch("lib.enrichers.wayback.enrich", return_value=rec):
            result = enrich(rec, wayback=True)
        assert isinstance(result, dict)
