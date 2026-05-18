import pytest
from unittest.mock import patch

_CDN_URL = "https://images-wixmp-ed30a86b8c4ca887773594c2.wixmp.com/f/abc/dlwd5ad-xxx.png/v1/fill/cindergaze_by_stellastria_dlwd5ad-pre.jpg"


def _base_record(filename="cindergaze_by_stellastria_dlwd5ad-pre.jpg", platform="deviantart"):
    return {
        "file": {"sha256": "a" * 64, "filename": filename},
        "source": {
            "url": _CDN_URL,
            "platform": platform,
            "page_url": "https://www.deviantart.com/",
        },
        "creator": {},
        "rights": {"ai_training": {}},
        "ai": {},
    }


class TestParseFilename:
    def test_standard_pattern(self):
        from lib.enrichers.deviantart import _parse_filename
        result = _parse_filename("cindergaze_by_stellastria_dlwd5ad-pre.jpg")
        assert result["author"] == "stellastria"
        assert result["title"] == "cindergaze"
        assert result["shortid"] == "dlwd5ad"

    def test_multi_word_title(self):
        from lib.enrichers.deviantart import _parse_filename
        result = _parse_filename("dark_forest_night_by_artist123_abc123.jpg")
        assert result["author"] == "artist123"
        assert result["title"] == "dark forest night"

    def test_non_deviantart_returns_none(self):
        from lib.enrichers.deviantart import _parse_filename
        assert _parse_filename("photo.jpg") is None
        assert _parse_filename("random_file_name.jpg") is None


class TestEnrich:
    def test_extracts_author_from_filename(self):
        from lib.enrichers.deviantart import enrich
        rec = _base_record()
        with patch("lib.enrichers.deviantart._oembed", return_value=None):
            result = enrich(rec)
        assert result["creator"]["name"] == "stellastria"
        assert "deviantart.com/stellastria" in result["creator"]["profile_url"]

    def test_sets_opt_out_true(self):
        from lib.enrichers.deviantart import enrich
        rec = _base_record()
        with patch("lib.enrichers.deviantart._oembed", return_value=None):
            result = enrich(rec)
        assert result["rights"]["ai_training"]["opt_out"] is True

    def test_does_not_overwrite_existing_opt_out(self):
        from lib.enrichers.deviantart import enrich
        rec = _base_record()
        rec["rights"]["ai_training"]["opt_out"] = False
        with patch("lib.enrichers.deviantart._oembed", return_value=None):
            result = enrich(rec)
        assert result["rights"]["ai_training"]["opt_out"] is False

    def test_constructs_page_url_from_author_shortid(self):
        from lib.enrichers.deviantart import enrich
        rec = _base_record()
        with patch("lib.enrichers.deviantart._oembed", return_value=None):
            result = enrich(rec)
        page_url = result["source"].get("page_url", "")
        assert "stellastria" in page_url
        assert "dlwd5ad" in page_url

    def test_uses_oembed_page_url_when_available(self):
        from lib.enrichers.deviantart import enrich
        rec = _base_record()
        oembed_data = {
            "url": "https://www.deviantart.com/stellastria/art/cindergaze-123456",
            "author_name": "Stellastria",
            "author_url": "https://www.deviantart.com/stellastria",
        }
        with patch("lib.enrichers.deviantart._oembed", return_value=oembed_data):
            result = enrich(rec)
        assert result["source"]["page_url"] == oembed_data["url"]

    def test_skips_non_deviantart(self):
        from lib.enrichers.deviantart import enrich
        rec = _base_record(platform="unsplash")
        rec["source"]["url"] = "https://images.unsplash.com/photo-123"
        result = enrich(rec)
        assert result == rec

    def test_does_not_mutate_input(self):
        import json
        from lib.enrichers.deviantart import enrich
        rec = _base_record()
        original = json.dumps(rec)
        with patch("lib.enrichers.deviantart._oembed", return_value=None):
            enrich(rec)
        assert json.dumps(rec) == original
