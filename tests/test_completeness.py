import pytest
from lib.completeness import compute


def _make_full():
    return {
        "source":  {"url": "https://example.com/img.jpg", "platform": "unsplash"},
        "creator": {"name": "Jane Doe"},
        "rights":  {
            "license_spdx": "CC-BY-4.0",
            "copyright": "© 2024 Jane Doe",
            "ai_training": {"opt_out": False},
        },
        "ai":      {"is_ai_generated": False},
        "file":    {"sha256": "abc123"},
    }


class TestComputeScore:
    def test_full_record_scores_1(self):
        result = compute(_make_full())
        assert result["score"] == 1.0

    def test_empty_record_scores_0(self):
        result = compute({})
        assert result["score"] == 0.0

    def test_partial_score_without_license(self):
        rec = _make_full()
        del rec["rights"]["license_spdx"]
        result = compute(rec)
        assert result["score"] == pytest.approx(0.80, abs=0.001)

    def test_partial_score_without_source_url(self):
        rec = _make_full()
        rec["source"]["url"] = None
        result = compute(rec)
        assert result["score"] == pytest.approx(0.80, abs=0.001)

    def test_unknown_platform_penalised(self):
        rec = _make_full()
        rec["source"]["platform"] = "unknown"
        result = compute(rec)
        assert result["score"] == pytest.approx(0.95, abs=0.001)
        assert result["has_platform"] is False

    def test_opt_out_none_penalised(self):
        rec = _make_full()
        rec["rights"]["ai_training"] = {}
        result = compute(rec)
        assert result["opt_out_checked"] is False

    def test_ai_status_none_penalised(self):
        rec = _make_full()
        rec["ai"]["is_ai_generated"] = None
        result = compute(rec)
        assert result["ai_status_known"] is False


class TestComputeFlags:
    def test_flags_present_in_result(self):
        result = compute(_make_full())
        expected_flags = {
            "has_source_url", "has_sha256", "has_author", "has_license_spdx",
            "ai_status_known", "opt_out_checked", "has_platform", "has_copyright",
        }
        assert expected_flags.issubset(result.keys())

    def test_all_flags_true_when_full(self):
        result = compute(_make_full())
        for flag in ["has_source_url", "has_sha256", "has_author", "has_license_spdx",
                     "ai_status_known", "opt_out_checked", "has_platform", "has_copyright"]:
            assert result[flag] is True, f"Expected {flag} to be True"

    def test_all_flags_false_when_empty(self):
        result = compute({})
        for flag in ["has_source_url", "has_sha256", "has_author", "has_license_spdx",
                     "ai_status_known", "opt_out_checked", "has_platform", "has_copyright"]:
            assert result[flag] is False, f"Expected {flag} to be False"

    def test_score_is_float(self):
        result = compute(_make_full())
        assert isinstance(result["score"], float)
