import pytest
from unittest.mock import patch


_STEAM_URL = "https://upload.wikimedia.org/wikipedia/commons/a/a8/Steam_phase_eruption_of_Castle_Geyser.jpg"


def _base_record(url=_STEAM_URL):
    return {
        "schema_version": "2.0",
        "file": {"sha256": "a" * 64, "filename": "Steam_phase_eruption_of_Castle_Geyser.jpg"},
        "source": {"url": url, "platform": "unknown"},
        "creator": {},
        "rights": {},
        "ai": {},
    }


def _mock_api_response():
    return {
        "LicenseShortName": {"value": "CC BY-SA 4.0"},
        "LicenseUrl":       {"value": "https://creativecommons.org/licenses/by-sa/4.0"},
        "Artist":           {"value": "Brocken Inaglory"},
        "UsageTerms":       {"value": "Creative Commons Attribution-Share Alike 4.0"},
        "ImageDescription": {"value": "Steam phase eruption of Castle Geyser in Yellowstone."},
    }


class TestExtractFilename:
    def test_standard_commons_url(self):
        from lib.enrichers.wikimedia import _extract_filename
        result = _extract_filename(_STEAM_URL)
        assert result == "Steam_phase_eruption_of_Castle_Geyser.jpg"

    def test_returns_none_for_non_wikimedia(self):
        from lib.enrichers.wikimedia import _extract_filename
        result = _extract_filename("https://example.com/photo.jpg")
        assert result is None


class TestEnrich:
    def test_enriches_wikimedia_image(self):
        from lib.enrichers.wikimedia import enrich
        rec = _base_record()

        with patch("lib.enrichers.wikimedia._query_commons", return_value=_mock_api_response()):
            result = enrich(rec)

        assert result["rights"]["license_spdx"] == "CC-BY-SA-4.0"
        assert result["creator"]["name"] == "Brocken Inaglory"
        assert result["source"]["platform"] == "wikimedia"
        assert "commons.wikimedia.org" in result["source"].get("page_url", "")

    def test_skips_non_wikimedia_url(self):
        from lib.enrichers.wikimedia import enrich
        rec = _base_record("https://example.com/photo.jpg")

        with patch("lib.enrichers.wikimedia._query_commons") as mock_api:
            result = enrich(rec)

        mock_api.assert_not_called()
        assert result == rec

    def test_does_not_overwrite_existing_license(self):
        from lib.enrichers.wikimedia import enrich
        rec = _base_record()
        rec["rights"]["license_spdx"] = "CC0-1.0"

        with patch("lib.enrichers.wikimedia._query_commons", return_value=_mock_api_response()):
            result = enrich(rec)

        assert result["rights"]["license_spdx"] == "CC0-1.0"  # not overwritten

    def test_returns_original_on_api_failure(self):
        from lib.enrichers.wikimedia import enrich
        rec = _base_record()

        with patch("lib.enrichers.wikimedia._query_commons", return_value=None):
            result = enrich(rec)

        assert result == rec

    def test_does_not_mutate_input(self):
        import json
        from lib.enrichers.wikimedia import enrich
        rec = _base_record()
        original = json.dumps(rec)

        with patch("lib.enrichers.wikimedia._query_commons", return_value=_mock_api_response()):
            enrich(rec)

        assert json.dumps(rec) == original


class TestDataUriFiltering:
    def test_data_uri_not_stored_as_source_url(self):
        """data: URIs from browser history must be discarded."""
        from lib.enrichers.wikimedia import enrich
        rec = _base_record("data:image/jpeg;base64,/9j/abc123")

        with patch("lib.enrichers.wikimedia._query_commons") as mock_api:
            result = enrich(rec)

        mock_api.assert_not_called()
        assert result == rec
