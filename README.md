# AI Provenance Collector

Automatically captures and documents the provenance of every image you download for AI training datasets.

**The problem:** When you save images from your browser, there is no record of where they came from, who made them, what license applies, or whether the creator opted out of AI training.

**What this does:** Watches your download folders, reads Chrome/Edge browser history to recover source URLs automatically, extracts embedded rights metadata (EXIF, IPTC, XMP, C2PA), checks AI training opt-out signals, and writes a `.provenance.json` sidecar next to every image plus a queryable SQLite index.

---

## Quick Start

```bash
pip install -r requirements.txt

# Watch a folder — captures provenance as images land
python provenance.py watch ~/Downloads/lora-images/

# Download an image directly
python provenance.py download https://example.com/photo.jpg

# Back-fill source URLs from Chrome history for existing images
python provenance.py enrich ~/Downloads/lora-images/

# Scan an existing folder
python provenance.py scan ~/Downloads/lora-images/

# See what Chrome has downloaded recently
python provenance.py history
```

---

## What Gets Captured

Every image gets a `.provenance.json` sidecar with:

| Field | Source |
|---|---|
| SHA256 hash | Computed from file bytes |
| Source URL | Chrome/Edge download history |
| Source page | Browser tab URL at time of download |
| Platform | Auto-detected (CivitAI, Unsplash, ArtStation, Pixiv, etc.) |
| Author / creator | EXIF `Artist`, OpenGraph, Schema.org |
| License | IPTC `UsageTerms`, XMP `xmpRights`, CC link detection, SPDX normalised |
| AI-generated flag | C2PA manifest, IPTC 2025.1 `DigitalSourceType` |
| AI training opt-out | `ai.txt`, `tdm-reservation` HTTP header, IPTC `Data Mining` field |
| Image dimensions | Width × height, color mode |
| Download timestamp | File mtime or HTTP `Last-Modified` |

### Example sidecar

```json
{
  "schema_version": "2.0",
  "captured_at": "2026-05-18T01:11:34Z",
  "file": {
    "filename": "portrait.jpg",
    "sha256": "c028d7aa...",
    "size_bytes": 245120,
    "mime_type": "image/jpeg"
  },
  "source": {
    "url": "https://cdn.civitai.com/images/123456/portrait.jpg",
    "page_url": "https://civitai.com/images/123456",
    "platform": "civitai",
    "via": "browser"
  },
  "creator": { "name": "ArtistName", "profile_url": "https://civitai.com/user/ArtistName" },
  "rights": {
    "license_spdx": "CC-BY-NC-4.0",
    "ai_training": {
      "opt_out": false,
      "signals": { "ai_txt": false, "tdm_reservation": null, "iptc_data_mining": null }
    }
  },
  "ai": { "is_ai_generated": true, "source": "c2pa", "tool": "Stable Diffusion XL" },
  "completeness": 0.91
}
```

---

## How Browser History Capture Works

When Chrome saves a file to disk it records the download in a local SQLite database (`~/Library/Application Support/Google/Chrome/Default/History` on macOS). This tool copies that database, queries it by filename and timestamp, and recovers:

- The direct image URL Chrome fetched
- The tab URL you were on (e.g. the CivitAI image page)
- For Google Images: the original source URL, extracted from the `imgurl=` parameter

**Chrome must be closed** when running `enrich` or `scan` for the history to be readable. The `watch` command queries history in real time as each file lands.

---

## Standards Support

| Standard | What it covers | Status |
|---|---|---|
| **C2PA v2.2** | Cryptographic AI-generation and training-consent assertions | Phase 1 |
| **IPTC 2025.1** | `Data Mining` opt-out field, AI prompt/system fields | Phase 1 |
| **XMP / xmpRights** | License URL, usage terms, rights owner | Phase 1 |
| **ai.txt** | Domain-level AI training opt-out | Phase 1 |
| **TDM Reservation** | Per-URL training opt-out HTTP header (EU AI Act Art. 53) | Phase 1 |
| **SPDX** | Canonical license identifiers (`CC-BY-4.0`, `CC0-1.0`, etc.) | Phase 1 |
| **Wayback Machine** | Source page archival for link-rot protection | Phase 2 |
| **Spawning DNTR** | Cross-reference against Do Not Train Registry | Phase 2 |

---

## Commands

```
provenance.py download <url>       Download an image and capture all provenance
  --dir PATH                       Output directory (default: current dir)
  --source-page URL                Page where the image was found
  --csv PATH                       CSV log path

provenance.py scan <path>          Process already-downloaded images
  --skip-existing                  Skip files that already have a sidecar
  --force                          Re-capture even if sidecar exists
  --dry-run                        Preview without writing
  --no-history                     Skip Chrome history lookup

provenance.py watch <dir>          Watch folder for new images
  --no-history                     Skip Chrome history lookup

provenance.py enrich <path>        Back-fill URLs from Chrome history
  --force                          Re-enrich even if URL already present
  --no-scrape                      Skip page scraping after URL lookup

provenance.py history              Show recent Chrome/Edge image downloads
  --limit N                        Number of records (default: 50)
  --db PATH                        Chrome History SQLite path (auto-detected)

provenance.py migrate <path>       Upgrade v1.0 sidecars to v2.0 (non-destructive)
provenance.py audit <path>         Gap report — files missing key fields
```

---

## Installation

**macOS:**
```bash
brew install exempi          # required for XMP reading
pip install -r requirements.txt
```

**Linux:**
```bash
apt install libexempi-dev
pip install -r requirements.txt
```

**Python 3.11+ required.**

---

## Storage

- **`.provenance.json`** — sidecar file alongside each image; portable, travels with the file
- **`~/.provenance/index.sqlite`** — fast queryable index across your whole collection
- **`provenance_log.csv`** — flat export, openable in Excel or Sheets

---

## Roadmap

- **Phase 1** (current) — Reliable CLI: C2PA + IPTC/XMP reading, opt-out detection, SPDX normalisation, SQLite index
- **Phase 2** — Enrichment: Unsplash/Pexels APIs, Wayback archival, HTML audit report, Spawning DNTR
- **Phase 3** — Desktop UI: Tauri app with gallery, detail panel, and audit screen (only if Phase 1+2 validate the need)

---

## Background

The EU AI Act Article 53 requires GPAI model developers to honor TDM reservation signals. The IPTC 2025.1 standard adds four AI-specific metadata fields to the industry photo standard. C2PA v2.2 includes explicit training-data consent assertions. No single open-source tool integrates all three with browser-download capture — this tool fills that gap.

**Research references:**
- [C2PA Specification v2.2](https://c2pa.org)
- [IPTC Photo Metadata 2025.1](https://iptc.org/standards/photo-metadata/iptc-standard/)
- [TDM Reservation Protocol](https://www.edrlab.org/open-standards/tdmrep/)
- [Data Provenance Initiative](https://www.dataprovenance.org) — *Nature Machine Intelligence* 2024
- [Spawning / Have I Been Trained](https://haveibeentrained.com)

---

## License

MIT
