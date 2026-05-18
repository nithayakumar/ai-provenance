# Engineering Plan — Final
## AI Data Provenance Collector

**Date:** 2026-05-18  
**Status:** Final, post agent-driven review  
**Branch:** `claude/automate-data-provenance-y8bYZ`

---

## 1. Context

This document is the engineering blueprint to deliver the PRD in `docs/prd.md`. It incorporates:

- The current code state on this branch
- Findings from four parallel agent reviews (product, engineering, rights/metadata, standards research)
- A Tauri-based desktop frontend with Apple-clean UI
- Industry standards integration (C2PA, IPTC 2025.1, XMP, SPDX, `ai.txt`, Wayback)

Companion documents:
- `docs/prd.md` — product requirements
- `docs/comprehensive-plan.md` — synthesis of all reviews and design
- `docs/how-it-works.md` — plain-English walkthrough with research citations

---

## 2. Current State (on this branch)

```
provenance.py                 CLI (download / scan / watch / enrich / history)
requirements.txt              requests, Pillow, beautifulsoup4, watchdog, lxml
lib/
  __init__.py                 empty
  metadata.py                 SHA256, EXIF, dimensions
  scrapers.py                 HTTP fetch, OG / schema.org / CC scrape
  storage.py                  JSON sidecar + CSV append
  watcher.py                  watchdog daemon
  browser_history.py          Chrome/Edge SQLite reader with Google Images extraction
docs/
  prd.md                      PRD (final)
  engineering-plan.md         this file
  comprehensive-plan.md
  how-it-works.md
```

Tests: none yet.

### Known issues to fix in Phase 1

From the engineering review:

| # | Issue | File:Line | Fix |
|---|---|---|---|
| 1 | `img._getexif()` private API, no `with` block, FD leak at scale | `lib/metadata.py:19-31` | Switch to public `getexif()`; wrap in `with Image.open(...)`. |
| 2 | SQL built via f-string interpolation | `lib/browser_history.py:177-194` | Parameterised queries with `?` placeholders. |
| 3 | Temp file leak path in `list_recent_image_downloads` on error | `lib/browser_history.py:214-240` | Share the `_with_history_copy()` context-manager helper. |
| 4 | CSV race/dedup not enforced | `lib/storage.py:34-41` | Replace append with `upsert_asset()` against SQLite. |
| 5 | CC regex scans full response text | `lib/scrapers.py:93` | Restrict to extracted `<a>` hrefs, `<link rel>`, `<meta>` content. |
| 6 | `IMAGE_EXTENSIONS` defined in 3 places | `provenance.py:33` + `lib/scrapers.py:17` + `lib/watcher.py:7` | Single definition in `lib/constants.py`. |
| 7 | `collect_provenance()` does too much | `provenance.py:32-137` | Split into `gather_signals()`, `resolve_canonical()`, `compute_completeness()`, `persist()`. |
| 8 | Schema.org `@graph` arrays silently dropped | `provenance.py:102-117` | Flatten nested arrays before iterating. |
| 9 | Sidecar overwrite for same-stem files (`a.jpg` and `a.png`) | `lib/storage.py:28` | Include extension in sidecar name: `<filename>.provenance.json`. |
| 10 | `cmd_enrich` crashes on malformed JSON | `provenance.py:281` | try/except per file; log and continue. |
| 11 | `download_image` doesn't validate content-type | `lib/scrapers.py:18-32` | Check `content-type: image/*` or `application/octet-stream` before writing. |
| 12 | Watcher fixed 1s sleep is fragile for large files | `lib/watcher.py:29` | Poll until file size unchanged for 500ms. |
| 13 | Scan re-hashes existing files | `provenance.py:178-205` | Default `--skip-existing`; `--force` to override. |
| 14 | `list_recent_image_downloads` only checks first history path | `lib/browser_history.py:216` | Iterate all paths like `find_download_record` does. |

---

