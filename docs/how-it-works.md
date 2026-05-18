# How It Works — Plain English Walkthrough

A line-by-line explanation of the AI Data Provenance Collector. Read top to bottom. Citations to the provenance research are in [brackets] and listed at the bottom.

---

## 1. The Big Picture

> **One sentence:** Every time you save an image, the tool quietly records who made it, where it came from, and what the rules are for using it — then shows you all of that in a Mac-style app.

Three things make the whole system work together:

1. A **Python brain** that knows how to fish facts out of files and web pages.
2. A **local server** (just on your Mac, nothing online) that lets the app ask the brain questions.
3. A **desktop app** (the window you actually use) that shows the facts in a clean Apple-style layout.

That is the entire architecture. Everything below is detail.

---

## 2. What Happens When You Download an Image — Step by Step

Imagine you right-click an image in Google Images and pick "Save image as…". Here is what the tool does, in order:

### Step 1 — Notice the new file
A small watchdog process is looking at your Downloads folder. The moment Chrome finishes writing the file, the watchdog notices it.

> *Why this works:* Operating systems fire events whenever a file is created. Python's `watchdog` library listens for those events. We just wait a moment to be sure the file isn't still being written.

### Step 2 — Take a fingerprint
The tool computes a **SHA256 hash** of the file — a 64-character string that's unique to those exact bytes. If a single pixel changes, the hash changes completely.

> *Why this matters for provenance:* Hashes are how you prove the file you have today is the same file you downloaded last week. Standards like C2PA bind their cryptographic signatures to file hashes. [C2PA]

### Step 3 — Open the file and read its hidden metadata
Most image files carry metadata blocks embedded inside them. There are three you care about:

- **EXIF** — camera settings, date taken, sometimes the artist's name and copyright
- **IPTC** — the press / stock-photo standard. Holds creator, copyright notice, license terms, and (in the 2025.1 update) AI-prompt and AI-system fields
- **XMP** — Adobe's framework that wraps both of the above plus a `xmpRights` block for license URLs and usage terms

> *Why this matters:* These fields are placed inside the file by the creator's software (Photoshop, Lightroom) or by the stock agency's pipeline. **They travel with the file forever, even if the source website disappears.** This is the single most reliable source of rights data. [IPTC] [XMP]

The tool uses three libraries to read them: `Pillow` for EXIF, `IPTCInfo3` for IPTC, `python-xmp-toolkit` for XMP.

### Step 4 — Look for a C2PA manifest
Some images carry a **Content Credentials** manifest — a cryptographically signed block declaring "I was made by Adobe Firefly" or "I was edited in Photoshop with these operations" or "I am AI-generated." Adobe, Microsoft, OpenAI, Leica, and Sony all write these.

The tool uses the `c2pa-python` library to read and verify the manifest. If found, you get a clear yes/no on:

- Is this image AI-generated?
- What tool created it?
- What edits has it been through?

> *Why this matters for AI training:* Auditors and regulators will ask "how many of your training images are themselves AI-generated?" Without C2PA, the answer is a shrug. With C2PA, the answer is a number. [C2PA]

### Step 5 — Ask Chrome where the file came from
Chrome stores every download in a local SQLite database called `History`. The tool copies that database to a temp location (so Chrome's lock doesn't block it), then runs a SQL query:

> "Find the download whose target filename matches this one and whose end time is within two minutes of this file's modification time."

If there's a match, Chrome tells you:

- The **direct URL** Chrome fetched (the actual image URL)
- The **referrer** (the page you were on)
- The **tab URL** (the address bar at the time)

For Google Images specifically, the tool parses the `imgurl=` query parameter out of the referrer to recover the **original site** the image was hosted on — not just Google's CDN.

> *Why this matters:* This is what makes browser saves work without a browser extension. Every modern Chromium browser does this. Firefox stores the same data in `places.sqlite` (different schema, same idea).

### Step 6 — Visit the source page and read its public metadata
If we have a source page URL, the tool fetches that page (politely, with a normal browser User-Agent) and looks at four kinds of structured metadata in the HTML:

- **OpenGraph tags** — `<meta property="og:author">`, `<meta property="og:site_name">`. Used by Facebook, Twitter, almost every modern site.
- **Schema.org JSON-LD** — script blocks with structured data. The `ImageObject` type includes `author`, `license`, `copyrightHolder`, `copyrightYear`.
- **Twitter Card tags** — additional author and site info.
- **`<link rel="license">`** — explicit machine-readable license declaration. Used by Creative Commons properly-marked content. [CC]

