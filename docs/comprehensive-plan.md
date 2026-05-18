# AI Data Provenance Collector — Comprehensive MVP Plan

**Author:** Alan  
**Date:** 2026-05-18  
**Status:** Comprehensive plan, post-review  
**Branch:** `claude/automate-data-provenance-y8bYZ`

---

## 0. Executive Summary

A local-first, Tauri-based desktop application that automatically captures and curates provenance metadata for every digital asset Alan downloads — primarily for AI LoRA training, secondarily for any digital asset.

The product is built in three layers:

1. **Python core** — capture engine (download, scan, watch, enrich) with file-, page-, and platform-level metadata extraction, including industry standards (C2PA, IPTC 2025.1, XMP) and rights-aware signals (AI opt-out, Wayback archive, dataset membership).
2. **FastAPI local server** — exposes the core as REST + WebSocket APIs for the frontend.
3. **Tauri desktop app** — native macOS/Linux shell wrapping a React frontend with Apple-style high-end UI (Gallery, Provenance Detail, Audit, Live Activity).

---

## 1. Context & Why

Alan downloads digital assets (images, illustrations, photographs, reference files) from many sources (Google Images, CivitAI, ArtStation, DeviantArt, Pixiv, Unsplash, Pexels, Shutterstock, social media). He needs an auditable record of where each file came from, who created it, and what rights apply — both to make individual rights judgements and to be able to demonstrate provenance for any model trained on the dataset.

Current state on `claude/automate-data-provenance-y8bYZ`:

- CLI works for download / scan / watch / enrich / history
- JSON sidecar + CSV log per asset
- EXIF, OpenGraph, Schema.org, CC license scraping
- Chrome / Edge browser-history lookup (with Google Images `imgurl` extraction)

Four parallel agent reviews surfaced major gaps; this plan addresses them.

---

## 2. Open-Source Standards & Datasets Integration

The single biggest improvement to the existing tool is to read and write the real industry standards. Findings from the standards research:

| Standard / Source | What it provides | Library | Priority |
|---|---|---|---|
| **C2PA / Content Credentials** | Cryptographically signed manifests embedded in image files — declares AI-generation status, edit history, source ingredients. Adopted by Adobe Firefly, Midjourney, OpenAI, camera makers. | `c2pa-python` (pip) | **P0** |
| **IPTC 2025.1 Photo Metadata** | Industry-standard rights fields including `Data Mining` (PLUS vocab) and four new AI fields (AI Prompt, AI System Used, AI System Version, AI Prompt Writer). | `IPTCInfo3` (IIM), `python-xmp-toolkit` (XMP-encoded IPTC) | **P0** |
| **XMP (ISO 16684)** | The plumbing that carries IPTC, Dublin Core, `xmpRights` (license, marked, owner, web statement). | `python-xmp-toolkit` (wraps libexempi) | **P0** |
| **ai.txt / `tdm-reservation` HTTP header** | Domain- and image-level AI training opt-out signals. Spawning.ai's standard, honored by Stability AI and HF. | Custom (HTTP HEAD + parse) | **P0** |
| **Wayback Machine Save API** | Permanent snapshot of the source page at capture time — defends against link rot. | `requests` POST to `web.archive.org/save/<url>` | **P0** |
| **Have I Been Trained / Spawning DNTR** | API to check whether an image is in LAION-5B and whether its hash is on the Do Not Train Registry. | `api.spawning.ai` REST | **P1** |
| **CLIP Retrieval (rom1504/clip-retrieval)** | Self-hosted LAION semantic search — local index of LAION Parquet files. | `clip-retrieval` (pip) | **P2** |
| **Wikidata** | Cross-reference artist names against structured entities, look up copyright status (`P6216`), license (`P275`). | `SPARQLWrapper` or REST | **P2** |
| **Platform APIs (Unsplash, Pexels, Flickr, ArtStation, DeviantArt, Pixiv)** | Structured `license`, `photographer`, `is_ai_generated` (Pixiv `ai_type`, ArtStation flag). | Direct REST | **P1** |
| **SPDX License Identifiers** | Canonical short-codes (`CC-BY-4.0`, `CC0-1.0`, etc.) for machine-readable license fields. | Static mapping table | **P0** |