## 3. Target Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Tauri 2 Shell  (Rust + macOS/Linux webview)                 │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  React 18 + TypeScript Frontend                        │  │
│  │  Routes:  Gallery · Detail · Audit · Activity · Set    │  │
│  │  Libs:    TanStack Query · Zustand · Tailwind · shadcn │  │
│  └────────────────────┬──────────────────────────────────┘  │
└────────────── REST / WebSocket ───────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  FastAPI Server  (Python sidecar, bundled with the app)      │
│  Spawned by Tauri on launch; killed on quit.                 │
└────────────────────────┬─────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Core Library (lib/)                                         │
│   • metadata             hash + EXIF (fixed)                 │
│   • embedded_metadata    XMP + IPTC + IPTC 2025.1 AI fields  │
│   • c2pa_reader          C2PA manifest reading & validation  │
│   • scrapers             HTML / OG / schema.org / CC (fixed) │
│   • platform_apis        Unsplash / Pexels / Flickr / AS /   │
│                          Pixiv / DeviantArt / CivitAI        │
│   • opt_out              ai.txt / tdm-reservation / robots / │
│                          IPTC DataMining / Spawning DNTR     │
│   • archive              Wayback Save API                    │
│   • license_spdx         Text/URL → SPDX identifier          │
│   • dataset_lookup       LAION (clip-retrieval) + Spawning   │
│   • browser_history      Chrome/Edge + Firefox (fixed)       │
│   • completeness         Pure scoring function               │
│   • storage              SQLite index + JSON sidecar + CSV   │
│   • thumbnails           WebP cache @ 256px                  │
│   • constants            IMAGE_EXTENSIONS, SCHEMA_VERSION    │
│   • api                  FastAPI app + WebSocket events      │
│   • watcher              Multi-folder, size-stable polling   │
└─────────────────────────────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Local Storage                                               │
│   ~/.provenance/                                             │
│     index.sqlite          assets + FTS5 + events log         │
│     thumbnails/<sha256>.webp                                 │
│     exports/provenance_log.csv  (derived view)               │
│     cache/                Spawning, Wayback, opt-out caches  │
│   <user folders>/                                            │
│     <image>.provenance.json   (portable, schema v2.0)        │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Module Specifications

### 4.1 `lib/constants.py` (new)
```python
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",
                    ".tiff", ".tif", ".avif", ".heic", ".heif"}
SCHEMA_VERSION = "2.0"
TOOL_VERSION   = "0.2.0"
PROVENANCE_DIR = Path.home() / ".provenance"
INDEX_DB       = PROVENANCE_DIR / "index.sqlite"
```

### 4.2 `lib/metadata.py` (refactor)
- `sha256_of_file(path) -> str` — unchanged
- `extract_exif(path) -> dict` — use public `Image.getexif()`, wrapped in `with`
- `get_image_dimensions(path) -> dict` — wrapped in `with`
- `collect_file_metadata(path, *, captured_at, downloaded_at) -> dict` — separate timestamps

### 4.3 `lib/embedded_metadata.py` (new)
```python
def read_xmp(path: Path) -> dict:    # python-xmp-toolkit
def read_iptc(path: Path) -> dict:   # IPTCInfo3 for IIM; XMP packet for IPTC-XMP
def read_all_embedded(path: Path) -> dict:
    return {"exif": ..., "iptc": ..., "xmp": ...}

# Mapping helpers (pure functions)
def map_to_canonical(embedded: dict) -> dict:
    """Returns partial { creator, rights } populated from embedded fields."""
```

Maps:
- `Xmp.dc.creator` → `creator.author`
- `Iptc.Application2.By-line` → `creator.author` (fallback)
- `Xmp.dc.rights` → `rights.copyright_notice`
- `Iptc.Application2.CopyrightNotice` → `rights.copyright_notice` (fallback)
- `Xmp.xmpRights.UsageTerms` → `rights.license_text`
- `Xmp.xmpRights.WebStatement` → `rights.license_url`
- `Xmp.xmpRights.Owner` → `rights.copyright_holder`
- `Xmp.plus.DataMining` → `rights.ai_training_opt_out.iptc_data_mining`
- **IPTC 2025.1 AI fields:**
  - `Xmp.Iptc4xmpExt.DigitalSourceType` → `c2pa.ai_generated` (mapped from PLUS vocab)
  - `Xmp.Iptc4xmpExt.AIPrompt` → `platform_specific.iptc_ai.prompt`
  - `Xmp.Iptc4xmpExt.AISystemUsed` → `platform_specific.iptc_ai.system_used`
  - `Xmp.Iptc4xmpExt.AISystemVersionUsed` → `platform_specific.iptc_ai.system_version`

Fall back to subprocess `exiftool` if `python-xmp-toolkit` import fails.

### 4.4 `lib/c2pa_reader.py` (new)
```python
def read_c2pa(path: Path) -> dict:
    """Returns:
        manifest_present: bool
        ai_generated: bool | None
        creator_tool: str | None
        actions: list[dict]
        ingredients: list[dict]
        validation_status: 'valid' | 'invalid' | 'unsigned' | 'absent'
    """
```
Wraps `c2pa-python`'s `Reader`. Treats missing manifest as `manifest_present: False` (not an error). Invalid signature still returns the manifest content with `validation_status: 'invalid'` — auditors care about the assertion either way.

### 4.5 `lib/scrapers.py` (refactor)
- Keep `download_image`, add content-type check
- `scrape_page_metadata` — split into `extract_opengraph`, `extract_schema_org`, `extract_license_link`, `extract_twitter_card`. Flatten Schema.org `@graph` arrays.
- CC regex now operates only on extracted `<a>` href values, `<link rel>` hrefs, `<meta>` content. Not raw HTML.
- User-Agent rotation pool; 429 backoff with exponential retry (3 attempts).
- `detect_platform()` unchanged but exhaustively documented.

