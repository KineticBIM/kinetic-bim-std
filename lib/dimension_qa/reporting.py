# -*- coding: utf-8 -*-
"""HTML + CSV report rendering for Auto Dimension.

Mirrors annotation_qa.reporting in shape: per-profile sections in
HTML, flat per-element rows in CSV (UTF-8 BOM so Excel auto-detects
the encoding).

The "active filters" line for each profile additionally calls out the
measurement reference + reference target + offset_distance, which are
the three settings that distinguish dimensioning runs from one-off
audits.
"""

import csv
import os
import datetime


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def report_path(doc, ext="html"):
    """Build a timestamped report path under <project>/.bim/reports/.

    ext switches between formats - "html" / "csv". Falls back to the
    user's home folder when the project is unsaved.
    """
    pn = doc.PathName
    base = os.path.dirname(pn) if pn else os.path.expanduser("~")
    folder = os.path.join(base, ".bim", "reports")
    if not os.path.isdir(folder):
        os.makedirs(folder)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    return os.path.join(folder, "auto_dimension_{0}.{1}".format(stamp, ext))


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------

def summary_counts(records):
    """Headline counts. Operates on any record subset."""
    return {
        "total":               len(records),
        "audit_eligible":      sum(1 for r in records if r["audit_eligible"]),
        "eligible":            sum(1 for r in records if r["eligible"]),
        "already_dimensioned": sum(1 for r in records if r.get("already_dimensioned")),
        "placed":              sum(1 for r in records if r.get("placed")),
        "failed":              sum(1 for r in records if r.get("placed") is False),
    }


def breakdown_by_rule(records):
    out = {}
    for r in records:
        if r.get("audit_eligible"):
            continue
        rule = r.get("failing_rule") or "(unknown)"
        out[rule] = out.get(rule, 0) + 1
    return out


def group_by_profile(records, profiles):
    """Bucket records by profile_key in the supplied profile order.

    Records whose profile_key isn't in `profiles` end up in a single
    trailing "(Unattributed)" bucket.
    """
    buckets = {}
    for r in records:
        key = r.get("profile_key")
        buckets.setdefault(key, []).append(r)

    ordered = []
    for profile in profiles:
        if profile.key in buckets:
            ordered.append((profile, buckets.pop(profile.key)))

    leftover = []
    for _, recs in buckets.items():
        leftover.extend(recs)
    if leftover:
        ordered.append((None, leftover))
    return ordered


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def render_html(records, view_name, scan_options, profiles, out_path):
    """Render scan + placement results to an HTML report.

    One section per profile with that profile's active-filters line,
    counts, exclusions table, and per-element rows.
    """
    counts = summary_counts(records)
    title = _scan_title(profiles)

    cards = [
        '<div class="card"><b>{0}</b>Total scanned</div>'.format(counts["total"]),
        '<div class="card"><b>{0}</b>Eligible</div>'.format(counts["eligible"]),
        '<div class="card"><b>{0}</b>Already dimensioned</div>'.format(
            counts["already_dimensioned"]),
        '<div class="card"><b>{0}</b>Placed</div>'.format(counts["placed"]),
        '<div class="card"><b>{0}</b>Failed</div>'.format(counts["failed"]),
    ]

    sections_html = _render_profile_sections(records, profiles)

    html = _HTML_TEMPLATE.format(
        title=_escape("Auto Dimension - {0}".format(title)),
        view=_escape(view_name),
        ts=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        cards="\n  ".join(cards),
        sections=sections_html,
    )

    data = html.encode("utf-8") if isinstance(html, unicode) else html
    fh = open(out_path, "wb")
    try:
        fh.write(data)
    finally:
        fh.close()
    return out_path


def _scan_title(profiles):
    if not profiles:
        return "(no profiles)"
    seen = []
    for p in profiles:
        try:
            from bim_core.core import discipline_config
            label = discipline_config.get(p.discipline_key).label
        except KeyError:
            label = p.discipline_key or "Other"
        if label not in seen:
            seen.append(label)
    return " + ".join(seen)