**No open-source tool integrates all of these end-to-end** — that integration is this product's differentiator.

---

## 3. Revised Data Model

Replaces the model in PRD §6. Schema version bumped to **`2.0`**, with a one-time migration of existing `1.0` sidecars.

```jsonc
{
  "schema_version": "2.0",
  "capture": {
    "captured_at":    "2026-05-18T01:11:34Z",   // when provenance was recorded
    "downloaded_at":  "2026-05-15T22:04:11Z",   // file mtime / HTTP date
    "tool_version":   "0.2.0"
  },
  "file": {
    "filename": "...", "filepath": "...",
    "sha256": "...", "size_bytes": 0, "mime_type": "image/jpeg"
  },
  "source": {
    "url": "...", "source_page": "...",
    "domain": "...", "platform": "civitai",
    "source_reliability": "primary | aggregator | unknown",
    "browser_history": { "..." },
    "wayback_snapshot_url": "https://web.archive.org/web/.../..."
  },
  "creator": {
    "author": "...", "profile_url": "...", "platform_handle": "..."
  },
  "rights": {
    "license_spdx":     "CC-BY-4.0",      // canonical
    "license_text":     "Creative Commons Attribution 4.0",
    "license_url":      "...",
    "copyright_notice": "...",
    "copyright_holder": "...",
    "copyright_year":   "2024",
    "ai_training_opt_out": {
      "ai_txt":            true | false | null,
      "tdm_reservation":   1 | 0 | null,
      "iptc_data_mining":  "Prohibited | Prohibited for Generative AI/ML training | null",
      "spawning_dntr":     true | false | null
    },
    "model_release_status": "unknown | required | not_required | on_file"
  },
  "embedded_metadata": {
    "exif": { ... },
    "iptc": { ... },
    "xmp":  { ... }
  },
  "c2pa": {
    "manifest_present": true,
    "ai_generated":     true,
    "creator_tool":     "Adobe Firefly",
    "actions":          [...],
    "ingredients":      [...]
  },
  "platform_specific": {
    "civitai":   { ... },
    "artstation":{ "is_ai_generated": false, "medium": "Digital 2D" },
    "pixiv":     { "ai_type": 0 },
    "unsplash":  { "license": "...", "photographer": {...} }
  },
  "training_dataset_membership": {
    "checked_at": "2026-05-18T01:11:34Z",
    "laion_5b":   { "found": true,  "score": 0.97 },
    "spawning":   { "in_dntr": false }
  },
  "completeness": {
    "score": 0.85,   // weighted 0–1
    "has_source_url": true, "has_author": true, "has_license_spdx": true,
    "has_sha256": true, "has_xmp": true, "has_iptc": true,
    "has_c2pa": false, "has_wayback": true,
    "ai_status_known": true, "opt_out_checked": true
  }
}
```

Notes:
- `filepath` is documented as a hint, not a hard reference; relinking uses SHA256.
- `captured_at` ≠ `downloaded_at` — fix from the product review.
- `source_reliability` flags aggregators (Pinterest, Google Images CDN) so they don't masquerade as authoritative sources.
- `completeness` is a pure function of the rest of the record; recomputed on every write.

---

