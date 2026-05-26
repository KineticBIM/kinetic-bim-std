# -*- coding: utf-8 -*-
"""Auto Dimension - rule-based MEP dimensioning tool (v1).

Opens the Auto Dimension dialog. The dialog scans the active view
for linear MEP elements (cable trays, conduits, ducts, pipes) per
the user's per-subcategory profile configuration and places aligned
dimensions to the nearest perpendicular grid line.

Shift-click: open the project's Auto Dimension config (creates from
the extension default if missing).
"""

import os

from pyrevit import revit, forms

from bim_core import log as log_module
from dimension_qa.ui import DimensionWindow


__title__  = "Auto\nDimension"
__author__ = "Kinetic BIM"
__doc__    = "Rule-based dimensioning for linear MEP runs to the nearest grid."


def _open_project_config(doc):
    pn = doc.PathName
    if not pn:
        forms.alert("Save the project first.", exitscript=True)
    proj_cfg_dir = os.path.join(os.path.dirname(pn), ".bim")
    proj_cfg = os.path.join(proj_cfg_dir, "auto_dimension.json")
    if not os.path.isfile(proj_cfg):
        if not os.path.isdir(proj_cfg_dir):
            os.makedirs(proj_cfg_dir)
        here = os.path.dirname(os.path.abspath(__file__))
        default = os.path.normpath(os.path.join(
            here, "..", "..", "..", "lib", "dimension_qa",
            "configs", "default.json"))
        src = open(default, "rb")
        try:
            data = src.read()
        finally:
            src.close()
        dst = open(proj_cfg, "wb")
        try:
            dst.write(data)
        finally:
            dst.close()
    os.startfile(proj_cfg)


def main():
    doc = revit.doc
    view = doc.ActiveView
    if view is None:
        forms.alert("No active view.", exitscript=True)

    if __shiftclick__:  # noqa: F821 - injected by pyRevit
        _open_project_config(doc)
        return

    log = log_module.get_logger(doc, tool_name="auto_dimension")
    log.info("Tool launched. view=%s", view.Name)

    win = DimensionWindow(doc, view)
    win.ShowDialog()


main()
