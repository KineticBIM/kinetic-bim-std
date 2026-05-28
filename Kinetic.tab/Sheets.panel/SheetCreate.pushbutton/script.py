# -*- coding: utf-8 -*-
"""Batch-create Revit sheets from an .xlsx or .csv file.

Sheet-list layout: row 1 is the header row. Required columns (any of these
aliases will be matched, case-insensitive, punctuation-insensitive):
  - Number     : sheet_number, number, no, dwg_no, drawing_no
  - Name       : sheet_name, name, title, drawing_name
  - Titleblock : titleblock, title_block, tb, sheet_format
Optional columns: any other column whose header matches a sheet parameter
name will be set on the new sheet (best-effort, skipped if not found).
"""

from pyrevit import revit, DB, forms, script
from bim_core import errors
from sheet_tools.excel_reader import read_sheet, normalise

ALIASES = {
    "number": {"sheet_number", "number", "no", "num", "dwg_no", "drawing_no", "drawing_number"},
    "name": {"sheet_name", "name", "title", "drawing_name", "drawing_title"},
    "titleblock": {"titleblock", "title_block", "tb", "sheet_format", "title_block_type"},
}

doc = revit.doc
output = script.get_output()


def resolve_columns(headers):
    """Map normalised header → role ('number' | 'name' | 'titleblock' | None)."""
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


def collect_titleblocks():
    """Return (lookup_dict, available_names) for all titleblock types in the project.

    - lookup_dict: normalised key (Family: Type / Type / Family) -> FamilySymbol
    - available_names: sorted list of 'Family: Type' strings for user-facing display
    """
    lookup = {}
    available = set()
    coll = (DB.FilteredElementCollector(doc)
              .OfCategory(DB.BuiltInCategory.OST_TitleBlocks)
              .WhereElementIsElementType())
    for sym in coll:
        fam = sym.Family.Name if sym.Family else ""
        type_name = sym.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString() or ""
        full = "{}: {}".format(fam, type_name)
        available.add(full)
        for key in (full, type_name, fam):
            n = normalise(key)
            if n and n not in lookup:
                lookup[n] = sym
    return lookup, sorted(available)


def existing_sheet_numbers():
    return {s.SheetNumber for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet)}


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
        errors.show_error("sheet_create",
                          "Couldn't read the sheet list file.",
                          exc=exc)
        return

    if not rows:
        errors.show_warning(
            "sheet_create",
            "No data rows found in {0}.".format(sheet_path),
            exitscript=True)

    role_for = resolve_columns(headers)
    role_to_header = {role: h for h, role in role_for.items() if role}
    missing = [r for r in ("number", "name", "titleblock") if r not in role_to_header]
    if missing:
        errors.show_warning(
            "sheet_create",
            "Missing required column(s): {0}.\n\nFound headers: {1}".format(
                ", ".join(missing), ", ".join(h for h in headers if h)),
            exitscript=True)

    titleblocks, available_titleblocks = collect_titleblocks()
    if not titleblocks:
        errors.show_warning(
            "sheet_create",
            "No titleblock types loaded in this project.",
            exitscript=True)

    taken = existing_sheet_numbers()
    optional_headers = [h for h, role in role_for.items() if role is None]

    created, skipped = [], []

    with revit.Transaction("Batch create sheets"):
        for i, row in enumerate(rows, start=2):  # row 2 = first data row in Excel
            number = coerce_text(row.get(role_to_header["number"]))
            name = coerce_text(row.get(role_to_header["name"]))
            tb_raw = coerce_text(row.get(role_to_header["titleblock"]))

            if not number or not name:
                skipped.append((i, number or "?", "missing number or name"))
                continue
            if number in taken:
                skipped.append((i, number, "sheet number already exists"))
                continue

            sym = titleblocks.get(normalise(tb_raw)) if tb_raw else None
            if sym is None:
                skipped.append((i, number, "titleblock '{}' not found".format(tb_raw)))
                continue

            if not sym.IsActive:
                sym.Activate()
                doc.Regenerate()

            try:
                sheet = DB.ViewSheet.Create(doc, sym.Id)
                sheet.SheetNumber = number
                sheet.Name = name
            except Exception as exc:
                skipped.append((i, number, "Revit error: {}".format(exc)))
                continue

            for h in optional_headers:
                val = row.get(h)
                if val is None or val == "":
                    continue
                p = sheet.LookupParameter(h)
                if p is None or p.IsReadOnly:
                    continue
                try:
                    if p.StorageType == DB.StorageType.String:
                        p.Set(coerce_text(val))
                    elif p.StorageType == DB.StorageType.Integer:
                        p.Set(int(val))
                    elif p.StorageType == DB.StorageType.Double:
                        p.Set(float(val))
                except Exception:
                    pass  # parameter mismatch is non-fatal

            taken.add(number)
            created.append((number, name))

    output.print_md("## Batch sheet creation")
    output.print_md("**Created: {}**  ·  **Skipped: {}**".format(len(created), len(skipped)))
    if created:
        output.print_md("### Created")
        for num, nm in created:
            output.print_md("- `{}` — {}".format(num, nm))
    if skipped:
        output.print_md("### Skipped")
        for row_num, num, reason in skipped:
            output.print_md("- row {} (`{}`): {}".format(row_num, num, reason))

    if any("titleblock" in reason for _, _, reason in skipped):
        output.print_md("### Available titleblocks in this model")
        output.print_md("Copy one of these names into the **Titleblock** column. "
                        "Matching is case- and punctuation-insensitive; the family "
                        "name or type name alone also works.")
        for name in available_titleblocks:
            output.print_md("- `{}`".format(name))


if __name__ == "__main__":
    main()
