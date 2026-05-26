"""Minimal .xlsx / .csv reader using only the Python standard library.

Reads the first worksheet of an .xlsx file (or a .csv) and returns rows as
dicts keyed by the header row. Handles shared strings, inline strings,
numbers, and empty cells. Skips fully-blank rows.
"""

import csv
import re
import zipfile
from xml.etree import ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_COL_RE = re.compile(r"^([A-Z]+)")


def _col_letter_to_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n - 1


def _cell_ref_to_col(ref):
    m = _COL_RE.match(ref)
    return _col_letter_to_index(m.group(1)) if m else None


def _read_shared_strings(zf):
    try:
        data = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(data)
    return ["".join(t.text or "" for t in si.iter(NS + "t")) for si in root.findall(NS + "si")]


def _first_sheet_path(zf):
    root = ET.fromstring(zf.read("xl/workbook.xml"))
    sheets = root.find(NS + "sheets")
    if sheets is None or len(sheets) == 0:
        raise ValueError("No sheets found in workbook")
    rid = sheets[0].get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    for rel in rels:
        if rel.get("Id") == rid:
            target = rel.get("Target")
            return "xl/" + target if not target.startswith("/") else target.lstrip("/")
    return "xl/worksheets/sheet1.xml"


def _cell_value(cell, shared_strings):
    ctype = cell.get("t", "n")
    if ctype == "s":
        v = cell.find(NS + "v")
        if v is None or v.text is None:
            return None
        idx = int(v.text)
        return shared_strings[idx] if 0 <= idx < len(shared_strings) else None
    if ctype == "inlineStr":
        return "".join(t.text or "" for t in cell.iter(NS + "t")) or None
    if ctype == "b":
        v = cell.find(NS + "v")
        return bool(int(v.text)) if v is not None and v.text else None
    v = cell.find(NS + "v")
    if v is None or v.text is None:
        return None
    text = v.text
    try:
        f = float(text)
        return int(f) if f.is_integer() else f
    except ValueError:
        return text


def normalise(s):
    """Lowercase, strip, collapse non-alphanumerics to underscores. For matching only."""
    if s is None:
        return None
    return re.sub(r"[^a-z0-9]+", "_", str(s).strip().lower()).strip("_")


def read_rows(xlsx_path):
    """Read the first worksheet. Returns (headers, rows).

    headers: list of original header strings (stripped) in column order; None for blank.
    rows: list of dicts keyed by original header text. Skips fully-blank rows.
    Use sheet_tools.excel_reader.normalise() on a header for case-insensitive matching.
    """
    with zipfile.ZipFile(xlsx_path) as zf:
        shared = _read_shared_strings(zf)
        sheet_path = _first_sheet_path(zf)
        sheet_xml = zf.read(sheet_path)

    root = ET.fromstring(sheet_xml)
    sheet_data = root.find(NS + "sheetData")
    if sheet_data is None:
        return [], []

    raw_rows = []
    for row_el in sheet_data.findall(NS + "row"):
        row = {}
        for cell in row_el.findall(NS + "c"):
            ref = cell.get("r", "")
            col = _cell_ref_to_col(ref)
            if col is None:
                continue
            val = _cell_value(cell, shared)
            if val is not None:
                row[col] = val
        raw_rows.append(row)

    if not raw_rows:
        return [], []

    header_row = raw_rows[0]
    max_col = max(header_row.keys()) if header_row else -1
    headers = []
    for i in range(max_col + 1):
        h = header_row.get(i)
        headers.append(str(h).strip() if h is not None else None)

    out = []
    for row in raw_rows[1:]:
        if not row:
            continue
        d = {}
        for col, val in row.items():
            if col < len(headers) and headers[col]:
                d[headers[col]] = val
        if d:
            out.append(d)
    return headers, out


def read_csv_rows(csv_path):
    """Read a CSV file. Returns (headers, rows) in the same shape as read_rows().

    Uses binary mode + manual BOM strip to stay compatible with IronPython 2.7,
    whose builtin open() does not accept encoding/newline keyword arguments.
    """
    with open(csv_path, "rb") as f:
        data = f.read()
    if data[:3] == b"\xef\xbb\xbf":
        data = data[3:]
    rows_raw = list(csv.reader(data.splitlines()))
    if not rows_raw:
        return [], []
    header_row = rows_raw[0]
    headers = [(h.strip() if h and h.strip() else None) for h in header_row]
    out = []
    for row in rows_raw[1:]:
        if not any((cell or "").strip() for cell in row):
            continue
        d = {}
        for i, val in enumerate(row):
            if i < len(headers) and headers[i] and val not in (None, ""):
                d[headers[i]] = val
        if d:
            out.append(d)
    return headers, out


def read_sheet(path):
    """Dispatch by extension: .csv -> read_csv_rows, anything else -> read_rows (xlsx)."""
    return read_csv_rows(path) if str(path).lower().endswith(".csv") else read_rows(path)
