# Hardened Plan — AI Provenance Collector
## Go / No-Go Decision Document

**Alan | 2026-05-18 | Post-Research Version**

---

## 1. Confirmed Market Gap

The research confirms one genuine, unoccupied niche:

> **A desktop-native tool that (1) captures provenance at browser-download time, (2) reads C2PA + IPTC + XMP standards from the file itself, and (3) checks AI training opt-out signals — in a single workflow. Nothing currently ships this combination.**

What exists and what we don't rebuild:

| Existing tool | What it covers | We use it, not rebuild it |
|---|---|---|
| `c2pa-python` (contentauth/c2pa-rs) | Reading C2PA manifests | ✅ import as library |
| ExifTool | EXIF / IPTC / XMP reading | ✅ subprocess fallback |
| `python-xmp-toolkit` | XMP read/write | ✅ import as library |
| Spawning DNTR API | Opt-out registry lookup | ✅ optional API call |
| Data Provenance Initiative schema | Dataset documentation structure | ✅ reference for our data model |
| Digimarc C2PA browser extension | In-browser C2PA reading | Reference only — we do this server-side |

What we build that doesn't exist: **the integration layer** — browser history → file → embedded metadata → page scrape → opt-out signals → one clean record.

---

## 2. The Problem with the Previous Plan

The engineering plan was a full product roadmap: Tauri desktop app, FastAPI server, React frontend, 14 new Python modules, PyInstaller binary, macOS notarisation pipeline.

**That is a 3-month team project, not a tool for one person.**

Before building a UI, we need to know the data is good. We don't know that yet. The CLI exists. It needs hardening. Run it for 30 days. See what actually gets captured. Then decide what the UI needs to show.

---

## 3. Simplified Phases

### Phase 1 — Reliable CLI (2 weeks, one person)
**Goal:** Every image Alan downloads has a complete, trustworthy provenance record.

What's in:
- Fix 14 known bugs (file-handle leaks, SQL injection vector, CC regex over-match, dedup race)
- Add C2PA reading (`c2pa-python`) — AI-generated flag, creator tool
- Add IPTC/XMP reading (`python-xmp-toolkit`) — embedded rights, IPTC 2025.1 AI fields, Data Mining opt-out
- Add opt-out detection (ai.txt, `tdm-reservation` HTTP header, IPTC Data Mining field)
- Add license SPDX normalisation (static mapping table)
- Replace CSV-as-primary-store with SQLite (`~/.provenance/index.sqlite`)
- `provenance audit` CLI command — gap report to terminal
- `provenance migrate` — non-destructive v1.0 → v2.0 schema upgrade

