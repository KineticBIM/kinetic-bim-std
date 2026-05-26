# -*- coding: utf-8 -*-
"""HTML + CSV report rendering + headline aggregates.

v5 reports are profile-driven: one HTML section per TaggingProfile (in
the order the profiles were supplied to scan), with that profile's
own active-filters line and its own exclusions-by-rule breakdown.
There is no single global "active filters" header any more, because
each profile may run a different pipeline.

CSV export emits one flat row per element with the profile, discipline,
subcategory, and outcome columns; Excel opens it natively. The CSV
includes a UTF-8 BOM so Excel auto-detects the encoding (otherwise it
mangles non-ASCII element names on default-Windows installs).

Aggregates (summary_counts, breakdown_by_rule) operate on records and
don't care about profiles - same as v4.
"""

import csv
import os
import datetime

from bim_core.core import discipline_config


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def report_path(doc, ext="html"):
    """Build a timestamped report path under <project>/.bim/reports/.

    ext switches between formats - "html" for the rendered report,
    "csv" for the per-element CSV / Excel export. Falls back to the
    user's home folder when the project is unsaved.
    """
    pn = doc.PathName
    base = os.path.dirname(pn) if pn else os.path.expanduser("~")
    folder = os.path.join(base, ".bim", "reports")
    if not os.path.isdir(folder):
        os.makedirs(folder)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    return os.path.join(folder, "auto_tag_{0}.{1}".format(stamp, ext))


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------

def summary_counts(records):
    """Headline counts. Operates on any record subset."""
    return {
        "total":              len(records),
        "audit_eligible":     sum(1 for r in records if r["audit_eligible"]),
        "eligible":           sum(1 for r in records if r["eligible"]),
        "eligible_elsewhere": sum(
            1 for r in records
            if r["audit_eligible"] and not r.get("in_active_view", True)),
        "already":            sum(1 for r in records if r["already_tagged"]),
        "placed":             sum(1 for r in records if r.get("placed")),
        "failed":             sum(1 for r in records if r.get("placed") is False),
    }


def breakdown_by_rule(records):
    """Map of failing_rule -> count. Skips records that passed the rules."""
    out = {}
    for r in records:
        if r.get("audit_eligible"):
            continue
        rule = r.get("failing_rule") or "(unknown)"
        out[rule] = out.get(rule, 0) + 1
    return out


def group_by_profile(records, profiles):
    """Bucket records by profile_key in the supplied profile order.

    Records whose profile_key isn't in `profiles` (e.g. a record from
    an earlier scan that referenced a since-removed profile) end up in
    a single trailing "(Unattributed)" bucket so they still surface.
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


def group_by_discipline(records):
    """Legacy bucketing (for callers that still want discipline ->
    subcategory grouping without supplying the profile list).

    Order preserved: disciplines follow DISCIPLINE_ORDER, subcategories
    follow the order declared in the registry. Records that lack
    attribution end up in a trailing "(Unattributed)" bucket.
    """
    buckets = {}
    for r in records:
        key = (r.get("discipline_key"), r.get("subcategory_key"))
        buckets.setdefault(key, []).append(r)

    ordered = []
    for disc_key in discipline_config.DISCIPLINE_ORDER:
        disc = discipline_config.DISCIPLINE_REGISTRY[disc_key]
        for binding in disc.subcategories:
            key = (disc_key, binding.key)
            if key in buckets:
                ordered.append((disc, binding, buckets.pop(key)))

    if buckets:
        leftover = []
        for _, recs in buckets.items():
            leftover.extend(recs)
        ordered.append((None, None, leftover))
    return ordered


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def render_html(records, view_name, scan_options, profiles, out_path):
    """Render the scan results to an HTML report at out_path.

    scan_options carries top-level scope state (whole_model). profiles
    is the list of TaggingProfile that drove the scan; the report
    renders one section per profile with that profile's own active-
    filters header and exclusions table.
    """
    counts = summary_counts(records)
    whole_model = bool((scan_options or {}).get("whole_model"))

    scope = "Whole model" if whole_model else "Active view"
    title = _scan_title(profiles)

    cards = [
        '<div class="card"><b>{0}</b>Total scanned</div>'.format(counts["total"]),
    ]
    if whole_model:
        cards.append(
            '<div class="card"><b>{0}</b>Audit-eligible</div>'.format(
                counts["audit_eligible"]))
        cards.append(
            '<div class="card"><b>{0}</b>Eligible (this view)</div>'.format(
                counts["eligible"]))
        cards.append(
            '<div class="card"><b>{0}</b>Eligible elsewhere</div>'.format(
                counts["eligible_elsewhere"]))
    else:
        cards.append(
            '<div class="card"><b>{0}</b>Eligible</div>'.format(counts["eligible"]))
    cards.append(
        '<div class="card"><b>{0}</b>Already tagged</div>'.format(counts["already"]))
    cards.append(
        '<div class="card"><b>{0}</b>Placed</div>'.format(counts["placed"]))
    cards.append(
        '<div class="card"><b>{0}</b>Failed</div>'.format(counts["failed"]))

    sections_html = _render_profile_sections(records, profiles)

    html = _HTML_TEMPLATE.format(
        title=_escape("Auto Tag - {0}".format(title)),
        view=_escape(view_name),
        scope=_escape(scope),
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


# ---------------------------------------------------------------------------
# Section rendering
# ---------------------------------------------------------------------------

def _scan_title(profiles):
    """Compose a page title from the profile set: 'Mechanical + Electrical'
    when several disciplines are in play, just the discipline label when
    one. Empty when profiles is empty (e.g. report rendered before any
    scan)."""
    if not profiles:
        return "(no profiles)"
    seen = []
    for p in profiles:
        try:
            label = discipline_config.get(p.discipline_key).label
        except KeyError:
            label = p.discipline_key or "Other"
        if label not in seen:
            seen.append(label)
    return " + ".join(seen)


def _render_profile_sections(records, profiles):
    """One <section> per profile: profile label, active filters,
    counts, exclusions table, per-element rows. Profiles with zero
    records still render so the reader sees they ran but found nothing.
    """
    grouped = group_by_profile(records, profiles)
    if not grouped and not profiles:
        return "<p class='meta'>(no records)</p>"

    parts = []
    for profile, recs in grouped:
        parts.append(_render_one_profile(profile, recs))

    # Profiles with zero records aren't in `grouped` (group_by_profile
    # keys on records). Emit them so the user can confirm the profile
    # ran but matched nothing.
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
        already=counts["already"],
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
    elif r.get("audit_eligible") and not r.get("in_active_view", True):
        status = "Eligible elsewhere - not in active view"
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
        "yes" if r["already_tagged"] else "no",
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
    <span class='pill'>{already} already tagged</span>
    <span class='pill'>{placed} placed</span>
    <span class='pill'>{failed} failed</span>
  </div>
  {rule_table}
  <table>
    <thead><tr>
      <th>Id</th><th>Element</th><th>Length (mm)</th>
      <th>System</th><th>Failing rule</th>
      <th>Tagged before</th><th>Outcome</th>
    </tr></thead>
    <tbody>
{rows}
    </tbody>
  </table>
</section>"""


