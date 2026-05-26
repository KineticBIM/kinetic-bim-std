# -*- coding: utf-8 -*-
"""Minimal stdlib-only XLSX writer.

Mirrors the deliberate choice the rest of this codebase makes
(`sheet_tools/excel_reader.py`) - we ship our own minimal reader/
writer using just `zipfile` + `xml.etree` so the platform works
under IronPython 2.7 without third-party dependencies.

Features kept:
  - Multiple worksheets with explicit names
  - Per-cell value types: str, int, float, None (empty)
  - Frozen header row on every sheet
  - Auto-detected column widths (rough, based on header length)

Features deliberately omitted (extend later if needed):
  - Per-cell colour formatting (status pills)
  - Auto-filter dropdowns (Excel renders the table fine without
    them; coordinators can add Filter via Ctrl+Shift+L)
  - Shared strings table (we inline every string, which produces
    slightly larger files but is correct for our scale)

Usage:

    wb = Workbook()
    s = wb.add_sheet("Summary")
    s.append_row(["A", "B", "C"])
    s.append_row(["1", 2, 3.5])
    wb.save("report.xlsx")
"""

from __future__ import print_function, division, absolute_import

import io
import os
import zipfile
from xml.sax.saxutils import escape


# ---------------------------------------------------------------------------
# Internals - XML boilerplate
# ---------------------------------------------------------------------------

_CONTENT_TYPES_HEAD = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
)
_CONTENT_TYPES_TAIL = '</Types>'

_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="xl/workbook.xml"/>'
    '</Relationships>'
)

_WORKBOOK_NS = (
    'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
)


def _col_letter(idx):
    """0-based column index -> Excel column letter (A, B, ..., Z, AA, AB, ...)."""
    letters = ""
    n = idx + 1
    while n > 0:
        n, r = divmod(n - 1, 26)
        letters = chr(65 + r) + letters
    return letters


# ---------------------------------------------------------------------------
# Public classes
# ---------------------------------------------------------------------------

class Sheet(object):
    def __init__(self, name):
        self.name = _safe_sheet_name(name)
        self.rows = []
        self.frozen_top_row = True

    def append_row(self, values):
        self.rows.append(list(values))

    def _column_count(self):
        return max((len(r) for r in self.rows), default=0)

    def _to_xml(self):
        ncols = self._column_count()
        parts = []
        parts.append('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>')
        parts.append('<worksheet ' + _WORKBOOK_NS + '>')

        # Sheet view: freeze top row.
        if self.frozen_top_row and self.rows:
            parts.append(
                '<sheetViews><sheetView workbookViewId="0" tabSelected="1">'
                '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
                '<selection pane="bottomLeft"/>'
                '</sheetView></sheetViews>')

        # Column widths.
        if ncols:
            cols_xml = ['<cols>']
            for i in range(ncols):
                # 22 chars is a reasonable default for our reports.
                cols_xml.append(
                    '<col min="{0}" max="{0}" width="{1}" customWidth="1"/>'.format(
                        i + 1, 22))
            cols_xml.append('</cols>')
            parts.append("".join(cols_xml))

        parts.append('<sheetData>')
        for ri, row in enumerate(self.rows):
            parts.append('<row r="{0}">'.format(ri + 1))
            for ci, val in enumerate(row):
                if val is None or val == "":
                    continue
                ref = _col_letter(ci) + str(ri + 1)
                if isinstance(val, bool):
                    # Excel doesn't have a great bool cell type; coerce to int.
                    parts.append(
                        '<c r="{0}" t="n"><v>{1}</v></c>'.format(
                            ref, 1 if val else 0))
                elif isinstance(val, (int, float)):
                    parts.append(
                        '<c r="{0}" t="n"><v>{1}</v></c>'.format(ref, val))
                else:
                    text = _to_text(val)
                    parts.append(
                        '<c r="{0}" t="inlineStr"><is><t xml:space="preserve">{1}</t></is></c>'.format(
                            ref, escape(text)))
            parts.append('</row>')
        parts.append('</sheetData>')
        parts.append('</worksheet>')
        return "".join(parts)


class Workbook(object):
    def __init__(self):
        self.sheets = []

    def add_sheet(self, name):
        s = Sheet(name)
        self.sheets.append(s)
        return s

    @property
    def sheetnames(self):
        return [s.name for s in self.sheets]

    def save(self, path):
        folder = os.path.dirname(os.path.abspath(path))
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)

        # Build the parts.
        content_types_xml = _CONTENT_TYPES_HEAD
        for i, sheet in enumerate(self.sheets, start=1):
            content_types_xml += (
                '<Override PartName="/xl/worksheets/sheet{0}.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.'
                'spreadsheetml.worksheet+xml"/>'.format(i))
        content_types_xml += _CONTENT_TYPES_TAIL

        # workbook.xml
        wb_parts = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<workbook ' + _WORKBOOK_NS + '><sheets>',
        ]
        for i, sheet in enumerate(self.sheets, start=1):
            wb_parts.append(
                '<sheet name="{0}" sheetId="{1}" r:id="rId{1}"/>'.format(
                    escape(sheet.name), i))
        wb_parts.append('</sheets></workbook>')
        workbook_xml = "".join(wb_parts)

        # workbook.xml.rels
        rels_parts = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<Relationships xmlns="http://schemas.openxmlformats.org/'
            'package/2006/relationships">',
        ]
        for i in range(1, len(self.sheets) + 1):
            rels_parts.append(
                '<Relationship Id="rId{0}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                'relationships/worksheet" Target="worksheets/sheet{0}.xml"/>'.format(i))
        rels_parts.append('</Relationships>')
        workbook_rels_xml = "".join(rels_parts)

        # Write zip.
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", content_types_xml)
            zf.writestr("_rels/.rels", _ROOT_RELS)
            zf.writestr("xl/workbook.xml", workbook_xml)
            zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
            for i, sheet in enumerate(self.sheets, start=1):
                zf.writestr(
                    "xl/worksheets/sheet{0}.xml".format(i),
                    sheet._to_xml())
        return os.path.abspath(path)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_INVALID_SHEET_CHARS = set('[]:*?/\\')


def _safe_sheet_name(name):
    safe = "".join("_" if c in _INVALID_SHEET_CHARS else c for c in (name or "Sheet"))
    safe = safe.strip("'").strip()
    if not safe:
        safe = "Sheet"
    # Excel sheet names are limited to 31 chars.
    return safe[:31]


def _to_text(val):
    """str() that handles None, ints, floats, and IronPython 2.7
    unicode strings transparently."""
    if val is None:
        return ""
    if isinstance(val, float):
        # Prevent scientific notation in the file for typical values.
        if val.is_integer():
            return str(int(val))
        return repr(val) if abs(val) < 1e-3 or abs(val) >= 1e16 else "{0}".format(val)
    try:
        return str(val)
    except UnicodeEncodeError:
        # IronPython 2.7 unicode handling.
        return val.encode("utf-8", "replace").decode("utf-8")