### 4.6 `lib/platform_apis.py` (new)
One async function per platform, all return a `platform_specific[<platform>]` dict:

```python
async def unsplash(image_id, api_key) -> dict
async def pexels(image_id, api_key) -> dict
async def flickr(photo_id, api_key) -> dict
async def artstation(slug) -> dict           # public JSON, no key
async def pixiv(work_id, auth_cookie) -> dict
async def deviantart(deviation_id, api_key) -> dict
async def civitai(image_or_model_id, api_key=None) -> dict
```

Each function:
- Extracts the platform-canonical `license` and maps to SPDX
- Extracts `creator.author` and `profile_url`
- Captures platform-specific AI flags where present (Pixiv `ai_type`, ArtStation `is_ai_generated`)
- 24h cached per ID

API keys are read from `~/.provenance/config.json` (set via Settings UI). Missing keys → skip platform (logged warning).

### 4.7 `lib/opt_out.py` (new)
```python
def check_ai_txt(domain) -> dict
    # GET https://<domain>/ai.txt; parse Spawning grammar; 24h cache
def check_tdm_reservation(url) -> int | None
    # HEAD; read 'tdm-reservation' header per IETF draft
def check_robots_ai(domain) -> dict
    # parse robots.txt for User-agent: GPTBot|CCBot|ClaudeBot etc.
def check_spawning_dntr(sha256, api_key=None) -> bool | None
    # POST to api.spawning.ai; 7d cache; opt-in
def check_iptc_data_mining(provenance) -> str | None
    # Read from already-extracted embedded_metadata.iptc

def aggregate_opt_out(provenance) -> dict
    # Combines all 5 into the rights.ai_training_opt_out block
```

### 4.8 `lib/archive.py` (new)
```python
def wayback_save(url) -> str | None
    # POST https://web.archive.org/save/<url>
    # Per-domain rate limiter: max 1 req / 60s / domain
    # Returns permalink or None on failure
def wayback_check(url) -> str | None
    # GET availability API to see if already archived
```

### 4.9 `lib/license_spdx.py` (new)
Static dict mapping (case-insensitive) common license names and URLs to SPDX:
- `"CC BY 4.0"`, `"creativecommons.org/licenses/by/4.0/"` → `"CC-BY-4.0"`
- All CC variants (BY, BY-SA, BY-ND, BY-NC, BY-NC-SA, BY-NC-ND) v3.0 and v4.0
- `"CC0"`, `"Public Domain Mark"` → `"CC0-1.0"`, `"PDDL-1.0"`
- Unsplash License, Pexels License (custom non-SPDX, kept as text but marked)

```python
def to_spdx(license_text: str | None, license_url: str | None) -> str | None
```

### 4.10 `lib/dataset_lookup.py` (new — P1/P2)
```python
def check_spawning(sha256) -> dict   # P1: opt-in, requires API key
def check_laion_via_clip_retrieval(image_path, local_index_path) -> dict
    # P2: requires ~600GB local index, only for power users
def lookup_all(provenance) -> dict
```

### 4.11 `lib/browser_history.py` (refactor)
- Replace f-string SQL with `?` placeholders
- Add Firefox: `_firefox_history_paths()` and `_query_firefox()` against `places.sqlite` / `moz_annos` (handle two schemas — pre-v75 `moz_downloads` table, post-v75 `moz_annos` with `type=1`)
- `list_recent_image_downloads` iterates all paths
- Context-manager helper `with _history_copy(path) as conn:` to remove temp-file leak risk

### 4.12 `lib/watcher.py` (refactor)
- Replace `time.sleep(1.0)` with stable-size check (size unchanged for 500ms)
- Multi-folder support: `watch_directories(dirs: list[Path], process_fn)`
- Re-watch on observer crash with exponential backoff

### 4.13 `lib/completeness.py` (new)
Pure function. No side effects, no I/O.

```python
WEIGHTS = {
    "has_source_url":       0.20,
    "has_author":           0.10,
    "has_license_spdx":     0.20,
    "has_sha256":           0.10,
    "has_c2pa":             0.10,
    "ai_status_known":      0.15,
    "opt_out_checked":      0.10,
    "has_wayback":          0.05,
}

def compute(provenance: dict) -> dict:
    # Returns dict with score (0..1) and individual booleans
```