These give you the public-facing answer to "who made this and what's the license."

### Step 7 — If it's a known platform, ask its API directly
HTML scraping is unreliable. Many platforms publish proper APIs that return structured data. The tool calls them when it recognises the platform:

| Platform | API gives you |
|---|---|
| Unsplash | photographer object, official license, EXIF, location |
| Pexels | photographer, official license |
| Flickr | numeric license code (maps to Creative Commons / public domain) |
| ArtStation | artist, medium, software used, **`is_ai_generated` flag** |
| Pixiv | tags, restrictions, **`ai_type` field** (0 = not AI, 1 = AI-assisted, 2 = AI-generated) |
| DeviantArt | license object, mature flag |
| CivitAI | full image record + linked model + creator |

> *Why this matters:* Pixiv's `ai_type` is the platform's own declaration of AI status — far more reliable than guessing. It became a labeling field in 2023 to comply with regulators.

### Step 8 — Check the AI training opt-out signals
The creator may have explicitly said "do not use this for AI training." There are four places to check:

- **`ai.txt`** — a file at the domain root (like `robots.txt`) listing AI agents that are not welcome. Spawning.ai's standard, honored by Stability AI and Hugging Face. [Spawning]
- **`tdm-reservation` HTTP header** — a draft web standard for per-URL opt-out
- **`robots.txt`** — checked for entries like `User-agent: GPTBot Disallow: /`
- **IPTC `Data Mining` field** — the in-file standard from IPTC's PLUS vocabulary, with values like "Prohibited for Generative AI/ML training" [IPTC]

If any of these say "no," the tool flags the file. Whether you respect that is your call — but you'll know.

### Step 9 — Cross-check against known AI training datasets
The tool can (optionally) ask:

- **Spawning's Do Not Train Registry** — has this file been opted out by its creator? [Spawning]
- **LAION-5B membership** — was this image in the dataset that trained Stable Diffusion? Checked via the `clip-retrieval` library against a local LAION index. [LAION]

> *Why this matters:* Knowing an image was used to train an existing public model tells you it's plausibly already "in the wild" for AI training — which is relevant context, not a permission, but useful when documenting your judgement.

### Step 10 — Archive the source page in case it disappears
The tool posts the source URL to the **Wayback Machine's Save API** (`https://web.archive.org/save/<url>`). The Wayback Machine returns a permalink. That permalink is recorded in the provenance.

> *Why this matters:* Websites change and disappear. If you're ever asked to prove what the page said when you downloaded the image — page content, license, attribution requirements — the Wayback snapshot is your evidence.

### Step 11 — Normalise the license to an SPDX identifier
A page that says "Creative Commons Attribution 4.0," another that says "CC BY 4.0," and a third with a CC URL all mean the same thing. The tool maps all of them to the SPDX short code `CC-BY-4.0` — a registered, machine-readable identifier used in software bill-of-materials standards.

> *Why this matters:* SPDX codes let you write a single rule like "include only CC-BY-4.0 and CC0-1.0" and have it work consistently. Free-text license strings cannot be filtered reliably.

### Step 12 — Compute a completeness score
Each provenance record gets a 0.0–1.0 score based on how many fields are filled in. Higher weights on the fields that matter most (source URL, license SPDX, AI-status known, opt-out checked). This is what the app shows as a colored ring on each thumbnail.

### Step 13 — Write everything to two places
- **A `.provenance.json` file** sits right next to the image. Move the image, move the JSON — provenance travels with the file. This is the portable, durable record.
- **A SQLite index** at `~/.provenance/index.sqlite`. This is what the app reads when you scroll the gallery — fast queries across 10,000 images take less than 100ms.

A CSV export is generated on demand for spreadsheet review.

### Step 14 — Push a live event to the UI
A WebSocket message goes out: "new asset captured." The Activity feed in the app updates in real time.

---

## 3. The Three User Flows

**Flow A — Use the browser as normal.** You download something to your watched folder. Steps 1–14 happen automatically in the background. The new asset appears in the Gallery within a few seconds.

**Flow B — Batch back-fill.** You point the tool at an existing folder full of images you downloaded last month. It runs steps 2–13 on every file. Browser-history matching uses each file's last-modified time to find the right history entry.

