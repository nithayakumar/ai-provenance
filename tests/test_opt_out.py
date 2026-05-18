import pytest
from unittest.mock import patch, MagicMock


class TestCheckTdmReservation:
    def test_opt_out_when_header_is_1(self):
        from lib.opt_out import check_tdm_reservation
        mock_resp = MagicMock()
        mock_resp.headers = {"tdm-reservation": "1"}
        mock_resp.status_code = 200

        with patch("lib.opt_out.requests.head", return_value=mock_resp):
            result = check_tdm_reservation("https://example.com/img.jpg")
        assert result == 1

    def test_allowed_when_header_is_0(self):
        from lib.opt_out import check_tdm_reservation
        mock_resp = MagicMock()
        mock_resp.headers = {"tdm-reservation": "0"}

        with patch("lib.opt_out.requests.head", return_value=mock_resp):
            result = check_tdm_reservation("https://example.com/img.jpg")
        assert result == 0

    def test_returns_none_when_header_absent(self):
        from lib.opt_out import check_tdm_reservation
        mock_resp = MagicMock()
        mock_resp.headers = {}

        with patch("lib.opt_out.requests.head", return_value=mock_resp):
            result = check_tdm_reservation("https://example.com/img.jpg")
        assert result is None

    def test_returns_none_on_exception(self):
        from lib.opt_out import check_tdm_reservation
        with patch("lib.opt_out.requests.head", side_effect=Exception("timeout")):
            result = check_tdm_reservation("https://example.com/img.jpg")
        assert result is None


class TestCheckAiTxt:
    def test_opt_out_when_disallow_all(self):
        from lib.opt_out import check_ai_txt
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "User-agent: *\nDisallow: /"

        with (
            patch("lib.opt_out._get", return_value=mock_resp),
            patch("lib.opt_out._cache_get", return_value=None),
            patch("lib.opt_out._cache_set"),
        ):
            result = check_ai_txt("example.com")
        assert result is True

    def test_returns_none_when_file_missing(self):
        from lib.opt_out import check_ai_txt
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with (
            patch("lib.opt_out._get", return_value=mock_resp),
            patch("lib.opt_out._cache_get", return_value=None),
            patch("lib.opt_out._cache_set"),
        ):
            result = check_ai_txt("example.com")
        assert result is None

    def test_uses_cache_when_available(self):
        from lib.opt_out import check_ai_txt

        with (
            patch("lib.opt_out._cache_get", return_value={"opt_out": True}),
        ):
            result = check_ai_txt("example.com")
        assert result is True


class TestCheckAll:
    def test_aggregates_signals_returns_dict(self):
        from lib.opt_out import check_all
        with (
            patch("lib.opt_out.check_tdm_reservation", return_value=1),
            patch("lib.opt_out.check_ai_txt", return_value=None),
            patch("lib.opt_out.check_robots_ai_clauses", return_value=None),
        ):
            result = check_all("https://example.com/img.jpg")

        assert isinstance(result, dict)
        assert result["opt_out"] is True
        assert "signals" in result

    def test_iptc_opt_out_propagates(self):
        from lib.opt_out import check_all
        with (
            patch("lib.opt_out.check_tdm_reservation", return_value=None),
            patch("lib.opt_out.check_ai_txt", return_value=None),
            patch("lib.opt_out.check_robots_ai_clauses", return_value=None),
        ):
            result = check_all("https://example.com/img.jpg", iptc_data_mining="DMI-PROHIBITED")

        assert result["opt_out"] is True

    def test_none_when_all_unknown(self):
        from lib.opt_out import check_all
        with (
            patch("lib.opt_out.check_tdm_reservation", return_value=None),
            patch("lib.opt_out.check_ai_txt", return_value=None),
            patch("lib.opt_out.check_robots_ai_clauses", return_value=None),
        ):
            result = check_all("https://example.com/img.jpg")

        assert result["opt_out"] is None

    def test_c2pa_opt_out_propagates(self):
        from lib.opt_out import check_all
        with (
            patch("lib.opt_out.check_tdm_reservation", return_value=None),
            patch("lib.opt_out.check_ai_txt", return_value=None),
            patch("lib.opt_out.check_robots_ai_clauses", return_value=None),
        ):
            result = check_all(
                "https://example.com/img.jpg",
                c2pa_training_opt_out=True,
            )

        assert result["opt_out"] is True

    def test_handles_none_url(self):
        from lib.opt_out import check_all
        result = check_all(None)
        assert isinstance(result, dict)
        assert "opt_out" in result
