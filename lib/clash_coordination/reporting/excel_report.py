# -*- coding: utf-8 -*-
"""Excel clash detail report using the stdlib-only xlsx writer.

Produces a workbook with:

    Summary        High-level counts.
    All Clashes    One row per clash with every reportable field.
    <per-test>     Up to 30 per-test sheets, rest collapse to "Other".

Pure-stdlib - no openpyxl dependency. Works under IronPython 2.7
and CPython 3.

The output is a valid .xlsx file that opens cleanly in Excel,
Google Sheets, LibreOffice, etc. Coordinators can add Filter
(Ctrl+Shift+L) themselves on the All Clashes sheet - skipping
auto-filter in the writer is a deliberate complexity cut.
"""

from __future__ import print_function, division, absolute_import

import os

from clash_coordination.data import models
from clash_coordination.reporting.xlsx_writer import Workbook


CLASH_COLUMNS = [
    "Clash Test",
    "Clash ID",
    "Clash Name",
    "Status",
    "Assigned Group",
    "Distance (mm)",
    "Grid Location",
    "Location X (m)",
    "Location Y (m)",
    "Location Z (m)",
    "Disciplines",
    "Item 1 - Path",
    "Item 1 - Source File",
    "Item 1 - Layer",
    "Item 1 - Category",
    "Item 1 - Element ID",
    "Item 1 - Discipline",
    "Item 2 - Path",
    "Item 2 - Source File",
    "Item 2 - Layer",
    "Item 2 - Category",
    "Item 2 - Element ID",
    "Item 2 - Discipline",
    "Found Date",
    "Approved Date",
    "Approved By",
    "Comments",
    "Screenshot",
]


def _clash_row(test_name, c):
    loc = c.location_xyz_m or (None, None, None)
    distance_mm = None
    if c.distance_m is not None:
        distance_mm = round(c.distance_m * 1000.0, 2)
    return [
        test_name,
        c.clash_id,
        c.name,
        c.status,
        c.assigned_group or "",
        distance_mm,
        c.grid_location,
        loc[0], loc[1], loc[2],
        c.discipline_pair,
        c.item1.item_path, c.item1.source_file, c.item1.layer,
        c.item1.category or "", c.item1.element_id or "",
        c.item1.discipline or "",
        c.item2.item_path, c.item2.source_file, c.item2.layer,
        c.item2.category or "", c.item2.element_id or "",
        c.item2.discipline or "",
        c.found_date or "",
        c.approved_date or "",
        c.approved_by or "",
        " | ".join(c.comments) if c.comments else "",
        c.screenshot_path or "",
    ]


def _write_clash_sheet(wb, title, rows):
    ws = wb.add_sheet(title)
    ws.append_row(CLASH_COLUMNS)
    for row in rows:
        ws.append_row(row)
    return ws


def _write_summary_sheet(wb, run):
    ws = wb.add_sheet("Summary")
    ws.append_row(["Clash Coordination Report"])
    ws.append_row([run.project_name or "(no project name)"])
    ws.append_row(["Project number", run.project_number or ""])
    ws.append_row(["Federated model", run.nwf_path])
    ws.append_row(["Run date", run.run_date])
    ws.append_row(["Run timestamp", run.run_timestamp])
    ws.append_row([])

    ws.append_row(["Totals"])
    ws.append_row(["Total clashes", run.total])
    if run.delta_new is not None or run.delta_resolved is not None:
        ws.append_row([
            "New since previous run",
            run.delta_new if run.delta_new is not None else ""])
        ws.append_row([
            "Resolved since previous run",
            run.delta_resolved if run.delta_resolved is not None else ""])
        ws.append_row(["Previous snapshot date", run.previous_snapshot_date or ""])
    ws.append_row([])

    ws.append_row(["By status"])
    for status in sorted(run.total_by_status.keys()):
        ws.append_row([status, run.total_by_status[status]])
    ws.append_row([])

    ws.append_row(["By test", "Count"])
    for test in run.tests:
        ws.append_row([test.name, test.count])
    ws.append_row([])

    ws.append_row(["By discipline pair", "Count"])
    pair_items = sorted(
        run.total_by_discipline_pair.items(),
        key=lambda kv: kv[1], reverse=True,
    )
    for pair, count in pair_items:
        ws.append_row([pair, count])
    return ws


def write_excel_report(run, out_path):
    """Write the Excel report for `run` to `out_path`. Returns the
    absolute path written.
    """
    folder = os.path.dirname(os.path.abspath(out_path))
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)

    wb = Workbook()
    _write_summary_sheet(wb, run)

    all_rows = []
    for test in run.tests:
        for c in test.clashes:
            all_rows.append(_clash_row(test.name, c))
    _write_clash_sheet(wb, "All Clashes", all_rows)

    # Per-test sheets, capped at 30 to keep the workbook tidy.
    overflow_rows = []
    sheets_created = 0
    sheet_cap = 30
    for test in run.tests:
        if not test.clashes:
            continue
        if sheets_created >= sheet_cap:
            for c in test.clashes:
                overflow_rows.append(_clash_row(test.name, c))
            continue
        rows = [_clash_row(test.name, c) for c in test.clashes]
        _write_clash_sheet(wb, test.name, rows)
        sheets_created += 1
    if overflow_rows:
        _write_clash_sheet(wb, "Other Tests", overflow_rows)

    return wb.save(out_path)