### 4.14 `lib/storage.py` (rewrite)
SQLite schema:
```sql
CREATE TABLE assets (
    sha256          TEXT PRIMARY KEY,
    filepath        TEXT,
    filename        TEXT,
    captured_at     TEXT,
    downloaded_at   TEXT,
    platform        TEXT,
    source_url      TEXT,
    license_spdx    TEXT,
    completeness    REAL,
    ai_generated    INTEGER,    -- 0/1/NULL
    opt_out_any     INTEGER,    -- 0/1/NULL
    json_blob       TEXT        -- full v2.0 provenance JSON
);
CREATE VIRTUAL TABLE assets_fts USING fts5(
    sha256, filename, source_url, author, license_text,
    content='assets', content_rowid='rowid'
);
CREATE TABLE events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at     TEXT,
    event_type      TEXT,
    sha256          TEXT,
    detail          TEXT
);
CREATE INDEX idx_assets_platform     ON assets(platform);
CREATE INDEX idx_assets_completeness ON assets(completeness);
```

API:
```python
def upsert_asset(provenance: dict) -> None     # atomic write to both sidecar + index
def get_asset(sha256: str) -> dict | None
def query_assets(filters: dict, limit, offset) -> list[dict]
def search_assets(text: str, limit) -> list[dict]
def export_csv(path: Path) -> int
def emit_event(event_type, sha256, detail) -> None
def write_sidecar(image_path, provenance) -> Path
def read_sidecar(image_path) -> dict | None
```

### 4.15 `lib/thumbnails.py` (new)
```python
def ensure_thumbnail(sha256, image_path) -> Path
    # 256px webp; idempotent; cached in ~/.provenance/thumbnails/
```

### 4.16 `lib/api.py` (new — FastAPI)
```
GET    /assets                  ?platform=&missing=&q=&limit=&offset=&sort=
GET    /assets/{sha256}
PATCH  /assets/{sha256}         body: partial rights/creator update
DELETE /assets/{sha256}         remove from index (file untouched)

GET    /audit                   aggregate completeness/gap stats
POST   /audit/export            generate CSV → returns path

POST   /capture                 body: { url, source_page?, dest_dir? }
POST   /enrich                  body: { sha256? | path?, force? }
POST   /scan                    body: { dir, recursive?, skip_existing? }
POST   /recheck                 body: { sha256 | path }
POST   /relink                  body: { dir }
POST   /migrate                 body: { dir }

POST   /watch                   body: { dir }
GET    /watch                   list active watches
DELETE /watch/{dir_b64}         stop watching

GET    /thumbnails/{sha256}.webp
GET    /history                 recent Chrome/Edge/Firefox downloads (debug)

WS     /ws/activity             event stream (event_type, sha256, detail)
WS     /ws/watch                folder-watcher status
```

Uses `pydantic` models that mirror schema v2.0. TypeScript types generated via `pydantic_to_typescript` build step.

---

## 5. Frontend

### 5.1 Stack and Why

| Choice | Why |
|---|---|
| **Tauri 2** | Native window, small binary (~10MB), bundles a Python sidecar, signs/notarises on Mac |
| **React 18 + TypeScript strict** | Familiar, large ecosystem, type-safe across the API |
| **Tailwind + shadcn/ui** | shadcn is unstyled Radix components — Tailwind classes shape them. Produces the cleanest "Apple-clean" defaults with zero CSS-in-JS overhead |
| **TanStack Query** | Cache + optimistic updates + WebSocket integration |
| **Zustand** | 1KB state library — perfect for `selectedSha`, `filters`, `theme` |
| **Framer Motion** | Spring physics matches macOS feel |
| **Lucide React** | SF Symbols look-alike icon set |

### 5.2 File Layout

```
ui/
  src-tauri/
    Cargo.toml
    tauri.conf.json                 # window, sidecar, signing config
    src/
      main.rs                       # spawn FastAPI sidecar, lifecycle
      sidecar.rs                    # process management
  src/
    main.tsx
    App.tsx
    routes/
      Gallery.tsx
      Detail.tsx
      Audit.tsx
      Activity.tsx
      Settings.tsx
    components/
      ui/                           # shadcn primitives (button, card, sheet, ...)
      AssetCard.tsx
      CompletenessRing.tsx
      PlatformBadge.tsx
      SpdxBadge.tsx
      C2paBadge.tsx
      OptOutChips.tsx
      MetadataAccordion.tsx
      Sidebar.tsx
      Titlebar.tsx
      ActivityCard.tsx
    lib/
      api.ts                        # typed REST client (fetch wrappers)
      ws.ts                         # WebSocket client (auto-reconnect)
      types.ts                      # generated from pydantic models
      query.ts                      # TanStack Query setup
      store.ts                      # Zustand stores
    styles/
      globals.css                   # Tailwind layers + vibrancy CSS
  tailwind.config.ts                # design tokens (color/spacing/radius/shadow)
  tsconfig.json
  package.json
  vite.config.ts
```

