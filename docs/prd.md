# Product Requirements Document — Final
## AI Data Provenance Collector

**Author:** Alan  
**Date:** 2026-05-18  
**Status:** Final, post agent-driven review  
**Branch:** `claude/automate-data-provenance-y8bYZ`

---

## 1. Vision

Every digital asset Alan downloads becomes a fully-documented, auditable provenance record — automatically, with near-zero added friction — so that any AI model trained on his datasets can be defended end-to-end: who made the image, where it came from, what license applies, whether the creator opted out of AI training, and whether the image is itself AI-generated.

The product is a local-first **macOS / Linux desktop app** (Tauri shell, React + TypeScript frontend, FastAPI + Python backend) with an Apple-clean UI. All data is stored locally. No cloud account is required.

---

## 2. Problem & Why Now

### The problem
Alan downloads images from many sources — Google Images, CivitAI, ArtStation, DeviantArt, Pixiv, Unsplash, Pexels, Shutterstock, social media — for LoRA model training and reference. Today there is no systematic record of:

- Where each file came from
- Who created it
- What license or rights apply
- Whether the source has changed or removed the asset
- Whether the creator has opted out of AI training
- Whether the image is itself AI-generated

### Why now
- Regulatory pressure (EU AI Act Article 53, US AI legislation, copyright class actions) is making training-dataset provenance auditable, not optional
- Industry standards have matured in the last 18 months: **C2PA v2.4** is shipping in Adobe Firefly, OpenAI, Microsoft products; **IPTC 2025.1** adds four AI-specific metadata fields; **Spawning's `ai.txt`** is honored by Stability AI and Hugging Face
- Practitioners have no tool that wires these signals together end-to-end (verified by research)

### What changes for Alan
- Capture happens automatically. He keeps using his browser the way he already does
- Every asset arrives with a colored ring telling him how complete its provenance is
- An audit screen surfaces gaps — files needing manual review — without him having to look for them
- A C2PA badge tells him at a glance whether an image is AI-generated
- An opt-out indicator tells him whether the creator said "don't train on this"

---

## 3. Users & Use Cases

### Primary user — Alan
- Solo practitioner on macOS (and possibly Linux later)
- Downloads via Chrome / Edge primarily, sometimes via direct URL
- Trains LoRA models in batches; revisits old datasets weeks later
- Comfortable with CLI but wants a GUI for daily work

### Use cases — MVP

| # | Use case | Frequency |
|---|---|---|
| U1 | Save an image in the browser to a watched folder; capture is automatic | Daily |
| U2 | Provide a direct URL and let the tool download + capture | Several times a week |
| U3 | Open the app, scroll the gallery, click a card to see all provenance | Daily |
| U4 | Open the audit screen to find files missing source URL, author, or license | Weekly |
| U5 | Bulk-enrich an existing folder of previously-downloaded images | Once per project |
| U6 | Manually override or correct a rights field on a specific asset | Occasional |
| U7 | Re-check opt-out and dataset-membership status on a stale record | Monthly |
| U8 | Re-link a moved or renamed file to its existing provenance record by SHA256 | Occasional |
| U9 | Export a CSV of the entire collection for review in Sheets | Occasional |

### Use cases — explicitly out of MVP

- Distribute provenance bundles to collaborators
- Sign provenance records cryptographically
- Watch cloud folders (iCloud, Dropbox, OneDrive)
- Browser extension
- Embed AI-training opt-out IPTC fields into Alan's own files

---

## 4. Product Principles