_HTML_TEMPLATE = u"""<!doctype html>
<html><head><meta charset="utf-8"><title>Auto Tag Report</title>
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
<div class="meta">View: <b>{view}</b> &middot; Scope: <b>{scope}</b> &middot; Generated {ts}</div>
<div class="cards">
  {cards}
</div>
<h2>Results by profile</h2>
{sections}
</body></html>"""


# ---------------------------------------------------------------------------
# CSV / Excel export
# ---------------------------------------------------------------------------

# UTF-8 BOM so Excel auto-detects the encoding on Windows. Without it,
# Excel reads UTF-8 bytes as Windows-1252 and mangles non-ASCII names.
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
    "In active view",
    "Eligible",
    "Already tagged",
    "Failing rule",
    "Skip reason",
    "Placed",
    "Place error",
)


def render_csv(records, view_name, scan_options, profiles, out_path):
    """Render the scan results to a flat CSV at out_path.

    One row per element. Column order is CSV_HEADER. The first row is
    the header; data starts on row 2 so Excel's "Format as table" hits
    the right shape on first try.

    Profiles that ran but matched zero elements don't add rows - the
    HTML report shows them; the CSV is for per-element analysis.

    view_name and scan_options are intentionally unused in the rows
    themselves; they're recoverable from the timestamp / paired HTML
    report. Keeping the function signature parallel to render_html
    means the UI can call them through the same plumbing.
    """
    fh = open(out_path, "wb")
    try:
        fh.write(_UTF8_BOM)
        writer = csv.writer(fh)
        writer.writerow([_csv_cell(c) for c in CSV_HEADER])
        for r in records:
            writer.writerow(_csv_row_for(r))
    finally:
        fh.close()
    return out_path


def _csv_row_for(r):
    """Translate one record dict into the CSV column tuple."""
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
        _csv_yes_no(r.get("in_active_view"), default_for_none=True),
        _csv_yes_no(r.get("eligible")),
        _csv_yes_no(r.get("already_tagged")),
        _csv_cell(r.get("failing_rule")),
        _csv_cell(r.get("skip_reason")),
        _csv_placed(r.get("placed")),
        _csv_cell(r.get("place_error")),
    ]


def _csv_cell(value):
    """Coerce a value into the bytes the stdlib csv module expects.

    Under IronPython 2.7 / Python 2 the csv writer expects str (bytes),
    not unicode. Encode to UTF-8 so the BOM-prefixed file stays valid.
    """
    if value is None:
        return ""
    if isinstance(value, unicode):
        return value.encode("utf-8")
    if isinstance(value, str):
        return value
    return str(value)


def _csv_length(value):
    """Format a length-in-mm cell as an integer string for Excel.

    Excel doesn't need 'mm' in the value when the column header carries
    the unit; emitting a plain number lets users sort/filter/sum the
    column without text coercion.
    """
    if value is None:
        return ""
    try:
        return "{0:.0f}".format(float(value))
    except (TypeError, ValueError):
        return ""


def _csv_yes_no(value, default_for_none=False):
    """Translate a tri-state bool/None to 'yes' / 'no' / blank.

    default_for_none lets in_active_view fall back to 'yes' for active-
    view scope records (where the key is omitted by qa_engine).
    """
    if value is None:
        return "yes" if default_for_none else ""
    return "yes" if value else "no"


def _csv_placed(value):
    """Placement state has three meanings: True (placed), False (tried
    and failed), None (not attempted yet). Surface them distinctly so
    the user can filter rows that need re-running."""
    if value is None:
        return ""
    return "placed" if value else "failed"