### 5.3 Design Tokens (`tailwind.config.ts`)

```ts
theme: {
  fontFamily: {
    sans: ['-apple-system', 'BlinkMacSystemFont', 'SF Pro Text', 'Inter', 'sans-serif'],
    display: ['SF Pro Display', 'Inter', 'sans-serif'],
    mono: ['SF Mono', 'JetBrains Mono', 'ui-monospace', 'monospace'],
  },
  colors: {
    surface:    { light: '#FFFFFF', dark: '#000000' },
    panel:      { light: '#F5F5F7', dark: '#1C1C1E' },
    text:       { light: '#1D1D1F', dark: '#F5F5F7' },
    muted:      { light: '#86868B', dark: '#8E8E93' },
    accent:     { light: '#007AFF', dark: '#0A84FF' },
    success:    '#34C759',
    warning:    '#FF9F0A',
    danger:     '#FF453A',
  },
  borderRadius: { sm: '6px', md: '8px', lg: '12px', xl: '20px' },
  spacing: { 0.5: '2px', 1: '4px', 2: '8px', 3: '12px', 4: '16px',
             6: '24px', 8: '32px', 12: '48px', 16: '64px' },
}
```

`globals.css` adds vibrancy:
```css
.vibrancy {
  background: rgba(245, 245, 247, 0.7);
  backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
}
.dark .vibrancy {
  background: rgba(28, 28, 30, 0.7);
}
```

### 5.4 Screen Details

**Gallery (`/`)**
- Masonry grid (CSS columns)
- Sticky header: search input, filter pills (chips), sort dropdown
- AssetCard:
  - 256px thumbnail (rounded-lg, aspect-square cover)
  - Filename below
  - Platform badge top-left, CompletenessRing top-right
  - C2PA / AI-generated chip if applicable
- Click → opens Detail in right-side Sheet (`shadcn/ui Sheet`, 60% width)
- Cmd-click → navigate to `/asset/{sha256}` for full-page detail
- Empty state: large `ImageOff` icon, "No assets yet", primary CTA "Set up a watch folder"

**Detail (`/asset/{sha256}` or in Sheet)**
- Header: filename, SHA256 (mono, click-to-copy), CompletenessRing, kebab menu (Re-enrich, Re-archive, Re-check dataset, Reveal in Finder, Delete from index)
- Layout: 3-column grid on full page, 1-column stacked in sheet
- Left column: image preview (max 480px), file stats card, C2PA badge with details
- Middle column: Source card, Creator card, Rights card with SPDX badge and inline-editable license picker
- Right column: AI Status card (ai.txt / tdm-reservation / IPTC data-mining / Spawning DNTR chips), Dataset Membership card, Embedded Metadata accordion (EXIF / IPTC / XMP / C2PA Actions sub-accordions), Capture Chronology timeline

**Audit (`/audit`)**
- Left: filter sidebar (checkboxes: Missing source URL, Missing author, Missing license, No AI status, No opt-out check, No Wayback, Completeness < 0.7, Aggregator source)
- Right: header summary cards (total / % complete / missing URL / AI-generated / opt-out flagged)
- Below: table with multi-select
- Bulk actions: Re-enrich (force) selected, Re-check membership, Export gap CSV
- Empty state when no gaps: confetti-free "All clear" with last-audit timestamp

**Activity (`/activity`)**
- WebSocket to `/ws/activity`
- Status banner top: "Idle" / "Watching /Users/alan/Downloads/lora_drop" / "Processing 3 assets"
- Vertical stream of ActivityCard components: timestamp + step icon + sha256 short + brief detail + elapsed ms
- Steps: download_started, hashed, exif_read, xmp_read, c2pa_read, history_matched, page_scraped, opt_out_checked, archived, dataset_checked, sidecar_written, indexed
- Auto-scroll toggle, Clear button, filter by event type

**Settings (`/settings`)**
- Form sections (shadcn `Form` + `Card`):
  - Watch folders: list with add/remove (folder picker via Tauri dialog)
  - Browser profiles: auto-detected, manual override
  - API keys: Unsplash, Pexels, CivitAI, Spawning (password inputs with reveal)
  - Wayback archival: on/off toggle, per-domain rate-limit selector
  - LAION local index path (optional, P2)
  - Theme: System / Light / Dark
  - Export: CSV path

### 5.5 Tauri / Python Sidecar

`src-tauri/src/main.rs`:
- On startup: spawn `provenance serve --port <random>` Python sidecar
- Pass the chosen port to the frontend via `window.__TAURI_PORT__`
- On window close or app quit: send SIGTERM to sidecar, wait 5s, SIGKILL
- Sidecar binary: built via PyInstaller on CI; embedded in `src-tauri/binaries/`
- Notarisation: both the Rust binary and the Python sidecar are signed and notarised in the same pipeline