1. **Local-first.** Everything runs on Alan's machine. No account, no cloud sync. External calls are limited to: source-page scraping, platform APIs (Unsplash etc.), Wayback Machine save, Spawning DNTR check — each opt-in-able.
2. **Portable provenance.** Each asset's JSON sidecar lives next to it. Move the file, the provenance moves with it. The SQLite index is a fast cache, not the source of truth.
3. **Standards-first.** When an industry standard exists (C2PA, IPTC 2025.1, XMP, SPDX, `ai.txt`, `tdm-reservation`) the tool reads it directly. Bespoke scraping is the fallback, not the default.
4. **Opportunistic enrichment.** Failure of any single signal never blocks capture. The asset is still recorded; the field is left blank; the completeness ring shows the gap.
5. **Honest about uncertainty.** Aggregators (Pinterest, Google Images CDN) are tagged `source_reliability: aggregator`, not treated as authoritative. Unknown fields are `null`, never invented.
6. **Apple-clean UI.** Generous whitespace, system fonts, monochrome with single accent, frosted-glass vibrancy, spring motion. Comfort and clarity over density.

---

## 5. Functional Requirements

### 5.1 Capture (Must)

| ID | Requirement | Detail |
|---|---|---|
| F1 | SHA256 hash at capture time | Computed by streaming, never holds whole file in memory |
| F2 | File metadata | filename, path, size, mime, captured_at, downloaded_at |
| F3 | Direct download | `download <url>` CLI / `/capture` API |
| F4 | Folder scan | `scan <path>` recursive, with `--skip-existing` and `--force` |
| F5 | Watch folder daemon | Real-time capture, multi-folder, configurable in Settings |
| F6 | Chrome/Edge browser-history lookup | Match by filename + ±120s of file mtime; parameterised SQL |
| F7 | Firefox browser-history lookup | `places.sqlite` schema, both v75+ and older formats |
| F8 | EXIF extraction | Public Pillow `getexif()`, `with` blocks; PNG `tEXt` + XMP also |
| F9 | XMP extraction | `python-xmp-toolkit` — `dc:creator`, `dc:rights`, `xmpRights:UsageTerms`, `xmpRights:WebStatement`, `xmpRights:Owner`, `plus:DataMining` |
| F10 | IPTC extraction | `IPTCInfo3` for IIM (JPEG); XMP-encoded IPTC via XMP toolkit; **including IPTC 2025.1 AI fields** (`DigitalSourceType`, `AIPrompt`, `AISystemUsed`, `AIPromptWriterName`) |
| F11 | C2PA manifest reading | `c2pa-python` library; `manifest_present`, `ai_generated`, `creator_tool`, `actions`, `ingredients`, `validation_status` |
| F12 | Source-page scraping | OpenGraph, Schema.org `@graph` arrays, Twitter Card, `<link rel="license">`, `<meta name="copyright">`; CC regex restricted to `<a>`, `<link rel>`, `<meta>` content (not full HTML) |
| F13 | Platform API enrichment | Unsplash, Pexels, Flickr, ArtStation, DeviantArt, Pixiv, CivitAI — called only when `detect_platform()` matches |
| F14 | Google Images original-URL extraction | Parse `imgurl=` and `imgrefurl=` from referrer/tab_url |
| F15 | AI training opt-out detection | `ai.txt`, `tdm-reservation` HTTP header, `robots.txt` AI clauses, IPTC `Data Mining` field |
| F16 | Wayback Machine archival | POST to `https://web.archive.org/save/<url>`; record permalink; rate-limited per source domain |
| F17 | License → SPDX normalization | Static mapping table covering CC variants, public domain, Unsplash/Pexels licenses |
| F18 | Source-reliability flag | `primary | aggregator | unknown` |
| F19 | Completeness score | Pure function over the record; weighted 0–1 |

### 5.2 Storage & Outputs (Must)

| ID | Requirement | Detail |
|---|---|---|
| F20 | JSON sidecar per asset | `<image>.provenance.json` alongside file; portable; schema v2.0 |
| F21 | SQLite index | `~/.provenance/index.sqlite`; fast queries; FTS5 search; thumbnails referenced |
| F22 | CSV export | On-demand, derived from the index; openable in Sheets |
| F23 | Schema versioning | `schema_version: "2.0"` field; non-destructive migration from `1.0` (originals backed up to `.v1backup`) |
| F24 | Thumbnails | 256px WebP cached at `~/.provenance/thumbnails/<sha256>.webp` |

