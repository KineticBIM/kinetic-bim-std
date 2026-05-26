# -*- coding: utf-8 -*-
"""Management-summary report.

Name kept as `pdf_summary` for orchestrator compatibility, but the
output is **HTML** - rendered with the same self-contained-HTML
pattern as `audit_engine/reporters.py`. HTML opens in any browser,
prints to PDF (Ctrl+P -> Save as PDF) cleanly, and works without
any third-party libraries.

The output file is written with a `.html` extension regardless of
what the caller passes for `out_path`. The function returns the
actual path written.

Includes:
  - Project header + run metadata
  - Headline metrics (active / new / resolved / total)
  - Refresh report (when present)
  - Per-status / per-discipline-pair / per-test breakdown tables
  - Embedded clash thumbnails (data-URI base64), if available

Pure stdlib. IronPython 2.7 / CPython 3 compatible.
"""

from __future__ import print_function, division, absolute_import

import base64
import io
import os

from clash_coordination.data import models


# ---------------------------------------------------------------------------
# Palette - matches the Excel-report colour intent (described in markup)
# ---------------------------------------------------------------------------

NAVY = "#1F3A5F"
GREY = "#7F8C8D"
LINE = "#D0D4D8"
STATUS_FILLS = {
    "new":      "#F4D03F",
    "active":   "#EB984E",
    "reviewed": "#85C1E9",
    "approved": "#82E0AA",
    "resolved": "#27AE60",
}


