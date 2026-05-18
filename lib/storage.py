"""
Persist provenance records in two places:
  1. <image>.provenance.json  — portable sidecar alongside the image
  2. ~/.provenance/index.sqlite — fast queryable index

CSV is a derived export, not the primary store.
"""

import csv
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from lib.constants import INDEX_DB, SCHEMA_VERSION

_CSV_FIELDS = [
    "captured_at", "filename", "sha256", "size_bytes", "mime_type",
    "width", "height", "source_url", "page_url", "platform", "domain",
    "author", "license_spdx", "license_url", "copyright",
    "ai_generated", "training_opt_out", "completeness",
    "filepath", "sidecar_path",
]

_DDL = """
CREATE TABLE IF NOT EXISTS assets (
    sha256          TEXT PRIMARY KEY,
    filename        TEXT NOT NULL,
    filepath        TEXT,
    captured_at     TEXT,
    platform        TEXT,
    source_url      TEXT,
    license_spdx    TEXT,
    completeness    REAL,
    ai_generated    INTEGER,
    training_opt_out INTEGER,
    json_blob       TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS assets_fts USING fts5(
    sha256, filename, source_url, author, license_spdx,
    content='assets', content_rowid='rowid'
);
CREATE TRIGGER IF NOT EXISTS assets_ai AFTER INSERT ON assets BEGIN
    INSERT INTO assets_fts(rowid, sha256, filename, source_url, author, license_spdx)
    VALUES (new.rowid, new.sha256, new.filename, new.source_url,
            json_extract(new.json_blob, '$.creator.name'),
            new.license_spdx);
END;
CREATE TRIGGER IF NOT EXISTS assets_au AFTER UPDATE ON assets BEGIN
    INSERT INTO assets_fts(assets_fts, rowid, sha256, filename, source_url, author, license_spdx)
    VALUES ('delete', old.rowid, old.sha256, old.filename, old.source_url,
            json_extract(old.json_blob, '$.creator.name'), old.license_spdx);
    INSERT INTO assets_fts(rowid, sha256, filename, source_url, author, license_spdx)
    VALUES (new.rowid, new.sha256, new.filename, new.source_url,
            json_extract(new.json_blob, '$.creator.name'), new.license_spdx);
END;
"""


@contextmanager
def _db():
    INDEX_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(INDEX_DB))
    conn.row_factory = sqlite3.Row
    conn.executescript(_DDL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_sidecar(image_path: str, provenance: dict) -> str:
    """Write <image>.provenance.json and return the sidecar path."""
    path = Path(image_path)
    sidecar = path.with_name(path.stem + ".provenance.json")
    with open(sidecar, "w", encoding="utf-8") as f:
        json.dump(provenance, f, indent=2, ensure_ascii=False, default=str)
    return str(sidecar)


def upsert_asset(provenance: dict, sidecar_path: str) -> None:
    """Insert or replace a provenance record in the SQLite index."""
    file_ = provenance.get("file", {})
    source = provenance.get("source", {})
    rights = provenance.get("rights", {})
    ai = provenance.get("ai", {})

    sha256 = file_.get("sha256", "")
    if not sha256:
        return

    ai_generated = ai.get("is_ai_generated")
    training_opt_out = rights.get("ai_training", {}).get("opt_out")

    blob = json.dumps(provenance, ensure_ascii=False, default=str)
    blob_with_sidecar = json.dumps({**provenance, "_sidecar_path": sidecar_path},
                                   ensure_ascii=False, default=str)

    with _db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO assets
               (sha256, filename, filepath, captured_at, platform, source_url,
                license_spdx, completeness, ai_generated, training_opt_out, json_blob)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                sha256,
                file_.get("filename", ""),
                file_.get("filepath") or str(Path(sidecar_path).parent / file_.get("filename", "")),
                provenance.get("captured_at"),
                source.get("platform"),
                source.get("url"),
                rights.get("license_spdx"),
                provenance.get("completeness", {}).get("score"),
                None if ai_generated is None else int(ai_generated),
                None if training_opt_out is None else int(training_opt_out),
                blob_with_sidecar,
            ),
        )