---

## 6. Build, CI, Distribution

### Local dev
- Backend: `pip install -e .[dev]`; `python -m uvicorn lib.api:app --reload`
- Frontend: `cd ui && npm install && npm run tauri dev` (auto-spawns the sidecar from the Python venv)

### CI (GitHub Actions)
- Matrix: Python 3.11/3.12 × macOS-14, ubuntu-22.04
- Jobs:
  1. **Backend tests** — `pytest -q`, `mypy lib/`
  2. **Frontend type-check** — `tsc --noEmit`, `vitest run`, `eslint`
  3. **Bundle Python sidecar** — PyInstaller produces single binary
  4. **Tauri build** — for macOS: sign + notarise + produce `.dmg`; for Linux: produce AppImage + `.deb`
  5. **Release** — on tag, attach binaries to GitHub release

### Distribution
- macOS: signed and notarised `.dmg` containing the universal Tauri app
- Linux: AppImage and `.deb` (P1)

---

## 7. Testing Strategy

### Layers

| Layer | Tools | Key cases |
|---|---|---|
| metadata | pytest + fixture JPG with known EXIF / PNG with XMP | SHA256 deterministic; EXIF map complete; FD count stable across 1000 opens |
| embedded_metadata | pytest + fixture JPGs with IPTC + XMP packets | All canonical fields mapped; missing → None not raise; IPTC 2025.1 fields recognised |
| c2pa_reader | pytest + C2PA test vectors | Valid manifest, invalid signature, no manifest, AI-generated assertion |
| scrapers | `pytest-httpserver` serving controlled HTML | OG, schema.org `@graph` flatten, CC false-positive guarded, 429 backoff |
| browser_history | pytest + synthetic Chrome SQLite + Firefox SQLite | Parameterised SQL, ±120s match, multi-profile, Google `imgurl` extraction |
| opt_out | `responses` mocks | ai.txt parse, tdm-reservation header, robots.txt AI clauses, 24h cache |
| archive | `responses` Wayback mock | Permalink extracted, 429 backoff, per-domain rate limit |
| license_spdx | parametrised table-driven | All CC variants, mixed casing, URL canonicalisation |
| completeness | table-driven | Edge cases (all empty → 0; all full → 1; weights correct) |
| storage | pytest + tmp_path SQLite | Sidecar round-trip; upsert idempotent; FTS5 search; CSV export |
| api | `httpx.AsyncClient` against FastAPI | Endpoint contracts, validation errors, WebSocket event stream |
| watcher | tmp_path + watchdog | Detection latency, size-stable polling, multi-folder |
| Frontend components | Vitest + Testing Library | AssetCard renders; CompletenessRing colors correct; filters dispatch right query |
| End-to-end | Playwright against Tauri (P1) | Drop image in watch folder → appears in Gallery → Detail opens with hash; manual edit persists |

### Performance benchmarks (`tests/perf/`)
- SHA256 throughput: ≥ 500 MB/s on Apple Silicon
- Scan throughput: ≥ 1000 images/min
- Gallery query latency at 10k assets: ≤ 100ms p95
- Watch event → sidecar written: ≤ 5s p95 (sync path)

### Test corpus
- Curated set of 50 known-source downloads stored at `tests/corpus/` (small files, public domain or owned by Alan)
- Used as a canary by the CI nightly job

---

## 8. Dependencies

`requirements.txt` (production):
```
requests>=2.31.0
Pillow>=10.0.0
beautifulsoup4>=4.12.0
lxml>=4.9.0
watchdog>=3.0.0
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
websockets>=12.0
python-xmp-toolkit>=2.0.2
IPTCInfo3>=2.1.4
c2pa-python>=0.32.0
pydantic>=2.6.0
```

`requirements-dev.txt`:
```
pytest>=8.0.0
pytest-httpserver>=1.0.10
responses>=0.25.0
pytest-benchmark>=4.0.0
mypy>=1.8.0
ruff>=0.3.0
pydantic-to-typescript>=2.0.0
pyinstaller>=6.5.0
```

System requirements:
- macOS: `brew install exempi` (for `python-xmp-toolkit`)
- Linux: `apt install libexempi-dev`
- Python 3.11+

`ui/package.json` (key deps):
```json
{
  "dependencies": {
    "@tauri-apps/api": "^2.0.0",
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "react-router-dom": "^6.22.0",
    "@tanstack/react-query": "^5.20.0",
    "zustand": "^4.5.0",
    "framer-motion": "^11.0.0",
    "lucide-react": "^0.350.0",
    "tailwindcss": "^3.4.0",
    "class-variance-authority": "^0.7.0",
    "clsx": "^2.1.0",
    "tailwind-merge": "^2.2.0"
  },
  "devDependencies": {
    "@tauri-apps/cli": "^2.0.0",
    "typescript": "^5.3.0",
    "vite": "^5.1.0",
    "vitest": "^1.3.0",
    "@testing-library/react": "^14.2.0",
    "eslint": "^8.57.0"
  }
}
```