def _render_profile_sections(records, profiles):
    grouped = group_by_profile(records, profiles)
    if not grouped and not profiles:
        return "<p class='meta'>(no records)</p>"

    parts = []
    for profile, recs in grouped:
        parts.append(_render_one_profile(profile, recs))

    rendered_keys = set()
    for profile, _ in grouped:
        rendered_keys.add(profile.key if profile is not None else None)
    for profile in profiles:
        if profile.key not in rendered_keys:
            parts.append(_render_one_profile(profile, []))
    return "\n".join(parts)


def _render_one_profile(profile, recs):
    if profile is None:
        title = "(Unattributed)"
        filters_line = "(no profile)"
        enabled_meta = ""
    else:
        title = _escape(profile.label)
        filters_line = _escape(profile.active_rule_summary())
        enabled_meta = (
            "" if profile.enabled
            else " <span class='meta' style='color:#a40'>(disabled)</span>")

    counts = summary_counts(recs)
    breakdown = breakdown_by_rule(recs)

    rule_rows = []
    for name in sorted(breakdown.keys()):
        rule_rows.append(
            "<tr><td>{0}</td><td>{1}</td></tr>".format(
                _escape(name), breakdown[name]))
    rule_table = (
        "<table class='rule-tbl'><thead><tr><th>Rule</th>"
        "<th>Excluded</th></tr></thead><tbody>{0}</tbody></table>".format(
            "\n".join(rule_rows))
        if rule_rows
        else "<p class='meta'>(no exclusions)</p>"
    )

    rows = "\n".join(_row_html(r) for r in recs)
    rows = rows or _EMPTY_ROW

    return _PROFILE_TEMPLATE.format(
        title=title,
        enabled_meta=enabled_meta,
        filters=filters_line,
        total=counts["total"],
        eligible=counts["eligible"],
        already=counts["already_dimensioned"],
        placed=counts["placed"],
        failed=counts["failed"],
        rule_table=rule_table,
        rows=rows,
    )


def _row_html(r):
    if r.get("placed"):
        status = "Placed"
    elif r.get("placed") is False:
        status = "Failed: {0}".format(_escape(r.get("place_error") or ""))
    elif r["eligible"]:
        status = "Eligible (not placed)"
    else:
        status = "Skipped: {0}".format(_escape(r["skip_reason"] or ""))

    length = "{0:.0f}".format(r["length_mm"]) if r["length_mm"] is not None else "-"
    sys_cls = r.get("system_classification") or "-"

    return (
        "<tr><td>{0}</td><td>{1}</td><td>{2}</td>"
        "<td>{3}</td><td>{4}</td><td>{5}</td><td>{6}</td></tr>"
    ).format(
        r["id"],
        _escape(r["name"]),
        length,
        _escape(sys_cls),
        _escape(r.get("failing_rule") or "-"),
        "yes" if r.get("already_dimensioned") else "no",
        status,
    )


def _escape(text):
    if text is None:
        return ""
    s = text if isinstance(text, basestring) else str(text)
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;"))


_EMPTY_ROW = (
    "<tr><td colspan='7' style='color:#888;font-style:italic'>"
    "no records</td></tr>"
)

_PROFILE_TEMPLATE = u"""<section class='profile'>
  <h2>{title}{enabled_meta}</h2>
  <div class='meta filters'>Active filters: {filters}</div>
  <div class='profile-cards'>
    <span class='pill'>{total} scanned</span>
    <span class='pill'>{eligible} eligible</span>
    <span class='pill'>{already} already dimensioned</span>
    <span class='pill'>{placed} placed</span>
    <span class='pill'>{failed} failed</span>
  </div>
  {rule_table}
  <table>
    <thead><tr>
      <th>Id</th><th>Element</th><th>Length (mm)</th>
      <th>System</th><th>Failing rule</th>
      <th>Dim'd before</th><th>Outcome</th>
    </tr></thead>
    <tbody>
{rows}
    </tbody>
  </table>
</section>"""