def persist(image_path: str, provenance: dict) -> str:
    """Write sidecar JSON + upsert to SQLite index. Returns sidecar path."""
    sidecar_path = write_sidecar(image_path, provenance)
    upsert_asset(provenance, sidecar_path)
    return sidecar_path


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_asset(sha256: str) -> Optional[dict]:
    with _db() as conn:
        row = conn.execute(
            "SELECT json_blob FROM assets WHERE sha256 = ?", (sha256,)
        ).fetchone()
    return json.loads(row["json_blob"]) if row else None


def read_sidecar(image_path: str) -> Optional[dict]:
    path = Path(image_path)
    sidecar = path.with_name(path.stem + ".provenance.json")
    if not sidecar.exists():
        return None
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:
        return None


def query_assets(
    platform: Optional[str] = None,
    missing: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Simple filtered query. missing can be: 'source_url','license','author','ai_status'."""
    clauses, params = [], []
    if platform:
        clauses.append("platform = ?")
        params.append(platform)
    if missing == "source_url":
        clauses.append("(source_url IS NULL OR source_url = '')")
    elif missing == "license":
        clauses.append("(license_spdx IS NULL OR license_spdx = '')")
    elif missing == "ai_status":
        clauses.append("ai_generated IS NULL")

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _db() as conn:
        rows = conn.execute(
            f"SELECT json_blob FROM assets {where} ORDER BY captured_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
    return [json.loads(r["json_blob"]) for r in rows]


def search_assets(text: str, limit: int = 50) -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            """SELECT a.json_blob FROM assets a
               JOIN assets_fts f ON a.rowid = f.rowid
               WHERE assets_fts MATCH ?
               ORDER BY rank LIMIT ?""",
            (text, limit),
        ).fetchall()
    return [json.loads(r["json_blob"]) for r in rows]


def audit_gaps() -> dict:
    with _db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        missing_url = conn.execute(
            "SELECT COUNT(*) FROM assets WHERE source_url IS NULL OR source_url = ''"
        ).fetchone()[0]
        missing_license = conn.execute(
            "SELECT COUNT(*) FROM assets WHERE license_spdx IS NULL OR license_spdx = ''"
        ).fetchone()[0]
        missing_ai = conn.execute(
            "SELECT COUNT(*) FROM assets WHERE ai_generated IS NULL"
        ).fetchone()[0]
        opted_out = conn.execute(
            "SELECT COUNT(*) FROM assets WHERE training_opt_out = 1"
        ).fetchone()[0]
        avg_completeness = conn.execute(
            "SELECT AVG(completeness) FROM assets WHERE completeness IS NOT NULL"
        ).fetchone()[0]

    return {
        "total":             total,
        "missing_source_url": missing_url,
        "missing_license":   missing_license,
        "missing_ai_status": missing_ai,
        "opted_out":         opted_out,
        "avg_completeness":  round(avg_completeness or 0, 3),
    }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_csv(csv_path: str) -> int:
    """Export all assets to CSV. Returns row count."""
    with _db() as conn:
        rows = conn.execute("SELECT json_blob FROM assets ORDER BY captured_at").fetchall()

    count = 0
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            prov = json.loads(row["json_blob"])
            file_ = prov.get("file", {})
            source = prov.get("source", {})
            creator = prov.get("creator", {})
            rights = prov.get("rights", {})
            ai = prov.get("ai", {})
            image = prov.get("image", {})
            writer.writerow({
                "captured_at":    prov.get("captured_at", ""),
                "filename":       file_.get("filename", ""),
                "sha256":         file_.get("sha256", ""),
                "size_bytes":     file_.get("size_bytes", ""),
                "mime_type":      file_.get("mime_type", ""),
                "width":          image.get("width", ""),
                "height":         image.get("height", ""),
                "source_url":     source.get("url", ""),
                "page_url":       source.get("page_url", ""),
                "platform":       source.get("platform", ""),
                "domain":         source.get("domain", ""),
                "author":         creator.get("name", ""),
                "license_spdx":   rights.get("license_spdx", ""),
                "license_url":    rights.get("license_url", ""),
                "copyright":      rights.get("copyright", ""),
                "ai_generated":   ai.get("is_ai_generated", ""),
                "training_opt_out": rights.get("ai_training", {}).get("opt_out", ""),
                "completeness":   prov.get("completeness", {}).get("score", ""),
                "filepath":       file_.get("filepath", ""),
                "sidecar_path":   prov.get("_sidecar_path", ""),
            })
            count += 1
    return count
