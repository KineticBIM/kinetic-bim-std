# -*- coding: utf-8 -*-
"""
reporters.py
============

Turn findings into output. Two reporters for now:
    - render_html(): a self-contained HTML file with a traffic-light summary.
    - print_console(): pyRevit output window using its formatting helpers.
"""

import os
import datetime


SEVERITY_ORDER = {"FAIL": 0, "WARN": 1, "INFO": 2}
SEVERITY_COLOR = {"FAIL": "#c0392b", "WARN": "#e67e22", "INFO": "#2980b9"}


def _sort_findings(findings):
    return sorted(findings, key=lambda f: (SEVERITY_ORDER.get(f.severity, 9),
                                            f.category))


def _summary_counts(findings):
    counts = {"FAIL": 0, "WARN": 0, "INFO": 0}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

HTML_TEMPLATE = u"""<!doctype html>
<html><head><meta charset="utf-8"/>
<title>{title}</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif;
          margin: 24px; color: #222; }}
  h1   {{ margin: 0 0 4px; }}
  .meta {{ color:#666; font-size: 13px; margin-bottom: 18px; }}
  .summary {{ display:flex; gap:12px; margin: 16px 0 24px; }}
  .pill {{ padding: 8px 14px; border-radius: 999px; color:white;
          font-weight: 600; }}
  .finding {{ border-left: 4px solid #ccc; padding: 10px 14px;
              margin: 8px 0; background: #fafafa; }}
  .finding.FAIL {{ border-color: #c0392b; }}
  .finding.WARN {{ border-color: #e67e22; }}
  .finding.INFO {{ border-color: #2980b9; }}
  .sev {{ display:inline-block; min-width: 46px; padding: 2px 6px;
          border-radius: 4px; color: white; font-size: 11px;
          font-weight: 700; text-align:center; margin-right: 8px; }}
  details {{ margin-top: 6px; }}
  table  {{ border-collapse: collapse; margin-top: 6px; font-size: 12px; }}
  th, td {{ border: 1px solid #ddd; padding: 4px 8px; text-align: left; }}
  th     {{ background:#eee; }}
</style></head>
<body>
<h1>{title}</h1>
<div class="meta">{project} &middot; generated {now}</div>
<div class="summary">
  <div class="pill" style="background:{c_fail}">FAIL: {n_fail}</div>
  <div class="pill" style="background:{c_warn}">WARN: {n_warn}</div>
  <div class="pill" style="background:{c_info}">INFO: {n_info}</div>
</div>
{body}
</body></html>
"""


def _details_table(details):
    if not details:
        return ""
    keys = list(details[0].keys())
    head = "".join("<th>{0}</th>".format(k) for k in keys)
    rows = []
    for d in details[:100]:
        cells = "".join("<td>{0}</td>".format(d.get(k, "")) for k in keys)
        rows.append("<tr>{0}</tr>".format(cells))
    more = ("<div><em>...{0} more rows truncated</em></div>".format(
        len(details) - 100) if len(details) > 100 else "")
    return ("<details><summary>Details ({0})</summary>"
            "<table><tr>{1}</tr>{2}</table>{3}</details>").format(
                len(details), head, "".join(rows), more)


def render_html(title, project_label, findings, out_path):
    findings = _sort_findings(findings)
    counts = _summary_counts(findings)

    body_parts = []
    for f in findings:
        sev_html = ('<span class="sev" style="background:{0}">{1}</span>'
                    .format(SEVERITY_COLOR.get(f.severity, "#888"), f.severity))
        body_parts.append(
            '<div class="finding {sev}"><strong>{cat}</strong> {pill}'
            '<div>{msg}</div>{tbl}</div>'.format(
                sev=f.severity, cat=f.category, pill=sev_html,
                msg=f.message, tbl=_details_table(f.details),
            )
        )

    html = HTML_TEMPLATE.format(
        title=title,
        project=project_label,
        now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        c_fail=SEVERITY_COLOR["FAIL"], c_warn=SEVERITY_COLOR["WARN"],
        c_info=SEVERITY_COLOR["INFO"],
        n_fail=counts["FAIL"], n_warn=counts["WARN"], n_info=counts["INFO"],
        body="".join(body_parts) or "<p>No findings.</p>",
    )

    folder = os.path.dirname(out_path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    with open(out_path, "w") as fh:
        fh.write(html.encode("utf-8") if isinstance(html, unicode) else html)
    return out_path


# ---------------------------------------------------------------------------
# pyRevit console
# ---------------------------------------------------------------------------

def print_console(title, findings, output):
    """
    `output` is the pyRevit script.output object. Falls back to print().
    """
    findings = _sort_findings(findings)
    counts = _summary_counts(findings)

    write = output.print_md if output else (lambda s: None)
    if not output:
        write = lambda s: None  # we'll just rely on HTML
        return

    output.print_md("# {0}".format(title))
    output.print_md(
        "**FAIL:** {FAIL}  |  **WARN:** {WARN}  |  **INFO:** {INFO}".format(**counts))
    output.print_md("---")

    for f in findings:
        output.print_md("### [{sev}] {cat}".format(sev=f.severity, cat=f.category))
        output.print_md(f.message)
        if f.details:
            sample = f.details[:10]
            for d in sample:
                output.print_md("- " + ", ".join(
                    "{0}: {1}".format(k, v) for k, v in d.items()))
            if len(f.details) > 10:
                output.print_md("_...{0} more_".format(len(f.details) - 10))