### 5.3 Maintenance & Re-validation (Must)

| ID | Requirement | Detail |
|---|---|---|
| F25 | `enrich` command | Back-fills any missing field (not only source URL); `--force` re-runs everything |
| F26 | `relink` command | Re-attaches sidecars to moved/renamed files by SHA256 |
| F27 | `recheck` command | Re-runs opt-out + dataset-membership + Wayback checks |
| F28 | `migrate` command | One-shot upgrade of v1.0 sidecars to v2.0 |
| F29 | `--dry-run` flag | On `scan`, `enrich`, `migrate`, `recheck` — preview what would change without writing |
| F30 | Audit / gap report | Lists files missing key fields; available as CLI command and UI screen |

### 5.4 Dataset membership (Should — P1)

| ID | Requirement | Detail |
|---|---|---|
| F31 | Spawning DNTR check | API call by SHA256; cached 7 days; opt-in via Settings |
| F32 | LAION-5B membership check | Via local `clip-retrieval` index if configured; P2, deferrable |

### 5.5 Frontend — Tauri Desktop App (Must)

| ID | Requirement | Detail |
|---|---|---|
| F33 | Gallery screen | Masonry grid, thumbnails, completeness rings, filters (platform, AI status, license, opt-out), search (filename / hash / URL), sort |
| F34 | Detail screen | Full provenance for one asset; image preview; C2PA badge; source card with Wayback link; rights card with SPDX badge; opt-out card; embedded-metadata accordion; capture timeline; inline editing |
| F35 | Audit screen | Gap report; filters; bulk actions (Enrich selected, Re-check, Export CSV); header summary cards |
| F36 | Live Activity screen | WebSocket stream of capture events; status banner |
| F37 | Settings | Watch folders, browser profile paths, API keys, Wayback toggle, theme, CSV export path |
| F38 | App shell | Sidebar nav (Gallery / Audit / Activity / Settings), title bar with search and status, vibrancy effects |

### 5.6 Non-Functional

| ID | Requirement | Target |
|---|---|---|
| N1 | Provenance capture latency | ≤ 5s p95 from watch event (excluding scrape + archival; those are async) |
| N2 | Gallery query latency | ≤ 100ms p95 at 10k indexed assets |
| N3 | Scan throughput | ≥ 1000 images / minute on a recent Mac (SHA256-bound) |
| N4 | File-descriptor hygiene | No leak; scan of 10k files succeeds on default `ulimit` |
| N5 | macOS Full Disk Access | Required for browser history; clearly documented; graceful error if missing |
| N6 | Network failures | Capture still succeeds with `null` fields; failed enrichment retries up to 3× with backoff |
| N7 | Schema migration | 100% non-destructive; originals retained as `.v1backup` |

---

## 6. Data Model — v2.0

See `docs/comprehensive-plan.md §3` for the full JSON schema.

Top-level keys:

```
schema_version       "2.0"
capture              { captured_at, downloaded_at, tool_version }
file                 { filename, filepath, sha256, size_bytes, mime_type }
source               { url, source_page, domain, platform, source_reliability,
                       browser_history, wayback_snapshot_url }
creator              { author, profile_url, platform_handle }
rights               { license_spdx, license_text, license_url,
                       copyright_notice, copyright_holder, copyright_year,
                       ai_training_opt_out, model_release_status }
embedded_metadata    { exif, iptc, xmp }
c2pa                 { manifest_present, ai_generated, creator_tool,
                       actions, ingredients, validation_status }
platform_specific    { civitai, artstation, pixiv, unsplash, ... }
training_dataset_membership { checked_at, laion_5b, spawning }
completeness         { score, has_*, ai_status_known, opt_out_checked }
```

Migration from v1.0:
- `file.downloaded_at` → `capture.downloaded_at`
- New `capture.captured_at` set to migration time
- All other fields kept; new fields default to `null`
- Original sidecar moved to `<image>.provenance.json.v1backup`

---

## 7. User Flows