**Flow C — Manual capture.** You give the tool a direct URL. It downloads the image itself, then runs steps 2–13 with the URL already known.

---

## 4. The App — What You Actually See

Tauri is a Rust wrapper that gives a web app a native window. Inside the window is a React frontend styled with shadcn/ui — the same library Vercel and Linear use to get that clean modern look. Combined with Tailwind's design tokens set to match Apple's system colors, fonts (SF Pro on macOS), and spacing, the result feels native.

**Four screens:**

1. **Gallery** — every asset as a thumbnail. Each card has a colored ring showing completeness. Search by filename, URL, or hash. Filter by platform, AI-status, license, opt-out flag. Sort by date, completeness, platform. Click → opens the detail sheet from the right.

2. **Detail** — everything we know about one asset. Image preview, source URL with Wayback link, creator card, rights card with SPDX badge, AI-status card showing every opt-out signal we checked, embedded metadata accordion, dataset-membership card, full chronology timeline. Inline editing where you want to override a field manually.

3. **Audit** — a table of every gap in your dataset. "Missing source URL: 12 files." "No license detected: 28 files." "AI-status unknown: 7 files." Bulk-select and "Re-enrich" or "Re-check dataset membership."

4. **Activity** — a live stream of what's happening as the tool processes new files. Each card shows the step (downloading → reading XMP → checking opt-out → archiving → indexed) with elapsed time.

A sidebar with the four tabs plus settings stays visible. Top bar has search and a "what's running" indicator.

---

## 5. Why This Beats Anything Off the Shelf

There are pieces of this out there. **No single open-source tool combines them.** [Research]

- C2PA Python tools can *read* manifests, but don't capture browser provenance.
- Have I Been Trained can tell you LAION membership, but doesn't capture XMP/IPTC.
- ExifTool reads every embedded standard but isn't a workflow tool.
- Spawning's API lets you check opt-outs but doesn't write provenance records.

This tool **wires them all together** into one record per file, indexed and browseable. That's the gap.

---

## 6. References — Provenance Research

The standards and tools above are real and current. Sources from the research agent:

- **[C2PA] Content Authenticity Initiative**
  - C2PA Technical Specification v2.4: https://spec.c2pa.org/specifications/specifications/2.4/specs/C2PA_Specification.html
  - `c2pa-python` library: https://pypi.org/project/c2pa-python/
  - Wikipedia overview: https://en.wikipedia.org/wiki/Content_Authenticity_Initiative

- **[IPTC] IPTC Photo Metadata Standard (2025.1)** — adds four AI-related fields
  - https://iptc.org/standards/photo-metadata/iptc-standard/
  - 2025.1 AI properties announcement: https://iptc.org/news/iptc-photo-metadata-standard-2025-1-adds-ai-properties/

- **[XMP] Adobe Extensible Metadata Platform** (ISO 16684)
  - `python-xmp-toolkit`: https://pypi.org/project/python-xmp-toolkit/
  - XMP namespaces: https://developer.adobe.com/xmp/docs/xmp-namespaces/

- **[Spawning] Have I Been Trained / Spawning.ai**
  - https://haveibeentrained.com/
  - `ai.txt` standard guide: https://spawning.substack.com/p/the-spawning-guide-to-rights-reservations

- **[LAION] LAION-5B Dataset**
  - https://laion.ai/blog/laion-5b/
  - `clip-retrieval` library: https://github.com/rom1504/clip-retrieval

- **[CC] Creative Commons** — `<link rel="license">` machine-readable marking
  - https://wiki.creativecommons.org/wiki/CC_REL

- **[Research] Data Provenance Initiative** — audit of 4000+ training datasets
  - https://www.dataprovenance.org/
  - https://github.com/Data-Provenance-Initiative/Data-Provenance-Collection

---

## 7. One Final Plain-English Summary

You drop a picture into a folder. The tool grabs the file's fingerprint, opens the metadata hidden inside it, asks Chrome where it came from, visits the source page, calls the platform's API, checks the AI opt-out signals, archives the page on the Wayback Machine, looks up whether AI models were trained on it, normalises the license, scores how complete the record is, and writes a `.provenance.json` next to the image plus an entry in a local database. A second later, the picture shows up in your gallery with a colored ring telling you how good the record is — and you can click it to see every fact and every source.

That's the whole product.
