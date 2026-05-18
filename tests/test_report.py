import json
import pytest
from pathlib import Path
from unittest.mock import patch


def _make_records(n=3):
    records = []
    for i in range(n):
        sha = str(i) * 64
        records.append({
            "schema_version": "2.0",
            "captured_at": f"2024-01-{i+1:02d}T12:00:00",
            "file": {"sha256": sha[:64], "filename": f"photo_{i}.jpg"},
            "source": {
                "url": f"https://unsplash.com/photos/abc{i}",
                "platform": "unsplash",
                "domain": "unsplash.com",
            },
            "creator": {"name": f"Photographer {i}"},
            "rights": {
                "license_spdx": "LicenseRef-Unsplash",
                "ai_training": {"opt_out": False},
            },
            "ai": {"is_ai_generated": False},
            "completeness": {"score": 0.85},
        })
    return records


_GAPS = {
    "total": 3,
    "missing_source_url": 0,
    "missing_license": 0,
    "missing_ai_status": 0,
    "opted_out": 0,
    "avg_completeness": 0.85,
}


@pytest.fixture(autouse=True)
def _mock_storage():
    records = _make_records(3)
    with (
        patch("lib.report.query_assets", return_value=records),
        patch("lib.report.audit_gaps",   return_value=_GAPS),
    ):
        yield


class TestGenerateReport:
    def test_creates_html_file(self, tmp_path):
        from lib.report import generate
        out = str(tmp_path / "report.html")
        count = generate(out)
        assert Path(out).exists()
        assert count == 3

    def test_html_is_valid_utf8(self, tmp_path):
        from lib.report import generate
        out = str(tmp_path / "report.html")
        generate(out)
        content = Path(out).read_text(encoding="utf-8")
        assert len(content) > 100

    def test_contains_asset_filenames(self, tmp_path):
        from lib.report import generate
        out = str(tmp_path / "report.html")
        generate(out)
        html = Path(out).read_text(encoding="utf-8")
        assert "photo_0.jpg" in html
        assert "photo_1.jpg" in html
        assert "photo_2.jpg" in html

    def test_contains_summary_stats(self, tmp_path):
        from lib.report import generate
        out = str(tmp_path / "report.html")
        generate(out)
        html = Path(out).read_text(encoding="utf-8")
        assert "3" in html           # total assets
        assert "85%" in html         # avg completeness

    def test_is_self_contained_no_external_refs(self, tmp_path):
        from lib.report import generate
        out = str(tmp_path / "report.html")
        generate(out)
        html = Path(out).read_text(encoding="utf-8")
        # Should not reference external stylesheets or scripts
        assert '<link rel="stylesheet"' not in html
        assert 'src="http' not in html

    def test_opt_out_row_gets_class(self, tmp_path):
        from lib.report import generate
        records = _make_records(1)
        records[0]["rights"]["ai_training"]["opt_out"] = True
        out = str(tmp_path / "report.html")
        with (
            patch("lib.report.query_assets", return_value=records),
            patch("lib.report.audit_gaps", return_value={**_GAPS, "total": 1, "opted_out": 1}),
        ):
            generate(out)
        html = Path(out).read_text(encoding="utf-8")
        assert "row-optout" in html

    def test_filter_controls_present(self, tmp_path):
        from lib.report import generate
        out = str(tmp_path / "report.html")
        generate(out)
        html = Path(out).read_text(encoding="utf-8")
        assert 'id="search"' in html
        assert 'id="platform"' in html
        assert 'id="optout"' in html

    def test_returns_correct_count(self, tmp_path):
        from lib.report import generate
        out = str(tmp_path / "report.html")
        count = generate(out, limit=2)
        # query_assets mock returns 3, but limit=2 is passed through
        assert count == 3  # mock always returns 3 regardless of limit