What's out:
- Tauri, FastAPI, React (deferred to Phase 3)
- Wayback Machine archival (deferred — adds external dependency, latency)
- Platform APIs beyond CivitAI (deferred — only CivitAI is core to Alan's workflow today)
- Spawning DNTR, LAION membership check (deferred — opt-in enrichment)
- Firefox history (deferred — Alan uses Chrome/Edge)

**Exit criteria:** Run `provenance scan ~/lora-dataset/` on a real folder. 90%+ of images from CivitAI, Unsplash, ArtStation have source URL + license SPDX + AI-status populated. No crashes on 1,000-image batch.

---

### Phase 2 — Enrichment + Report (2 weeks, one person)
**Goal:** Surface the data as a useful artefact, not just a JSON file.

What's in:
- Unsplash + Pexels platform APIs (clean license, photographer data — free tier)
- Wayback Machine archival (opt-in per source domain — Wayback is free)
- Completeness scoring (0.0–1.0 per asset, stored in SQLite)
- `provenance report` — generates a self-contained HTML file (no server needed) showing gallery, gaps, opt-out flags
- Spawning DNTR check (opt-in, free API key)

**Exit criteria:** Alan runs `provenance report` and gets an HTML file he could hand to an auditor. Every opted-out image is flagged.

---

### Phase 3 — Desktop UI (evaluate after Phase 2)
**Decision point:** After 30+ days using Phases 1 + 2 in production, answer:
- Is the HTML report enough, or is daily use blocked by lack of a real UI?
- Are there interaction patterns (browsing, filtering, editing) that only a persistent app enables?

If yes to both: build the Tauri app from the engineering plan.
If no: ship a better `report` command and call it done.

This is the decision a CTO makes — don't build the UI until you know the CLI data is solid and the UI is genuinely needed.

---

## 4. Simplified Data Model (v2.0)

Remove fields we can't reliably populate. Every field in the record should be filled >60% of the time for images from primary platforms.

```jsonc
{
  "schema_version": "2.0",
  "captured_at": "ISO8601",
  "downloaded_at": "ISO8601",

  "file": {
    "filename": "...",
    "sha256": "...",
    "size_bytes": 0,
    "mime_type": "image/jpeg"
  },

  "source": {
    "url": "...",              // direct image URL
    "page_url": "...",         // page where it was found
    "platform": "civitai",     // detected platform
    "domain": "civitai.com",
    "via": "browser | download | scan"
  },

  "creator": {
    "name": "...",
    "profile_url": "..."
  },

  "rights": {
    "license_spdx": "CC-BY-4.0",
    "license_url": "...",
    "copyright": "...",
    "ai_training": {
      "opt_out": true,              // any signal says no
      "signals": {
        "ai_txt": null,             // true/false/null
        "tdm_reservation": null,    // 1/0/null
        "iptc_data_mining": null,   // "Prohibited"/null
        "spawning_dntr": null       // true/false/null (opt-in)
      }
    }
  },

  "ai": {
    "is_ai_generated": null,       // true/false/null
    "source": "c2pa | iptc | platform | unknown",
    "tool": "Adobe Firefly"
  },

  "embedded": {
    "has_c2pa": false,
    "exif_artist": "...",
    "xmp_rights_marked": null,
    "iptc_data_mining": null
  },

  "completeness": 0.85            // 0.0–1.0, pure function of above
}
```

Fields removed from the earlier v2.0 schema: `wayback_snapshot_url` (Phase 2), `training_dataset_membership` (Phase 2/3), `page_metadata` blob (replaced by extracted fields only), `platform_specific` nested objects (flattened into `creator` and `rights`).

---

## 5. Phase 1 — Exact Task List

14 files total. Ordered by dependency.

| # | File | Change | Why |
|---|---|---|---|
| 1 | `lib/constants.py` | New — `IMAGE_EXTENSIONS`, `SCHEMA_VERSION`, `PROVENANCE_DIR` | Single source of truth |
| 2 | `lib/metadata.py` | Fix `_getexif()` → `getexif()`; add `with` blocks | FD leak on 1k+ scan |
| 3 | `lib/browser_history.py` | Parameterise SQL; shared temp-copy context manager; iterate all paths | SQL injection; FD leak |
| 4 | `lib/scrapers.py` | Restrict CC regex; flatten `@graph`; UA rotation; 429 backoff | False positives; silent drops |
| 5 | `lib/embedded_metadata.py` | New — XMP + IPTC + IPTC 2025.1 via `python-xmp-toolkit` + `IPTCInfo3` | Embedded rights captured |
| 6 | `lib/c2pa_reader.py` | New — wraps `c2pa-python` | AI-generated status |
| 7 | `lib/opt_out.py` | New — ai.txt + tdm-reservation + IPTC Data Mining; 24h cache | Opt-out signals |
| 8 | `lib/license_spdx.py` | New — static mapping to SPDX | Machine-readable licenses |
| 9 | `lib/completeness.py` | New — pure scoring function | Drives audit + report |
| 10 | `lib/storage.py` | Rewrite — SQLite primary store; sidecar write; CSV export | No dedup races |
| 11 | `provenance.py` | Split `collect_provenance`; schema v2.0; `migrate`, `audit` commands; `--dry-run`, `--force`, `--skip-existing` | Maintainable; safe ops |
| 12 | `lib/watcher.py` | Size-stable file detection; multi-folder | Fragile on large files |
| 13 | `requirements.txt` | Add `c2pa-python`, `python-xmp-toolkit`, `IPTCInfo3` | New capabilities |
| 14 | `tests/` | Unit tests for all new modules; integration test with fixture images | Catch regressions |

**Time estimate: 8–10 focused days.**

---

## 6. Go / No-Go Assessment

### Go signals ✅
- The gap is real and confirmed by independent research
- The core capture mechanism (browser history + embedded metadata + opt-out signals) is technically sound and already partially working
- `c2pa-python`, `python-xmp-toolkit`, and `IPTCInfo3` are all active libraries with clean APIs
- The EU AI Act (Art. 53) creates a compliance driver — this isn't just nice-to-have
- Phase 1 is bounded: 14 files, 8–10 days, one person, no external services required

### Risks to watch 🟡
- **`libexempi` system dependency** — `python-xmp-toolkit` requires `brew install exempi` on macOS. First thing to test on Alan's machine. If it fails, fall back to `exiftool` subprocess.
- **C2PA adoption is still <10% of images** — most LoRA training images won't have a manifest yet. The tool is still useful (IPTC/XMP fields exist on stock photos; browser history covers the rest), but set expectations: C2PA fields will often be null.
- **Browser history works only when Chrome is closed.** This is an awkward UX truth. The `enrich` command exists for this reason — run it after a session.
- **Spawning DNTR API reliability** — intermittent as of mid-2026. Keep it opt-in; never block capture on its availability.

### No-go signals ❌ (none currently)
None identified. The plan is executable.

---

## 7. What We're Not Building (and Why)

| Deferred item | Why |
|---|---|
| Tauri desktop app | Don't build UI before validating data quality. Phase 3 if needed. |
| FastAPI server | No client yet. Over-engineering. |
| Wayback archival in Phase 1 | Adds latency + external dependency to core capture path. Phase 2. |
| Firefox browser history | Alan uses Chrome/Edge. Build for the user you have. |
| LAION dataset membership check | 600GB local index. P2 for power users. |
| Wikidata artist cross-reference | Low signal-to-noise for web-scraped images. Skip. |
| Browser extension | Useful for Safari + private windows. Build after CLI is solid. |
| Watermark / face detection | Research-grade accuracy. Not a fit for MVP. |

---

## 8. Recommendation

**Build Phase 1 now.**

The technical foundation is in place. The gap is real. The scope is tight. The highest-risk dependency (`libexempi`) should be validated on Alan's machine before writing a single line of Phase 1 code — run `brew install exempi && python -c "import libxmp"` and confirm it works. If it does, start with task #1 (`constants.py`) and work through the list.

Do not plan Phase 3 (Tauri UI) until Phase 1 and 2 have been run in production for at least 30 days.
