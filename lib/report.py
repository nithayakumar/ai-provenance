"""
Generate a self-contained HTML provenance report.

No external dependencies at render time — all CSS and JS are inlined.
Outputs a single .html file that can be emailed or opened offline.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from lib.storage import audit_gaps, query_assets


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _badge(text: str, colour: str) -> str:
    styles = {
        "green":  "#22c55e",
        "yellow": "#f59e0b",
        "red":    "#ef4444",
        "grey":   "#6b7280",
        "blue":   "#3b82f6",
    }
    bg = styles.get(colour, styles["grey"])
    return (
        f'<span style="background:{bg};color:#fff;padding:2px 7px;'
        f'border-radius:9px;font-size:11px;font-weight:600;">{text}</span>'
    )


def _completeness_badge(score) -> str:
    try:
        s = float(score)
    except (TypeError, ValueError):
        return _badge("?", "grey")
    if s >= 0.8:
        return _badge(f"{s:.0%}", "green")
    if s >= 0.5:
        return _badge(f"{s:.0%}", "yellow")
    return _badge(f"{s:.0%}", "red")


def _opt_out_badge(record: dict) -> str:
    opt_out = record.get("rights", {}).get("ai_training", {}).get("opt_out")
    if opt_out is True:
        return _badge("OPT-OUT", "red")
    if opt_out is False:
        return _badge("allowed", "green")
    return _badge("unknown", "grey")


def _ai_badge(record: dict) -> str:
    val = record.get("ai", {}).get("is_ai_generated")
    if val is True:
        return _badge("AI", "blue")
    if val is False:
        return _badge("human", "green")
    return _badge("?", "grey")


def _license_cell(record: dict) -> str:
    spdx = record.get("rights", {}).get("license_spdx", "")
    url  = record.get("rights", {}).get("license_url", "")
    if not spdx:
        return _badge("missing", "red")
    if url:
        return f'<a href="{url}" target="_blank" rel="noopener">{spdx}</a>'
    return spdx


def _source_cell(record: dict) -> str:
    url = record.get("source", {}).get("url", "")
    if not url:
        return _badge("missing", "red")
    short = url[:60] + "…" if len(url) > 60 else url
    return f'<a href="{url}" target="_blank" rel="noopener" title="{url}">{short}</a>'


def _author_cell(record: dict) -> str:
    name = record.get("creator", {}).get("name", "")
    url  = record.get("creator", {}).get("profile_url", "")
    if not name:
        return _badge("missing", "grey")
    if url:
        return f'<a href="{url}" target="_blank" rel="noopener">{name}</a>'
    return name


# ---------------------------------------------------------------------------
# Row builder
# ---------------------------------------------------------------------------

def _build_row(record: dict, index: int) -> str:
    file_  = record.get("file", {})
    source = record.get("source", {})
    comp   = record.get("completeness", {})
    score  = comp.get("score") if isinstance(comp, dict) else comp

    sha_short = (file_.get("sha256") or "")[:12]
    filename  = file_.get("filename", "—")
    platform  = source.get("platform", "—")
    captured  = (record.get("captured_at") or "")[:10]

    wayback = source.get("wayback_url", "")
    wayback_cell = (
        f'<a href="{wayback}" target="_blank" rel="noopener" title="Archived snapshot">📦</a>'
        if wayback else "—"
    )

    opt_out_raw = record.get("rights", {}).get("ai_training", {}).get("opt_out")
    row_class = "row-optout" if opt_out_raw is True else ""

    return f"""
    <tr class="{row_class}"
        data-platform="{platform}"
        data-optout="{str(opt_out_raw).lower()}"
        data-completeness="{score or 0}">
      <td>{index}</td>
      <td title="{file_.get('sha256','')}"><code>{sha_short}</code></td>
      <td>{filename}</td>
      <td>{_source_cell(record)}</td>
      <td>{_author_cell(record)}</td>
      <td>{_license_cell(record)}</td>
      <td>{_ai_badge(record)}</td>
      <td>{_opt_out_badge(record)}</td>
      <td>{_completeness_badge(score)}</td>
      <td>{platform}</td>
      <td>{captured}</td>
      <td>{wayback_cell}</td>
    </tr>"""


# ---------------------------------------------------------------------------
# Summary cards
# ---------------------------------------------------------------------------

def _summary_cards(gaps: dict) -> str:
    total     = gaps.get("total", 0)
    no_url    = gaps.get("missing_source_url", 0)
    no_lic    = gaps.get("missing_license", 0)
    no_ai     = gaps.get("missing_ai_status", 0)
    opted_out = gaps.get("opted_out", 0)
    avg_comp  = gaps.get("avg_completeness", 0)

    def card(label, value, colour="var(--fg)"):
        return f"""
        <div class="card">
          <div class="card-value" style="color:{colour}">{value}</div>
          <div class="card-label">{label}</div>
        </div>"""

    url_col  = "#ef4444" if no_url  else "var(--fg)"
    lic_col  = "#ef4444" if no_lic  else "var(--fg)"
    ai_col   = "#f59e0b" if no_ai   else "var(--fg)"
    opt_col  = "#ef4444" if opted_out else "var(--fg)"

    return f"""
    <div class="cards">
      {card("Total assets", total)}
      {card("Avg completeness", f"{avg_comp:.0%}")}
      {card("Missing source URL", no_url,  url_col)}
      {card("Missing license",    no_lic,  lic_col)}
      {card("Unknown AI status",  no_ai,   ai_col)}
      {card("Opted out of training", opted_out, opt_col)}
    </div>"""


# ---------------------------------------------------------------------------
# Full HTML
# ---------------------------------------------------------------------------

_CSS = """
:root { --bg: #0f172a; --surface: #1e293b; --border: #334155;
        --fg: #f1f5f9; --muted: #94a3b8; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: var(--bg); color: var(--fg); font-size: 14px; line-height: 1.5; }
header { background: var(--surface); border-bottom: 1px solid var(--border);
         padding: 16px 24px; display: flex; align-items: center; gap: 12px; }
header h1 { font-size: 18px; font-weight: 700; }
header .sub { color: var(--muted); font-size: 13px; }
main { padding: 24px; }
.cards { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 24px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
        padding: 16px 20px; min-width: 150px; }
.card-value { font-size: 28px; font-weight: 700; }
.card-label { color: var(--muted); font-size: 12px; margin-top: 2px; }
.filters { display: flex; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; }
.filters input, .filters select {
  background: var(--surface); border: 1px solid var(--border);
  color: var(--fg); padding: 6px 10px; border-radius: 6px; font-size: 13px; }
.filters input:focus, .filters select:focus { outline: 2px solid #3b82f6; }
.table-wrap { overflow-x: auto; border-radius: 8px; border: 1px solid var(--border); }
table { width: 100%; border-collapse: collapse; }
th { background: var(--surface); color: var(--muted); font-weight: 600; font-size: 12px;
     text-transform: uppercase; letter-spacing: 0.05em; padding: 10px 12px;
     text-align: left; position: sticky; top: 0; z-index: 1;
     border-bottom: 1px solid var(--border); }
td { padding: 9px 12px; border-bottom: 1px solid var(--border); vertical-align: middle; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: rgba(255,255,255,0.03); }
tr.row-optout td { background: rgba(239,68,68,0.07); }
a { color: #60a5fa; text-decoration: none; }
a:hover { text-decoration: underline; }
code { font-family: monospace; font-size: 12px; color: var(--muted); }
.hidden { display: none !important; }
footer { color: var(--muted); font-size: 12px; text-align: center; padding: 24px; }
"""

_JS = """
const rows = Array.from(document.querySelectorAll('tbody tr'));
const search   = document.getElementById('search');
const platform = document.getElementById('platform');
const optout   = document.getElementById('optout');
const counter  = document.getElementById('counter');

function applyFilters() {
  const q = search.value.toLowerCase();
  const p = platform.value;
  const o = optout.value;
  let visible = 0;
  rows.forEach(r => {
    const text = r.textContent.toLowerCase();
    const rp = r.dataset.platform || '';
    const ro = r.dataset.optout || '';
    const show = (!q || text.includes(q))
              && (!p || rp === p)
              && (!o || ro === o);
    r.classList.toggle('hidden', !show);
    if (show) visible++;
  });
  counter.textContent = `${visible} of ${rows.length} assets`;
}
search.addEventListener('input', applyFilters);
platform.addEventListener('change', applyFilters);
optout.addEventListener('change', applyFilters);
"""


def generate(output_path: str, limit: int = 5000) -> int:
    """
    Generate a self-contained HTML report.
    Returns the number of assets included.
    """
    records = query_assets(limit=limit)
    gaps    = audit_gaps()
    now     = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Collect unique platforms for the filter dropdown
    platforms = sorted({r.get("source", {}).get("platform") or "unknown" for r in records})
    platform_opts = "\n".join(
        f'<option value="{p}">{p}</option>' for p in platforms
    )

    rows_html = "\n".join(_build_row(r, i + 1) for i, r in enumerate(records))
    cards_html = _summary_cards(gaps)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Provenance Report — {now}</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <div>
    <h1>Provenance Report</h1>
    <div class="sub">Generated {now} &nbsp;·&nbsp; {gaps.get('total',0)} assets</div>
  </div>
</header>
<main>
{cards_html}
<div class="filters">
  <input id="search" type="search" placeholder="Search filename, author, URL…" style="flex:1;min-width:200px">
  <select id="platform">
    <option value="">All platforms</option>
    {platform_opts}
  </select>
  <select id="optout">
    <option value="">All opt-out status</option>
    <option value="true">Opted out</option>
    <option value="false">Allowed</option>
    <option value="none">Unknown</option>
  </select>
  <span id="counter" style="line-height:2;color:var(--muted);font-size:13px">
    {len(records)} of {len(records)} assets
  </span>
</div>
<div class="table-wrap">
<table>
<thead>
  <tr>
    <th>#</th><th>SHA256</th><th>Filename</th><th>Source URL</th>
    <th>Author</th><th>License</th><th>AI</th><th>Opt-out</th>
    <th>Complete</th><th>Platform</th><th>Captured</th><th>Archive</th>
  </tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
</div>
</main>
<footer>ai-provenance · <a href="https://github.com/nithayakumar/ai-provenance" target="_blank" rel="noopener">github.com/nithayakumar/ai-provenance</a></footer>
<script>{_JS}</script>
</body>
</html>"""

    Path(output_path).write_text(html, encoding="utf-8")
    return len(records)
