import json
import os
import tempfile
import pytest
from pathlib import Path
from PIL import Image
from unittest.mock import patch


def _make_provenance(sha256="abc123def456abc123def456abc123def456abc123def456abc123def456abc1"):
    return {
        "schema_version": "2.0",
        "captured_at": "2024-01-15T12:00:00",
        "file": {
            "sha256": sha256,
            "filename": "test.jpg",
            "filepath": "/tmp/test.jpg",
            "size_bytes": 1024,
            "mime_type": "image/jpeg",
        },
        "source": {"url": "https://example.com/img.jpg", "platform": "unsplash"},
        "creator": {"name": "Jane Doe"},
        "rights": {
            "license_spdx": "CC-BY-4.0",
            "ai_training": {"opt_out": False},
        },
        "ai": {"is_ai_generated": False},
        "completeness": {"score": 0.9},
    }


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.sqlite"
    monkeypatch.setattr("lib.storage.INDEX_DB", db_path)


class TestWriteSidecar:
    def test_creates_json_file(self, tmp_path):
        from lib.storage import write_sidecar
        img = tmp_path / "photo.jpg"
        img.touch()
        prov = _make_provenance()
        sidecar = write_sidecar(str(img), prov)
        assert Path(sidecar).exists()
        assert sidecar.endswith("photo.provenance.json")

    def test_json_is_valid(self, tmp_path):
        from lib.storage import write_sidecar
        img = tmp_path / "photo.jpg"
        img.touch()
        sidecar = write_sidecar(str(img), _make_provenance())
        data = json.loads(Path(sidecar).read_text())
        assert data["schema_version"] == "2.0"


class TestUpsertAndGet:
    def test_roundtrip(self, tmp_path):
        from lib.storage import upsert_asset, get_asset
        prov = _make_provenance()
        upsert_asset(prov, "/tmp/test.provenance.json")
        result = get_asset(prov["file"]["sha256"])
        assert result is not None
        assert result["file"]["sha256"] == prov["file"]["sha256"]

    def test_upsert_skips_missing_sha256(self, tmp_path):
        from lib.storage import upsert_asset, get_asset
        prov = _make_provenance()
        prov["file"]["sha256"] = ""
        upsert_asset(prov, "/tmp/test.provenance.json")
        # No row should be inserted
        result = get_asset("")
        assert result is None

    def test_replace_on_duplicate_sha256(self, tmp_path):
        from lib.storage import upsert_asset, get_asset
        sha = "a" * 64
        prov1 = _make_provenance(sha)
        prov1["source"]["url"] = "https://first.example.com/"
        upsert_asset(prov1, "/tmp/1.provenance.json")

        prov2 = _make_provenance(sha)
        prov2["source"]["url"] = "https://second.example.com/"
        upsert_asset(prov2, "/tmp/2.provenance.json")

        result = get_asset(sha)
        assert result["source"]["url"] == "https://second.example.com/"


class TestQueryAssets:
    def test_query_by_platform(self, tmp_path):
        from lib.storage import upsert_asset, query_assets
        prov = _make_provenance()
        upsert_asset(prov, "/tmp/test.provenance.json")
        rows = query_assets(platform="unsplash")
        assert any(r["source"]["platform"] == "unsplash" for r in rows)

    def test_query_missing_license(self, tmp_path):
        from lib.storage import upsert_asset, query_assets
        sha = "b" * 64
        prov = _make_provenance(sha)
        del prov["rights"]["license_spdx"]
        upsert_asset(prov, "/tmp/test.provenance.json")
        rows = query_assets(missing="license")
        shas = [r["file"]["sha256"] for r in rows]
        assert sha in shas


class TestAuditGaps:
    def test_empty_db(self, tmp_path):
        from lib.storage import audit_gaps
        result = audit_gaps()
        assert result["total"] == 0
        assert result["avg_completeness"] == 0.0

    def test_counts_increase_after_insert(self, tmp_path):
        from lib.storage import upsert_asset, audit_gaps
        upsert_asset(_make_provenance(), "/tmp/test.provenance.json")
        result = audit_gaps()
        assert result["total"] == 1


class TestPersist:
    def test_persist_creates_sidecar_and_indexes(self, tmp_path):
        from lib.storage import persist, get_asset
        img = tmp_path / "photo.jpg"
        img.touch()
        prov = _make_provenance()
        sidecar = persist(str(img), prov)
        assert Path(sidecar).exists()
        assert get_asset(prov["file"]["sha256"]) is not None