### Flow A — Browser save (most common)
1. Alan saves an image from his browser into a watched folder
2. Within 1s, the watchdog notices the new file
3. Backend computes hash, reads embedded metadata, looks up Chrome history, scrapes source page, checks opt-out, archives to Wayback, checks dataset membership, writes sidecar + index
4. Within 5s (excluding async network calls), the asset appears in the Gallery with a completeness ring
5. Activity feed streams progress in real time

### Flow B — Direct URL
1. Alan pastes a URL into the "Capture" action, or runs `provenance download <url>`
2. Backend fetches the image, then runs the same pipeline
3. The image is saved into the default capture folder; provenance is attached

### Flow C — Batch back-fill
1. Alan points the tool at a folder of existing images
2. Backend runs `scan` over every file; `--skip-existing` avoids re-hashing files that already have a v2.0 sidecar
3. Browser history is queried by file mtime for each file
4. Progress shown in the Activity feed

### Flow D — Audit and fix
1. Alan opens Audit, filters to "missing license"
2. Selects 12 files → Bulk action "Re-enrich (force)" → backend retries with full pipeline
3. Remaining files flagged for manual review
4. Alan clicks one, opens Detail, manually sets `license_spdx` to `CC-BY-4.0`

### Flow E — Re-link moved files
1. Alan moved a folder; the sidecars came along but the SQLite index has stale paths
2. `provenance relink <new-folder>` rehashes files and matches them to existing sidecars by SHA256, updating the index

---

## 8. Success Metrics

| Metric | Target | How measured |
|---|---|---|
| Source URL captured at download time (CLI / API path) | 100% | Unit test asserts presence on every `download` |
| Source URL captured for browser-saved images | ≥ 90% (Chrome closed, history ≤ 7d old, not renamed pre-scan) | Manual corpus of 50 known-source downloads; nightly CI assertion |
| Provenance capture latency | ≤ 5s p95 (sync portion) | `tests/perf/` benchmarks |
| Gallery query latency | ≤ 100ms p95 at 10k assets | `pytest-benchmark` |
| Completeness ≥ 0.7 for assets from primary platforms | ≥ 80% (CivitAI, Unsplash, Pexels, ArtStation) | Weekly canary capture set |
| AI-generation status known | ≥ 90% of assets from C2PA-supporting sources | Same canary set |
| Schema migrations | 100% non-destructive | Migration test on synthetic v1.0 corpus |

---

## 9. Risks & Open Decisions

### Risks
| Risk | Mitigation |
|---|---|
| `python-xmp-toolkit` requires `libexempi` system install | Document `brew install exempi`; fall back to `exiftool` subprocess if missing |
| `c2pa-python` ABI mismatch on Python upgrade | Pin Python 3.11; CI matrix 3.11/3.12 |
| Spawning DNTR API intermittent (maintenance mode observed mid-2026) | try/except wrap; cache last result; mark `checked_at` |
| Wayback rate-limited (~15 req/min/IP) | Per-domain queue; opportunistic batch; surface backlog in UI |
| Tauri notarisation pipeline non-trivial on macOS | Rehearse early in Phase 2; budget time for Apple Developer setup |

### Decisions deferred to Alan (Phase 1 kickoff)
1. Initial watched folders (single vs. multiple)?
2. Willing to register for free API keys (Unsplash, Pexels, CivitAI, Spawning)?
3. Wayback archival default-on or opt-in per domain?
4. `.v1backup` retention — keep indefinitely or auto-prune after 90 days?
5. Distribute as local dev build, or signed Mac DMG from Phase 3?

---

## 10. Non-Goals (MVP)

- Cloud sync, cloud account, sharing collaborators
- Video, audio, PDF, text dataset support
- Automatic enforcement (blocking files flagged opt-out)
- Browser extension (deferred — addresses Safari and private windows)
- Watermark detection
- Face / person detection for model release flagging
- Wikidata artist cross-referencing
- Public-key signing of sidecars

These are tracked in `docs/comprehensive-plan.md §14` for post-MVP.