_HTML_TEMPLATE = u"""<!doctype html>
<html><head><meta charset="utf-8"><title>Auto Dimension Report</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#222}}
h1{{margin:0 0 8px 0}}
h2{{font-size:15px;margin:22px 0 6px}}
.meta{{color:#666;font-size:13px}}
.cards{{display:flex;gap:12px;margin:14px 0 20px;flex-wrap:wrap}}
.card{{padding:10px 16px;border-radius:6px;background:#f3f3f3;min-width:120px;font-size:13px}}
.card b{{display:block;font-size:20px;color:#111}}
section.profile{{margin:18px 0;padding:6px 0;border-top:1px solid #eee}}
.filters{{margin:0 0 8px 0;font-style:italic}}
.profile-cards{{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0 10px}}
.pill{{padding:3px 10px;border-radius:10px;background:#eef;font-size:12px;color:#224}}
table{{border-collapse:collapse;width:100%;font-size:12px;margin-top:4px}}
th,td{{border:1px solid #ddd;padding:5px 7px;text-align:left;vertical-align:top}}
th{{background:#fafafa}}
tr:nth-child(even) td{{background:#fbfbfb}}
.rule-tbl{{width:auto;margin-bottom:10px}}
</style></head><body>
<h1>{title}</h1>
<div class="meta">View: <b>{view}</b> &middot; Generated {ts}</div>
<div class="cards">
  {cards}
</div>
<h2>Results by profile</h2>
{sections}
</body></html>"""


# ---------------------------------------------------------------------------
# CSV / Excel export (mirror annotation_qa)
# ---------------------------------------------------------------------------

_UTF8_BOM = b"\xef\xbb\xbf"

CSV_HEADER = (
    "Profile",
    "Discipline",
    "Subcategory",
    "Category",
    "Element ID",
    "Element name",
    "Length (mm)",
    "System classification",
    "Audit eligible",
    "Eligible",
    "Already dimensioned",
    "Failing rule",
    "Skip reason",
    "Placed",
    "Place error",
    "Measurement reference",
    "Reference target",
    "Offset (mm)",
)


def render_csv(records, view_name, scan_options, profiles, out_path):
    """Render the scan results to a flat CSV at out_path.

    One row per element. Includes the owning profile's measurement
    reference + reference target + offset so a CSV reader can pivot
    on those without joining back to the profile config.
    """
    profile_meta = {}
    for p in profiles:
        profile_meta[p.key] = (
            p.measurement_reference, p.reference_target, p.offset_distance_mm)

    fh = open(out_path, "wb")
    try:
        fh.write(_UTF8_BOM)
        writer = csv.writer(fh)
        writer.writerow([_csv_cell(c) for c in CSV_HEADER])
        for r in records:
            mref, tgt, offset = profile_meta.get(
                r.get("profile_key"), ("", "", None))
            writer.writerow(_csv_row_for(r, mref, tgt, offset))
    finally:
        fh.close()
    return out_path


def _csv_row_for(r, mref, tgt, offset):
    binding_key = r.get("subcategory_key") or ""
    return [
        _csv_cell(r.get("profile_key")),
        _csv_cell(r.get("discipline_key")),
        _csv_cell(binding_key),
        _csv_cell(r.get("category_key")),
        _csv_cell(r.get("id")),
        _csv_cell(r.get("name")),
        _csv_length(r.get("length_mm")),
        _csv_cell(r.get("system_classification")),
        _csv_yes_no(r.get("audit_eligible")),
        _csv_yes_no(r.get("eligible")),
        _csv_yes_no(r.get("already_dimensioned")),
        _csv_cell(r.get("failing_rule")),
        _csv_cell(r.get("skip_reason")),
        _csv_placed(r.get("placed")),
        _csv_cell(r.get("place_error")),
        _csv_cell(mref),
        _csv_cell(tgt),
        _csv_length(offset),
    ]


def _csv_cell(value):
    if value is None:
        return ""
    if isinstance(value, unicode):
        return value.encode("utf-8")
    if isinstance(value, str):
        return value
    return str(value)


def _csv_length(value):
    if value is None:
        return ""
    try:
        return "{0:.0f}".format(float(value))
    except (TypeError, ValueError):
        return ""


def _csv_yes_no(value):
    if value is None:
        return ""
    return "yes" if value else "no"


def _csv_placed(value):
    if value is None:
        return ""
    return "placed" if value else "failed"