CSS = """
* { box-sizing: border-box; }
body { font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
       margin: 28px; color: #222; }
h1 { margin: 0 0 4px; color: """ + NAVY + """; font-size: 28px; }
h2 { margin: 28px 0 10px; color: """ + NAVY + """; font-size: 18px;
     border-bottom: 1px solid """ + LINE + """; padding-bottom: 4px; }
.subtle { color: """ + GREY + """; font-size: 13px; }
.meta { margin-top: 8px; font-size: 13px; }
.meta b { display: inline-block; min-width: 130px; color: """ + GREY + """;
          font-weight: 500; }
.metrics { display: flex; gap: 18px; margin: 22px 0 8px; flex-wrap: wrap; }
.metric { min-width: 130px; padding: 16px 20px; background: #f5f6f8;
          border-radius: 6px; border-left: 4px solid """ + NAVY + """; }
.metric .v { font-size: 26px; font-weight: 700; color: """ + NAVY + """;
             line-height: 1.0; }
.metric .l { color: """ + GREY + """; font-size: 11px;
             text-transform: uppercase; letter-spacing: 0.04em;
             margin-top: 6px; }
table { border-collapse: collapse; margin-top: 6px; font-size: 13px;
        width: 100%; max-width: 720px; }
th, td { border: 1px solid """ + LINE + """; padding: 6px 10px;
         text-align: left; }
th { background: """ + NAVY + """; color: #fff; font-weight: 600;
     font-size: 12px; text-align: left; }
tr:nth-child(even) td { background: #fafafa; }
.count-col { text-align: right; width: 80px; }
.pill { display: inline-block; padding: 2px 8px; border-radius: 999px;
        color: #2c3e50; font-size: 11px; font-weight: 600; }
.thumbs { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px;
          margin-top: 8px; }
.thumb { background: #f9f9f9; padding: 8px; border: 1px solid """ + LINE + """;
         border-radius: 4px; }
.thumb img { width: 100%; max-height: 220px; object-fit: contain;
             display: block; margin-bottom: 6px; }
.thumb .cap { font-size: 12px; color: #444; }
.alert { background: #fff4e3; border-left: 4px solid #e67e22;
         padding: 10px 14px; margin-top: 8px; font-size: 13px; }
@media print {
  body { margin: 14mm; }
  .metric { background: #fff; border: 1px solid """ + LINE + """; }
  th { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _esc(text):
    if text is None:
        return ""
    s = str(text)
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;").replace("'", "&#39;"))


def _status_pill(status):
    s = (status or "").lower()
    colour = STATUS_FILLS.get(s, "#ECF0F1")
    return ('<span class="pill" style="background:{0};">{1}</span>'.format(
        colour, _esc(status or "?")))


def _metric_block(label, value):
    return (
        '<div class="metric"><div class="v">{0}</div>'
        '<div class="l">{1}</div></div>').format(_esc(value), _esc(label))


def _embed_image(path, max_bytes=1024 * 1024):
    """Return a `data:image/png;base64,...` URI for `path`, or ""
    if the file is unreadable or larger than `max_bytes`."""
    try:
        size = os.path.getsize(path)
        if size > max_bytes:
            return ""
        with open(path, "rb") as fh:
            data = fh.read()
        encoded = base64.b64encode(data).decode("ascii")
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        mime = "image/" + (ext if ext in ("png", "jpg", "jpeg", "gif") else "png")
        if ext == "jpg":
            mime = "image/jpeg"
        return "data:{0};base64,{1}".format(mime, encoded)
    except (OSError, IOError):
        return ""


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _header_section(run):
    return (
        '<h1>Clash Coordination Summary</h1>'
        '<div class="subtle">{0}</div>'
        '<div class="meta"><b>Project</b> {1} &nbsp; <b>Run date</b> {2}</div>'
        '<div class="meta"><b>Federated model</b> <code>{3}</code></div>'
    ).format(
        _esc(run.project_name or "(no project name)"),
        _esc(run.project_number or "-"),
        _esc(run.run_date or "-"),
        _esc(run.nwf_path or "-"),
    )


def _metrics_section(run):
    active = models.active_count(run)
    new_v = run.delta_new if run.delta_new is not None else "-"
    res_v = run.delta_resolved if run.delta_resolved is not None else "-"
    blocks = "".join([
        _metric_block("Active clashes", active),
        _metric_block("New this run", new_v),
        _metric_block("Resolved this run", res_v),
        _metric_block("Total tracked", run.total),
    ])
    note = ""
    if run.previous_snapshot_date:
        note = (
            '<div class="meta">Deltas computed against previous snapshot '
            'from <b style="min-width:0;">{0}</b>.</div>'.format(
                _esc(run.previous_snapshot_date)))
    return '<div class="metrics">' + blocks + '</div>' + note


def _refresh_section(run):
    rr = run.refresh_report
    if rr is None:
        return ""
    parts = ['<h2>Federated model refresh</h2>']
    parts.append(
        '<div class="meta">{0} refreshed &middot; {1} missing &middot; '
        '{2} failed</div>'.format(
            len(rr.refreshed), len(rr.missing), len(rr.failed)))
    if rr.missing:
        items = "".join('<li><code>{0}</code></li>'.format(_esc(m))
                        for m in rr.missing)
        parts.append('<div class="alert"><b>Missing link files</b><ul>' +
                     items + '</ul></div>')
    return "".join(parts)


def _by_status_section(run):
    if not run.total_by_status:
        return ""
    parts = ['<h2>Clashes by status</h2>',
             '<table><thead><tr><th>Status</th><th class="count-col">Count</th></tr></thead><tbody>']
    for status, count in sorted(run.total_by_status.items(),
                                  key=lambda kv: kv[1], reverse=True):
        parts.append('<tr><td>{0}</td><td class="count-col">{1}</td></tr>'.format(
            _status_pill(status), count))
    parts.append('</tbody></table>')
    return "".join(parts)


def _by_pair_section(run):
    if not run.total_by_discipline_pair:
        return ""
    parts = ['<h2>Clashes by discipline pair</h2>',
             '<table><thead><tr><th>Discipline pair</th><th class="count-col">Count</th></tr></thead><tbody>']
    for pair, count in sorted(run.total_by_discipline_pair.items(),
                                key=lambda kv: kv[1], reverse=True):
        parts.append('<tr><td>{0}</td><td class="count-col">{1}</td></tr>'.format(
            _esc(pair), count))
    parts.append('</tbody></table>')
    return "".join(parts)


def _by_test_section(run):
    if not run.tests:
        return ""
    parts = ['<h2>Clashes by test</h2>',
             '<table><thead><tr><th>Test</th>'
             '<th class="count-col">Total</th>'
             '<th class="count-col">New</th>'
             '<th class="count-col">Active</th>'
             '<th class="count-col">Resolved</th></tr></thead><tbody>']
    for test in run.tests:
        counts = test.counts_by_status()
        resolved = counts.get("resolved", 0) + counts.get("approved", 0)
        parts.append(
            '<tr><td>{0}</td>'
            '<td class="count-col">{1}</td>'
            '<td class="count-col">{2}</td>'
            '<td class="count-col">{3}</td>'
            '<td class="count-col">{4}</td></tr>'.format(
                _esc(test.name), test.count,
                counts.get("new", 0),
                counts.get("active", 0),
                resolved,
            ))
    parts.append('</tbody></table>')
    return "".join(parts)


def _thumbnails_section(run, max_thumbs=12):
    candidates = []
    for test in run.tests:
        for c in test.clashes:
            if c.screenshot_path and os.path.isfile(c.screenshot_path):
                candidates.append(c)
    if not candidates:
        return ""
    candidates.sort(
        key=lambda c: abs(c.distance_m) if c.distance_m is not None else 0,
        reverse=True,
    )
    chosen = candidates[:max_thumbs]

    parts = ['<h2>Clash thumbnails</h2><div class="thumbs">']
    for c in chosen:
        src = _embed_image(c.screenshot_path)
        if not src:
            continue
        cap = "<b>{0}</b> &middot; {1} &middot; {2}".format(
            _esc(c.name or c.clash_id),
            _esc(c.discipline_pair),
            _status_pill(c.status),
        )
        parts.append(
            '<div class="thumb"><img src="{0}" alt=""/>'
            '<div class="cap">{1}</div></div>'.format(src, cap))
    parts.append('</div>')
    return "".join(parts)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def write_pdf_summary(run, out_path, include_screenshots=True, max_thumbnails=12):
    """Write the HTML summary for `run` to `out_path`. The file is
    always written with a `.html` extension - we accept the legacy
    `pdf_summary` name for orchestrator compatibility. Returns the
    actual path written.
    """
    if out_path.lower().endswith(".pdf"):
        out_path = out_path[:-4] + ".html"

    folder = os.path.dirname(os.path.abspath(out_path))
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)

    body_parts = [
        _header_section(run),
        _metrics_section(run),
        _refresh_section(run),
        _by_status_section(run),
        _by_pair_section(run),
        _by_test_section(run),
    ]
    if include_screenshots:
        body_parts.append(_thumbnails_section(run, max_thumbnails))

    html = (
        '<!doctype html><html><head><meta charset="utf-8"/>'
        '<title>{0}</title><style>{1}</style></head><body>'
        '{2}'
        '<div class="subtle" style="margin-top:32px;">'
        'Kinetic BIM Coordination &middot; generated {3}</div>'
        '</body></html>'
    ).format(
        _esc(run.project_name or "Clash Coordination Report"),
        CSS,
        "".join(body_parts),
        _esc(run.run_timestamp or ""),
    )

    with io.open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return os.path.abspath(out_path)