shadcn/ui components installed individually (button, card, sheet, dialog, dropdown-menu, input, form, table, tabs, accordion, badge, switch, toast, tooltip, separator).

---

## 9. Implementation Phases & Tasks

### Phase 1 — Backend hardening + standards (1–2 weeks)

| # | Task | Output |
|---|---|---|
| 1.1 | `lib/constants.py` + remove the three duplicate `IMAGE_EXTENSIONS` | one source of truth |
| 1.2 | Fix `lib/metadata.py` (with-blocks, `getexif()`) | no FD leaks |
| 1.3 | Parameterise SQL in `lib/browser_history.py`; add Firefox support; share temp-copy context manager | safer, multi-browser |
| 1.4 | Restrict CC regex; parse Schema.org `@graph`; UA rotation + 429 backoff in `lib/scrapers.py` | fewer false positives |
| 1.5 | `lib/embedded_metadata.py` (XMP + IPTC + 2025.1 AI fields) | embedded rights captured |
| 1.6 | `lib/c2pa_reader.py` (manifest reading + validation) | AI-generation status known |
| 1.7 | `lib/license_spdx.py` mapping table + tests | SPDX-normalised licenses |
| 1.8 | `lib/opt_out.py` (ai.txt + tdm-reservation + robots AI + IPTC) | opt-out signals captured |
| 1.9 | `lib/archive.py` (Wayback save + rate-limit) | source page archived |
| 1.10 | `lib/completeness.py` pure scoring function | UI-ready score |
| 1.11 | Schema v2.0 in `provenance.py` + `migrate` command + `.v1backup` | non-destructive upgrade |
| 1.12 | `relink` command (SHA256 reattach) | survives file moves |
| 1.13 | `recheck` command (re-run opt-out + archive + dataset) | refresh stale records |
| 1.14 | Split `collect_provenance()` into gather/resolve/score/persist + `--dry-run`, `--force`, `--skip-existing` | testable, safe |
| 1.15 | `lib/storage.py` rewrite — SQLite index + FTS5 + sidecar + CSV export | fast queries, no dedup race |
| 1.16 | `lib/thumbnails.py` WebP generator | UI thumbnails ready |
| 1.17 | `lib/platform_apis.py` — Unsplash, Pexels first; ArtStation + Pixiv next | structured platform data |
| 1.18 | Backend test suite (unit + httpserver + sqlite fixtures + benchmarks) | green pytest |
| 1.19 | `provenance audit` CLI mirror of UI audit | gap report from terminal |

**Phase 1 exit:** Schema v2.0 stable, all CLI commands work with new metadata, test suite green, no FD leaks, 10k-asset scan completes cleanly.

### Phase 2 — Local API + Tauri shell + Gallery + Detail (2–3 weeks)

| # | Task | Output |
|---|---|---|
| 2.1 | `lib/api.py` FastAPI app skeleton + Pydantic models | local server runs |
| 2.2 | All REST endpoints (`/assets`, `/audit`, `/capture`, `/enrich`, `/scan`, `/recheck`, `/relink`) | full programmatic access |
| 2.3 | WebSocket `/ws/activity`, `/ws/watch` + event emission from core | live events streaming |
| 2.4 | `pydantic-to-typescript` build step | typed frontend |
| 2.5 | Tauri scaffold + Python sidecar lifecycle (Rust) | app launches |
| 2.6 | Tailwind design tokens + globals + vibrancy classes | Apple-clean foundation |
| 2.7 | shadcn/ui primitives installed + customised | base components ready |
| 2.8 | Sidebar + Titlebar + App Shell | navigation works |
| 2.9 | Gallery screen with filters / search / sort | browseable collection |
| 2.10 | Detail screen with all cards + manual edit | full per-asset view |
| 2.11 | Settings screen — watch folders, API keys, theme | configurable |
| 2.12 | Manual PATCH path tested end-to-end | edits persist |

**Phase 2 exit:** Launchable Tauri app on Alan's Mac; opens Gallery, shows real captured assets; Detail panel works; manual rights edits persist.

### Phase 3 — Audit, Activity, dataset lookup, packaging (1–2 weeks)