## 4. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Tauri 2 Shell  (Rust + native window, signed binary)        │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  React 18 + TypeScript Frontend                       │  │
│  │  ┌──────────┐ ┌──────────┐ ┌─────────┐ ┌──────────┐   │  │
│  │  │ Gallery  │ │  Detail  │ │  Audit  │ │ Activity │   │  │
│  │  └──────────┘ └──────────┘ └─────────┘ └──────────┘   │  │
│  │  TanStack Query · Zustand · Tailwind · shadcn/ui      │  │
│  └────────────────────┬──────────────────────────────────┘  │
└─────────────────────────┼──────────────────────────────────┘
              REST (HTTP) │ WebSocket (live events)
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  FastAPI Server  (Python sidecar, bundled with Tauri)        │
│  /assets  /assets/{id}  /audit  /capture  /enrich            │
│  /ws/activity   /thumbnails/{sha256}                         │
└─────────────────────────┬──────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Core Library  (existing lib/* refactored + new modules)     │
│  lib/                                                        │
│    metadata.py            (existing) hash, EXIF, dimensions  │
│    embedded_metadata.py   (NEW) XMP + IPTC + 2025.1 AI fields│
│    c2pa_reader.py         (NEW) C2PA manifest parsing        │
│    scrapers.py            (refactored) HTML, OG, schema.org  │
│    platform_apis.py       (NEW) Unsplash/Pexels/ArtStation/  │
│                                 Pixiv/Flickr structured calls│
│    opt_out.py             (NEW) ai.txt / tdm-reservation /   │
│                                 Spawning DNTR / robots.txt   │
│    archive.py             (NEW) Wayback save + verify        │
│    license_spdx.py        (NEW) Plain text → SPDX mapping    │
│    dataset_lookup.py      (NEW) HIBT / CLIP retrieval        │
│    browser_history.py     (existing) Chrome / Edge + Firefox │
│    completeness.py        (NEW) Pure scoring function        │
│    storage.py             (refactored) SQLite index + JSON   │
│                                  sidecars + CSV export       │
│    constants.py           (NEW) IMAGE_EXTENSIONS, schema ver │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Local Storage                                               │
│    ~/.provenance/                                            │
│      index.sqlite          (queryable index, fast)           │
│      thumbnails/<sha256>.webp                                │
│      exports/provenance_log.csv  (derived view)              │
│    <user's image folders>/                                   │
│      <image>.provenance.json   (portable, travels w/ file)   │
└─────────────────────────────────────────────────────────────┘
```

**Why SQLite index alongside JSON sidecars:**
- JSON sidecars stay portable (move folder → provenance moves with it)
- SQLite gives the frontend sub-millisecond queries for the gallery and audit views (10k+ assets indexed)
- CSV becomes an export, not the primary store — solves the dedup race condition from the engineering review

---

## 5. Frontend — Apple-Style UI

### 5.1 Stack

- **Tauri 2.x** — Rust shell, system webview, ~5–10MB binary, signed and notarisable for Mac
- **React 18 + TypeScript** — strict mode
- **Tailwind CSS 3** + **shadcn/ui** — built on Radix primitives, accessibility-first, Apple-clean defaults
- **TanStack Query** — async data, optimistic updates, cache
- **Zustand** — small global state (selected asset, filters)
- **Framer Motion** — spring animations
- **Lucide React** — icon set (matches SF Symbols aesthetic)

### 5.2 Design Language — "Apple-clean"

- **Typography:** System font stack (`-apple-system, BlinkMacSystemFont, "SF Pro Text", Inter`). Six type tokens: `display-2xl` (32/40), `display-xl` (24/32), `title` (17/24 semibold), `body` (15/22), `caption` (13/18), `mono` (13/18 SF Mono).
- **Color:** Monochrome neutrals + single accent.
  - Light: `#FFFFFF` surface, `#F5F5F7` panel, `#1D1D1F` text, `#86868B` muted, **accent `#007AFF`**.
  - Dark: `#000000` surface, `#1C1C1E` panel, `#F5F5F7` text, `#8E8E93` muted, **accent `#0A84FF`**.
  - Semantic: `#34C759` success, `#FF9F0A` warning, `#FF453A` danger.
- **Spacing:** 4px grid (2/4/8/12/16/24/32/48/64).
- **Radius:** 6px controls, 12px cards, 20px sheets, 999px chips.
- **Elevation:** 4 layers — Surface, Panel, Floating (8px blur), Modal (32px blur + 80% backdrop).
- **Effects:** `backdrop-filter: blur(20px) saturate(180%)` on top bar and sheets — the Mac "vibrancy" look.
- **Motion:** All transitions ≤ 250ms, ease-out for enter, ease-in for exit. Spring physics (`stiffness 300, damping 30`) for panels.
- **Empty states:** Centered icon (32px, muted), one-line headline, one-line body, single primary action.
- **Density:** Generous whitespace. Gallery card minimum 240px wide, sheet minimum 480px.

### 5.3 App Shell

```
┌─ Title bar (vibrancy, traffic lights left, search center) ──┐
├──────────────────┬──────────────────────────────────────────┤
│  Sidebar (240px) │  Main pane                                │
│  ◉ Gallery       │                                           │
│  ⚠ Needs Review  │                                           │
│  📊 Audit         │                                           │
│  ⚡ Activity      │                                           │
│  ─────           │                                           │
│  📁 Folders      │                                           │
│   ▸ LoRA-Faces   │                                           │
│   ▸ References   │                                           │
│  ─────           │                                           │
│  ⚙ Settings      │                                           │
└──────────────────┴──────────────────────────────────────────┘
```

### 5.4 The Four MVP Screens

**1. Gallery (default)**

- Masonry grid, 4 columns ≥1280px / 3 ≥960px / 2 ≥640px / 1 below
- Each card: thumbnail (webp from cache), filename caption, platform badge, **completeness ring** (0–100% with color: red < 0.4, amber < 0.7, green ≥ 0.7)
- Hover: subtle lift (scale 1.02, shadow), source URL tooltip
- Top toolbar: search (filename, hash, URL), filter chips (platform, has-license, has-author, completeness, ai-generated, opt-out), sort (recent, completeness, platform), refresh
- Click card → opens Detail in slide-in sheet from right (60% width); cmd-click → full-page detail

**2. Provenance Detail (sheet or full page)**

Three-column layout in full page; single-column stacked in sheet.

- **Header:** filename, SHA256 (mono, copy button), completeness ring, action menu (re-enrich, re-archive, re-check dataset, open in Finder)
- **Left:** large image preview, dimensions, file size, mime type, **C2PA badge** if manifest present (with AI-generated chip)
- **Middle:** Source card (URL, page, platform, Wayback snapshot link with capture time, browser-history record). Creator card. Rights card with SPDX badge.
- **Right:** AI-status card (opt-out signals: ai.txt, tdm-reservation, IPTC data-mining, Spawning DNTR). Dataset membership card (LAION-5B match, Spawning result). Embedded metadata accordion (EXIF / IPTC / XMP / C2PA actions). Capture chronology timeline.
- Inline editing on rights fields (license SPDX picker, copyright override) — writes to sidecar + index

**3. Audit / Gap Report**

- Two-pane: filter sidebar (240px) + table.
- Filters: missing SHA256, missing source URL, missing author, missing license, no AI status, no opt-out check, no Wayback snapshot, completeness < threshold.
- Table columns: thumbnail · filename · platform · missing fields (chips) · completeness · last captured · actions (Enrich, Re-check).
- Bulk actions: Enrich selected, Re-check dataset membership, Export gap CSV.
- Header summary cards: total assets, % complete, missing source URL count, AI-generated count, opt-out flagged count.

**4. Live Activity Feed**

- WebSocket-driven (`/ws/activity`).
- Vertical stream of cards as events arrive: download started → page scraped → C2PA parsed → opt-out checked → archived → sidecar written.
- Each card shows step icon, status (running / done / failed), elapsed time, brief detail.
- Top: status banner (idle / watching <folder> / processing N assets).
- Auto-scrolls; pin button to lock; clear button.

### 5.5 Settings

- Watch folders (multi-folder selection)
- Browser profile paths (auto-detected, override-able)
- API keys: Spawning, CivitAI (optional)
- Wayback enable/disable (rate-limited per source domain)
- LAION local index path (optional, P2)
- Theme (system / light / dark)
- CSV export path

### 5.6 Frontend File Layout

```
ui/                              (Tauri project root)
  src-tauri/                     (Rust shell)
    tauri.conf.json
    src/main.rs                  (sidecar lifecycle for FastAPI)
  src/
    App.tsx
    routes/
      Gallery.tsx
      Detail.tsx
      Audit.tsx
      Activity.tsx
      Settings.tsx
    components/
      ui/                        (shadcn components)
      AssetCard.tsx
      CompletenessRing.tsx
      PlatformBadge.tsx
      RightsBadge.tsx
      C2paBadge.tsx
      MetadataAccordion.tsx
      Sidebar.tsx
      Titlebar.tsx
    lib/
      api.ts                     (typed REST client)
      ws.ts                      (WebSocket client)
      types.ts                   (mirrors provenance schema)
    styles/
      globals.css                (Tailwind)
  package.json
  tailwind.config.ts
  tsconfig.json
```

---

## 6. Backend API (FastAPI)

```
GET    /assets                   ?platform=...&missing=author&limit=50&offset=0
GET    /assets/{sha256}
PATCH  /assets/{sha256}          (manual edits to rights/creator)
DELETE /assets/{sha256}          (removes from index, leaves files)

GET    /audit                    (aggregate gap stats)
POST   /audit/export             (gap CSV)

POST   /capture                  { url, source_page?, dest_dir? }
POST   /enrich                   { path? | sha256?, force?: bool }
POST   /scan                     { dir, recursive }

POST   /watch                    { dir }
DELETE /watch                    { dir }
GET    /watch                    (list active watches)

GET    /thumbnails/{sha256}.webp
GET    /history                  (browser history matches, debug)

WS     /ws/activity              (event stream: capture, scrape, archive, etc.)
WS     /ws/watch                 (folder watcher notifications)
```

All endpoints return the v2.0 schema; the frontend has a TypeScript type generator that mirrors it (`pydantic_to_typescript`).

---

## 7. Backend Module Plans

### 7.1 New modules

**`lib/embedded_metadata.py`**
- Reads XMP via `python-xmp-toolkit` (libexempi)
- Reads IPTC via `IPTCInfo3` (JPEG IIM); XMP-encoded IPTC via XMP toolkit
- Maps fields to canonical schema:
  - `Xmp.dc.creator` → `creator.author`
  - `Xmp.dc.rights` / `Iptc.Application2.CopyrightNotice` → `rights.copyright_notice`
  - `Xmp.xmpRights.UsageTerms` → `rights.license_text`
  - `Xmp.xmpRights.WebStatement` → `rights.license_url`
  - `Xmp.plus.DataMining` → `rights.ai_training_opt_out.iptc_data_mining`
  - IPTC 2025.1: `Xmp.Iptc4xmpExt.DigitalSourceType`, `Xmp.iptcExt.AIPrompt`, etc. → `c2pa.ai_generated` and `platform_specific.iptc_ai`

**`lib/c2pa_reader.py`**
- Wraps `c2pa-python` Reader
- Returns `{ manifest_present, ai_generated, creator_tool, actions, ingredients }`
- Validates signature; on invalid, sets `c2pa_validation_status: "invalid"` (still records the manifest content)

**`lib/platform_apis.py`**
- One function per platform; lazily called only when `detect_platform()` matches
- `unsplash(image_id, api_key)` → `GET /photos/<id>` → license, photographer, exif
- `pexels(image_id, api_key)` → `GET /v1/photos/<id>`
- `flickr(photo_id, api_key)` → `photos.getInfo` → numeric license code mapped to SPDX
- `artstation(slug)` → `/projects/<slug>.json` → `is_ai_generated`, medium, software_used
- `pixiv(work_id)` → `ai_type` (0/1/2)
- `deviantart(id, api_key)` → license object

**`lib/opt_out.py`**
- `check_ai_txt(domain)` — fetch `https://<domain>/ai.txt`, parse, cache result for 24h
- `check_tdm_reservation(url)` — HEAD request, read `tdm-reservation` header (RFC draft)
- `check_robots_txt_ai(domain)` — look for `GPTBot`, `CCBot`, etc.
- `check_spawning_dntr(sha256)` — POST to Spawning DNTR API (P1, gated behind opt-in)

**`lib/archive.py`**
- `wayback_save(url)` — POST to `https://web.archive.org/save/<url>`, return permalink
- Rate-limited (≤ 1 req / source domain / 60s), respects 429 backoff

**`lib/license_spdx.py`**
- Static mapping of common license strings and URLs to SPDX identifiers
- `to_spdx(text|url) → "CC-BY-4.0" | None`
- Coverage: all Creative Commons variants, Unsplash/Pexels custom licenses, public domain marks (CC0, PDM)

**`lib/dataset_lookup.py`**
- `check_laion_5b(image_path | clip_embedding)` — uses local clip-retrieval index if configured, else returns `unknown`
- `check_spawning(sha256)` — calls Spawning DNTR check
- Cached per-image for 7 days

**`lib/completeness.py`**
- Pure function `score(provenance: dict) -> dict`
- Weighted: source_url 0.20, author 0.10, license_spdx 0.20, sha256 0.10, c2pa 0.10, ai_status_known 0.15, opt_out_checked 0.10, wayback 0.05
- Returns `{ score, has_*, ai_status_known, opt_out_checked }`

**`lib/storage.py` (refactored)**
- Adds SQLite index alongside JSON sidecars
- Schema: `assets(sha256 PK, filepath, captured_at, platform, completeness_score, json_blob)` + FTS5 virtual table for search
- `upsert_asset(provenance)` writes both sidecar and index in a transaction
- CSV becomes a derived export (`export_csv(path)`)

**`lib/constants.py`**
- Single `IMAGE_EXTENSIONS` set (fixes the engineering review's "defined in 3 places")
- `SCHEMA_VERSION = "2.0"`

### 7.2 Refactors to existing modules

| File | Refactor |
|---|---|
| `lib/metadata.py` | Wrap `Image.open` in `with` blocks; switch from `_getexif()` to public `getexif()`; handle PNG `tEXt` / PNG XMP. |
| `lib/scrapers.py` | Parse Schema.org `@graph` arrays (fixes silent drop). Restrict CC regex to `<a>`, `<link rel>`, and `<meta>` content only (no full-page text). Add User-Agent rotation + 429 backoff. |
| `lib/browser_history.py` | Replace f-string SQL with parameterised queries (`?` placeholders). Iterate all history paths in `list_recent_image_downloads`. Add Firefox `places.sqlite` / `moz_annos` reader. |
| `lib/watcher.py` | Replace fixed `sleep(1.0)` with stable-size polling (`size unchanged for 500ms` → ready). |
| `provenance.py` | Split `collect_provenance` into: `gather_signals()`, `resolve_canonical()`, `compute_completeness()`, `persist()`. Add `--dry-run`, `--force`, `--skip-existing` flags. |

### 7.3 New CLI commands

```
provenance audit <path>           — gap report (CLI mirror of UI Audit screen)
provenance relink <path>          — re-attach sidecars to moved/renamed files (by SHA256)
provenance recheck <path>         — re-run opt-out + dataset membership checks
provenance migrate <path>         — upgrade v1.0 sidecars → v2.0
provenance serve                  — start FastAPI server (used by Tauri sidecar)
provenance gui                    — start FastAPI + open Tauri window
```

---

## 8. Implementation Roadmap

Three phases. Each phase ends with a working, dog-foodable state.

### Phase 1 — Backend hardening + standards (1–2 weeks)
Fix the foundation before building UI on it.

| Task | Files |
|---|---|
| Move `IMAGE_EXTENSIONS` to `lib/constants.py` | `constants.py`, refs |
| Fix `metadata.py` (with-blocks, `getexif()`) | `metadata.py` |
| Parameterise SQL in `browser_history.py` | `browser_history.py` |
| Restrict CC regex; parse `@graph`; UA backoff in `scrapers.py` | `scrapers.py` |
| Add `embedded_metadata.py` (XMP + IPTC) | new |
| Add `c2pa_reader.py` | new |
| Add `license_spdx.py` mapping | new |
| Add `opt_out.py` (ai.txt + tdm-reservation + robots ai-clauses) | new |
| Add `archive.py` (Wayback save) | new |
| Add `completeness.py` (pure score) | new |
| Schema v2.0 + `migrate` command | `provenance.py` |
| `relink` command (SHA256 → sidecar) | `provenance.py` |
| Split `collect_provenance`; add `--dry-run`, `--force`, `--skip-existing` | `provenance.py` |
| SQLite index in `storage.py`; CSV becomes export | `storage.py` |
| Firefox history support | `browser_history.py` |
| Test suite: unit + integration with fixture HTML and SQLite | `tests/` |

**Exit criteria:** All CLI commands work on v2.0 schema with new metadata signals; `pytest` green; can scan 10k images without file-descriptor exhaustion.

### Phase 2 — Local API + initial UI (2–3 weeks)

| Task | Files |
|---|---|
| FastAPI app skeleton | `lib/api.py` |
| REST endpoints (`/assets`, `/audit`, `/capture`, `/enrich`, `/scan`) | `lib/api.py` |
| Thumbnail generator (webp, 256px) | `lib/thumbnails.py` |
| WebSocket `/ws/activity` and `/ws/watch` | `lib/api.py` |
| Pydantic models → TypeScript types generator | `lib/api.py` |
| Tauri project scaffolding with FastAPI sidecar | `ui/src-tauri/` |
| Design tokens (Tailwind theme + globals.css) | `ui/src/styles/` |
| shadcn/ui base components | `ui/src/components/ui/` |
| Sidebar + Titlebar + App Shell | `ui/src/components/` |
| Gallery screen (grid + filters + search) | `ui/src/routes/Gallery.tsx` |
| Detail sheet/page (full provenance view) | `ui/src/routes/Detail.tsx` |
| Manual rights editing → PATCH `/assets/{sha256}` | `ui/`, `lib/api.py` |
| Settings (watch folders, API keys) | `ui/src/routes/Settings.tsx` |

**Exit criteria:** Tauri app launches, shows gallery of indexed assets, opens detail panel, allows manual rights edits. App runs on Alan's Mac.

### Phase 3 — Audit, Live Activity, Dataset Lookup (1–2 weeks)

| Task | Files |
|---|---|
| Audit screen (gap report + bulk actions) | `ui/src/routes/Audit.tsx` |
| Live Activity feed (WebSocket consumer) | `ui/src/routes/Activity.tsx` |
| `dataset_lookup.py` — Spawning DNTR | `lib/dataset_lookup.py` |
| Platform API integration (Unsplash, Pexels, ArtStation, Pixiv, Flickr) | `lib/platform_apis.py` |
| CivitAI model/post page enrichment | `lib/scrapers.py` |
| Bulk re-enrich, bulk re-archive (UI + API) | `ui/`, `lib/api.py` |
| App icon + Mac DMG packaging + code-signing pipeline | `ui/src-tauri/` |

**Exit criteria:** Distributable signed Mac `.dmg`. Audit screen surfaces gaps. Activity feed streams live captures.

### Out of scope for MVP (acknowledged, deferred)
- Browser extension (P2 — addresses the cases where browser history is unavailable, e.g. Safari, private windows)
- CLIP retrieval / local LAION index (P2 — requires ~600GB of Parquet data; only useful for power users)
- Watermark detection (P2 — research-grade, false-positive rate too high for MVP)
- Face / person detection for model release flagging (P2 — privacy and accuracy concerns)
- Wikidata artist cross-reference (P2 — high value for catalog work, low value for raw web scraping)

---

## 9. Testing Strategy

| Layer | Tooling | Key cases |
|---|---|---|
| `metadata` | pytest + fixture JPG with known EXIF, PNG with XMP | SHA256 determinism, EXIF extraction, file-handle hygiene |
| `embedded_metadata` | pytest + fixture JPG with embedded IPTC + XMP | All canonical fields mapped; missing fields → `None` not raise |
| `c2pa_reader` | pytest + sample manifests from C2PA test vectors | Valid + invalid + missing manifest cases |
| `scrapers` | `pytest-httpserver` serving controlled HTML | OG tags, schema.org `@graph`, CC false-positive guard |
| `browser_history` | pytest + synthetic Chrome + Firefox SQLite fixtures | Parameterised SQL, time-window matching, multi-profile |
| `storage` | pytest + tmp_path | Sidecar round-trip, SQLite upsert, CSV export, deduplication |
| `opt_out` | `responses` mocks | ai.txt parsing, tdm-reservation header, 24h cache |
| `archive` | `responses` + Wayback save mock | Permalink extraction, rate-limit handling |
| `completeness` | pytest table-driven | Weighted score correctness, all edge cases |
| `api` (FastAPI) | `httpx.AsyncClient` | Endpoint contracts, schema validation, WebSocket events |
| Frontend | Vitest + Testing Library | Components render with mocked API data; type-correctness via `tsc --noEmit` |
| End-to-end | Playwright against Tauri (P1) | Drop image into watch folder → appears in gallery → detail loads |

`pytest -q` should be green before each phase exit.

---

## 10. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `python-xmp-toolkit` requires libexempi system install | High | Medium | Document brew install; fall back to `exiftool` subprocess if missing |
| `c2pa-python` ABI compatibility across Python minor versions | Medium | Medium | Pin Python 3.11; CI matrix across 3.11/3.12 |
| Spawning DNTR API instability (intermittent maintenance) | High | Low | Wrap calls in try/except; cache last result; mark `checked_at` |
| Wayback rate limits (≈ 15 req/min per IP) | High | Medium | Per-domain queue; opportunistic batch; surface backlog in UI |
| Tauri sidecar lifecycle on Mac (notarisation requirements) | Medium | High | Build pipeline must sign+notarise both Rust shell and Python sidecar; CI rehearsal early |
| Schema v2.0 migration corrupts user data | Low | High | Migration is read-only first pass; writes new files alongside v1.0 originals; old files moved to `.v1backup` not deleted |
| `python-xmp-toolkit` lacks Windows support | Medium | Low | MVP is Mac/Linux only — documented; Windows is post-MVP |

---

## 11. Success Metrics

Replaces PRD §9. Each metric defined with measurement procedure.

| Metric | Target | How measured |
|---|---|---|
| Source URL captured at download time | 100% of `download` invocations | Unit: every test in `test_provenance_download.py` asserts presence |
| Source URL captured for browser-saved images | ≥ 90% when Chrome history is present (≤ 7 days old, Chrome closed) | Manual test corpus of 50 known-source downloads; assertion in CI nightly |
| Provenance gathered within 5s of watch event | ≥ 95% (excluding network-bound scraping + archival) | Benchmark suite in `tests/perf/` |
| SQLite gallery query latency | ≤ 100ms p95 at 10k assets | `pytest-benchmark` against indexed fixtures |
| Completeness ≥ 0.7 for downloads from primary platforms | ≥ 80% of CivitAI, Unsplash, Pexels, ArtStation assets | Real-world canary set captured weekly |
| AI-generation status known | ≥ 90% of assets from C2PA-supporting platforms (Firefly, Midjourney exports, CivitAI) | Same canary set |
| Schema migrations | 100% non-destructive | Migration test on synthetic v1.0 corpus |

---

## 12. Open Questions for Alan

These are decisions deferred to you before Phase 1 starts:

1. **Initial watch folder(s)** — single LoRA folder, or multi-folder?
2. **API keys** — Unsplash, Pexels, CivitAI, Spawning — willing to set these up? (free tier sufficient)
3. **Wayback archival** — enable by default, or opt-in per source domain? (it's polite to throttle, but slows capture)
4. **Schema v1.0 backups** — keep `.v1backup` indefinitely, auto-prune after 90 days?
5. **Distribution** — local dev build is fine for MVP, or do you want a signed Mac DMG installer from day one?

---

## 13. Files to Create / Modify

### Create
- `docs/comprehensive-plan.md` (this file)
- `lib/constants.py`
- `lib/embedded_metadata.py`
- `lib/c2pa_reader.py`
- `lib/platform_apis.py`
- `lib/opt_out.py`
- `lib/archive.py`
- `lib/license_spdx.py`
- `lib/dataset_lookup.py`
- `lib/completeness.py`
- `lib/api.py` (FastAPI app)
- `lib/thumbnails.py`
- `tests/` (full suite)
- `ui/` (Tauri + React project)

### Modify
- `provenance.py` (split functions, new commands, schema v2.0, --dry-run/--force/--skip-existing)
- `lib/metadata.py` (with-blocks, public API)
- `lib/scrapers.py` (regex scope, @graph, UA, backoff)
- `lib/browser_history.py` (parameterised SQL, Firefox, multi-profile)
- `lib/storage.py` (SQLite index, CSV export, upsert)
- `lib/watcher.py` (size-stable polling)
- `requirements.txt` (add: `c2pa-python`, `python-xmp-toolkit`, `IPTCInfo3`, `fastapi`, `uvicorn`, `websockets`, `pillow-avif-plugin`, dev: `pytest`, `pytest-httpserver`, `responses`, `pytest-benchmark`)

### Cleanup
- Existing `provenance.py` `collect_provenance()` becomes orchestrator only.
- Existing JSON sidecars get auto-migrated to v2.0 on first open.

---

## 14. Out of MVP — Tracked for Later

- Safari browser-history support
- Browser extension (Chrome / Firefox) for cases where history is unavailable
- Local CLIP/LAION retrieval index
- Wikidata artist cross-reference
- Watermark detection
- Face / person detection
- iCloud / Dropbox / OneDrive folder watching
- Public-key signing of sidecars (`detached COSE` over SHA256)
- Read-only collaborator sharing (export bundle of N assets + sidecars + thumbnails)
- AI-training opt-in declaration writer (write IPTC 2025.1 fields into your own files)
