import pytest
from unittest.mock import patch, MagicMock
import requests


def _mock_response(html: str, status: int = 200, content_type: str = "text/html"):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status
    resp.ok = (status == 200)
    resp.text = html
    resp.headers = {"content-type": content_type}
    resp.raise_for_status.return_value = None
    return resp


class TestScrapePageMetadata:
    def test_extracts_og_title(self):
        from lib.scrapers import scrape_page_metadata
        html = """
        <html><head>
          <meta property="og:title" content="Test Photo" />
          <meta property="og:image" content="https://example.com/img.jpg" />
        </head></html>
        """
        with patch("lib.scrapers._get_with_backoff", return_value=_mock_response(html)):
            result = scrape_page_metadata("https://example.com/page")

        # OpenGraph data is nested under 'opengraph'
        assert result.get("opengraph", {}).get("og:title") == "Test Photo"

    def test_extracts_cc_license_from_link_tag(self):
        from lib.scrapers import scrape_page_metadata
        html = """
        <html><head>
          <link rel="license" href="https://creativecommons.org/licenses/by/4.0/" />
        </head></html>
        """
        with patch("lib.scrapers._get_with_backoff", return_value=_mock_response(html)):
            result = scrape_page_metadata("https://example.com/page")

        assert "creativecommons.org/licenses/by" in result.get("license_url", "")

    def test_extracts_schema_org_creator(self):
        from lib.scrapers import scrape_page_metadata
        html = """
        <html><body>
          <script type="application/ld+json">
          {"@type": "ImageObject", "creator": {"name": "Jane Doe"},
           "license": "https://creativecommons.org/licenses/by/4.0/"}
          </script>
        </body></html>
        """
        with patch("lib.scrapers._get_with_backoff", return_value=_mock_response(html)):
            result = scrape_page_metadata("https://example.com/page")

        schema_objects = result.get("schema_org", [])
        creators = [obj.get("creator", {}).get("name") for obj in schema_objects if isinstance(obj, dict)]
        assert "Jane Doe" in creators

    def test_handles_non_200(self):
        from lib.scrapers import scrape_page_metadata
        with patch("lib.scrapers._get_with_backoff", return_value=_mock_response("", status=404)):
            result = scrape_page_metadata("https://example.com/missing")
        # Should return a dict (possibly with scrape_error)
        assert isinstance(result, dict)

    def test_returns_dict_on_exception(self):
        from lib.scrapers import scrape_page_metadata
        with patch("lib.scrapers._get_with_backoff", return_value=None):
            result = scrape_page_metadata("https://example.com/page")
        assert isinstance(result, dict)

    def test_extracts_page_title(self):
        from lib.scrapers import scrape_page_metadata
        html = "<html><head><title>My Gallery</title></head></html>"
        with patch("lib.scrapers._get_with_backoff", return_value=_mock_response(html)):
            result = scrape_page_metadata("https://example.com/page")
        assert result.get("page_title") == "My Gallery"

    def test_cc_link_href_captured(self):
        from lib.scrapers import scrape_page_metadata
        html = """
        <html><body>
          <a href="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0</a>
        </body></html>
        """
        with patch("lib.scrapers._get_with_backoff", return_value=_mock_response(html)):
            result = scrape_page_metadata("https://example.com/page")
        assert "cc_license" in result or "cc_license_url" in result


class TestBackoffOnRateLimit:
    def test_retries_on_429(self):
        from lib.scrapers import _get_with_backoff
        r429 = MagicMock(spec=requests.Response)
        r429.status_code = 429
        r429.ok = False
        r200 = _mock_response("<html></html>")

        with (
            patch("lib.scrapers.requests.get", side_effect=[r429, r429, r200]),
            patch("lib.scrapers.time.sleep"),
        ):
            result = _get_with_backoff("https://example.com/page")

        assert result.status_code == 200

    def test_returns_none_after_all_retries_fail(self):
        from lib.scrapers import _get_with_backoff
        r429 = MagicMock(spec=requests.Response)
        r429.status_code = 429
        r429.ok = False

        with (
            patch("lib.scrapers.requests.get", return_value=r429),
            patch("lib.scrapers.time.sleep"),
        ):
            result = _get_with_backoff("https://example.com/page")

        # After exhausting retries, should return the last response or None
        assert result is None or result.status_code == 429