| # | Task | Output |
|---|---|---|
| 3.1 | Audit screen (filters, table, bulk actions) | gap workflow |
| 3.2 | Live Activity feed (WebSocket consumer + auto-scroll) | real-time stream |
| 3.3 | `lib/dataset_lookup.py` — Spawning DNTR (P1) | opt-out cross-check |
| 3.4 | Platform API completion (Flickr, DeviantArt, CivitAI model/post) | full platform coverage |
| 3.5 | Bulk re-enrich, bulk re-archive (UI + API) | maintenance at scale |
| 3.6 | App icon (SF-style monochrome glyph) + DMG packaging | distributable build |
| 3.7 | Code-signing + notarisation pipeline on CI | trusted Mac install |
| 3.8 | Final QA pass + perf benchmark verification | hits success metrics |

**Phase 3 exit:** Signed `.dmg`, all four screens functional, success metrics in §11 verified, ready for daily use.

---

## 10. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `libexempi` not installed → `python-xmp-toolkit` import fails | High | Medium | Document `brew install exempi`; provide `exiftool` subprocess fallback in `embedded_metadata.py` |
| `c2pa-python` Python version pinning | Medium | Medium | Pin Py 3.11; CI matrix 3.11/3.12 |
| Spawning DNTR API intermittent | High | Low | try/except; cache result with `checked_at`; UI shows staleness |
| Wayback rate limits ~15 req/min/IP | High | Medium | Per-domain queue; UI shows backlog |
| Tauri notarisation pipeline complexity | Medium | High | Rehearse in Phase 2; budget time for Apple Developer setup |
| Schema migration corrupts user files | Low | High | Always write to new sidecar; rename original to `.v1backup`; never delete |
| `python-xmp-toolkit` lacks Windows support | Medium | Low | MVP is macOS/Linux only — documented |
| Tauri sidecar binary size (PyInstaller ~80MB) | Medium | Medium | Acceptable for desktop install; later: consider Nuitka for smaller binary |
| CivitAI API requires key for some endpoints | Medium | Low | Settings UI for key entry; public endpoints work without key |

---

## 11. Success Metrics (engineering verifiable)

| Metric | Target | Verification |
|---|---|---|
| `pytest` pass rate | 100% | CI |
| Type-check pass | `mypy lib/` + `tsc --noEmit` clean | CI |
| FD count after 10k scan | stable (no leak) | `tests/perf/test_fd_leak.py` |
| Gallery query at 10k assets | ≤ 100ms p95 | `pytest-benchmark` |
| Scan throughput | ≥ 1000 img/min on M-series | `tests/perf/test_scan_speed.py` |
| Watch latency | ≤ 5s p95 sync portion | `tests/perf/test_watch_latency.py` |
| Schema migration | 100% non-destructive | `tests/test_migration.py` on synthetic v1.0 corpus |
| Browser-history match accuracy on test corpus | ≥ 90% | Nightly canary job |
| C2PA AI-generated detection on canary | ≥ 90% | Same |
| Distributable artifact | signed `.dmg` produced on tag | CI release job |

---

## 12. Files Created / Modified

### Created (Phase 1)
- `lib/constants.py`
- `lib/embedded_metadata.py`
- `lib/c2pa_reader.py`
- `lib/platform_apis.py`
- `lib/opt_out.py`
- `lib/archive.py`
- `lib/license_spdx.py`
- `lib/completeness.py`
- `lib/dataset_lookup.py`
- `lib/thumbnails.py`
- `lib/api.py`
- `tests/` (full suite + fixtures + corpus)

### Created (Phase 2)
- `ui/` (entire Tauri + React project)
- Build configs for PyInstaller sidecar + CI release pipeline

### Modified
- `provenance.py` — split functions, new commands, schema v2.0, dry-run/force/skip-existing
- `lib/metadata.py` — with-blocks, public API
- `lib/scrapers.py` — regex scope, `@graph`, UA rotation, backoff
- `lib/browser_history.py` — parameterised SQL, Firefox, multi-profile, shared temp-copy
- `lib/storage.py` — full rewrite (SQLite index, CSV export, upsert)
- `lib/watcher.py` — size-stable polling, multi-folder
- `requirements.txt` — add the libs in §8
- `requirements-dev.txt` — new file with dev deps

### Cleanup
- Existing CSV header replaced by SQLite-derived export
- v1.0 sidecars migrated → `.v1backup` retained

---

## 13. References

Standards and libraries the implementation depends on (full citations in `docs/how-it-works.md §6`):

- C2PA v2.4 — `c2pa-python` library
- IPTC Photo Metadata Standard 2025.1 — `IPTCInfo3` + `python-xmp-toolkit`
- XMP (ISO 16684) — `python-xmp-toolkit` (wraps libexempi)
- Spawning `ai.txt` standard + Do Not Train Registry — `api.spawning.ai`
- Wayback Machine Save API — `web.archive.org/save/<url>`
- LAION-5B — `clip-retrieval` (rom1504/clip-retrieval)
- SPDX License Identifiers — static mapping
