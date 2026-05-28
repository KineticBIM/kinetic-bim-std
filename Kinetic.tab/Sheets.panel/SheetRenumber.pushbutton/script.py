# -*- coding: utf-8 -*-
"""Batch-renumber Revit sheets from an .xlsx or .csv file.

Sheet-list layout: row 1 is the header row. Required columns (any of these
aliases will be matched, case-insensitive, punctuation-insensitive):
  - Number     : sheet_number, number, no, current_number, old_number
  - New Number : new_number, new_no, target_number, renumber_to

The Number column identifies the existing sheet; New Number is the target.
Two-pass renumber: pass 1 assigns unique temporary numbers, pass 2 sets
the final values. This handles swaps (A<->B) and chains (A->B->C) without
collision errors. Both passes run in a single transaction so an undo
restores the original numbers.
"""

from pyrevit import revit, DB, forms, script
from bim_core import errors
from sheet_tools.excel_reader import read_sheet, normalise

ALIASES = {
    "number": {"sheet_number", "number", "no", "num", "current_number",
               "old_number", "dwg_no", "drawing_no", "drawing_number"},
    "new_number": {"new_number", "new_no", "new_num", "target_number",
                   "renumber_to", "new_dwg_no", "new_drawing_number"},
}

doc = revit.doc
output = script.get_output()


def resolve_columns(headers):
    role_for = {}
    for h in headers:
        if not h:
            continue
        n = normalise(h)
        for role, names in ALIASES.items():
            if n in names:
                role_for[h] = role
                break
        else:
            role_for[h] = None
    return role_for


def sheets_by_number():
    return {s.SheetNumber: s for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet)}


def coerce_text(value):
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def main():
    sheet_path = forms.pick_file(
        files_filter="Sheet list (*.xlsx, *.csv)|*.xlsx;*.csv",
        title="Select sheet list",
    )
    if not sheet_path:
        return

    try:
        headers, rows = read_sheet(sheet_path)
    except Exception as exc:
        errors.show_error("sheet_renumber",
                          "Couldn't read the sheet list file.",
                          exc=exc)
        return

    if not rows:
        errors.show_warning(
            "sheet_renumber",
            "No data rows found in {0}.".format(sheet_path),
            exitscript=True)

    role_for = resolve_columns(headers)
    role_to_header = {role: h for h, role in role_for.items() if role}
    missing = [r for r in ("number", "new_number") if r not in role_to_header]
    if missing:
        errors.show_warning(
            "sheet_renumber",
            "Missing required column(s): {0}.\n\nFound headers: {1}".format(
                ", ".join(missing), ", ".join(h for h in headers if h)),
            exitscript=True)

    lookup = sheets_by_number()

    # Pre-flight: validate rows and detect duplicate targets within the spreadsheet.
    # plan: list of (row_idx, sheet, current_number, new_number)
    plan = []
    skipped = []
    seen_targets = {}  # new_number -> row_idx of first occurrence

    for i, row in enumerate(rows, start=2):
        current = coerce_text(row.get(role_to_header["number"]))
        new = coerce_text(row.get(role_to_header["new_number"]))

        if not current:
            skipped.append((i, "?", "missing current number"))
            continue
        if not new:
            skipped.append((i, current, "missing new number"))
            continue

        sheet = lookup.get(current)
        if sheet is None:
            skipped.append((i, current, "no sheet with this number"))
            continue

        if current == new:
            skipped.append((i, current, "number unchanged"))
            continue

        if new in seen_targets:
            skipped.append((i, current,
                "new number '{}' duplicates row {}".format(new, seen_targets[new])))
            continue
        seen_targets[new] = i

        plan.append((i, sheet, current, new))

    # Drop plan entries whose target collides with a sheet not in the plan.
    being_renumbered = {p[2] for p in plan}
    filtered_plan = []
    for entry in plan:
        i, sheet, current, new = entry
        if new in lookup and new not in being_renumbered:
            skipped.append((i, current,
                "new number '{}' is taken by a sheet not being renumbered".format(new)))
        else:
            filtered_plan.append(entry)
    plan = filtered_plan

    renumbered = []

    with revit.Transaction("Batch renumber sheets"):
        # Pass 1: assign unique temp numbers to every sheet in the plan.
        for idx, (_, sheet, _, _) in enumerate(plan):
            try:
                sheet.SheetNumber = "__TMP_RN_{}__".format(idx)
            except Exception as exc:
                skipped.append((plan[idx][0], plan[idx][2],
                    "pass-1 temp set failed: {}".format(exc)))

        # Pass 2: set final new numbers.
        for i, sheet, current, new in plan:
            try:
                sheet.SheetNumber = new
            except Exception as exc:
                skipped.append((i, current, "pass-2 set failed: {}".format(exc)))
                continue
            renumbered.append((current, new, sheet.Name))

    output.print_md("## Batch sheet renumber")
    output.print_md("**Renumbered: {}**  -  **Skipped: {}**".format(len(renumbered), len(skipped)))
    if renumbered:
        output.print_md("### Renumbered")
        for old, new, name in renumbered:
            output.print_md("- `{}` -> `{}`  ({})".format(old, new, name))
    if skipped:
        output.print_md("### Skipped")
        for row_num, num, reason in skipped:
            output.print_md("- row {} (`{}`): {}".format(row_num, num, reason))


if __name__ == "__main__":
    main()
