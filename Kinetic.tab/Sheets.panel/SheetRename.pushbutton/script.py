# -*- coding: utf-8 -*-
"""Batch-rename Revit sheets from an .xlsx or .csv file.

Sheet-list layout: row 1 is the header row. Required columns (any of these
aliases will be matched, case-insensitive, punctuation-insensitive):
  - Number : sheet_number, number, no, dwg_no, drawing_no
  - Name   : sheet_name, name, new_name, title, drawing_name
The Number column identifies the existing sheet; the Name column is the
new name to apply. Rows whose Number does not match an existing sheet
are skipped.
"""

from pyrevit import revit, DB, forms, script
from bim_core import errors, licensing
from sheet_tools.excel_reader import read_sheet, normalise

ALIASES = {
    "number": {"sheet_number", "number", "no", "num", "dwg_no", "drawing_no", "drawing_number"},
    "name": {"sheet_name", "name", "new_name", "title", "drawing_name", "drawing_title"},
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
    licensing.require("sheet_rename")
    sheet_path = forms.pick_file(
        files_filter="Sheet list (*.xlsx, *.csv)|*.xlsx;*.csv",
        title="Select sheet list",
    )
    if not sheet_path:
        return

    try:
        headers, rows = read_sheet(sheet_path)
    except Exception as exc:
        errors.show_error("sheet_rename",
                          "Couldn't read the sheet list file.",
                          exc=exc)
        return

    if not rows:
        errors.show_warning(
            "sheet_rename",
            "No data rows found in {0}.".format(sheet_path),
            exitscript=True)

    role_for = resolve_columns(headers)
    role_to_header = {role: h for h, role in role_for.items() if role}
    missing = [r for r in ("number", "name") if r not in role_to_header]
    if missing:
        errors.show_warning(
            "sheet_rename",
            "Missing required column(s): {0}.\n\nFound headers: {1}".format(
                ", ".join(missing), ", ".join(h for h in headers if h)),
            exitscript=True)

    lookup = sheets_by_number()
    renamed, skipped = [], []

    with revit.Transaction("Batch rename sheets"):
        for i, row in enumerate(rows, start=2):
            number = coerce_text(row.get(role_to_header["number"]))
            new_name = coerce_text(row.get(role_to_header["name"]))

            if not number:
                skipped.append((i, "?", "missing number"))
                continue
            if not new_name:
                skipped.append((i, number, "missing new name"))
                continue

            sheet = lookup.get(number)
            if sheet is None:
                skipped.append((i, number, "no sheet with this number"))
                continue

            old_name = sheet.Name
            if old_name == new_name:
                skipped.append((i, number, "name unchanged"))
                continue

            try:
                sheet.Name = new_name
            except Exception as exc:
                skipped.append((i, number, "Revit error: {}".format(exc)))
                continue

            renamed.append((number, old_name, new_name))

    output.print_md("## Batch sheet rename")
    output.print_md("**Renamed: {}**  -  **Skipped: {}**".format(len(renamed), len(skipped)))
    if renamed:
        output.print_md("### Renamed")
        for num, old, new in renamed:
            output.print_md("- `{}`: {} -> {}".format(num, old, new))
    if skipped:
        output.print_md("### Skipped")
        for row_num, num, reason in skipped:
            output.print_md("- row {} (`{}`): {}".format(row_num, num, reason))


if __name__ == "__main__":
    main()
