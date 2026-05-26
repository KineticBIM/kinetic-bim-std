# -*- coding: utf-8 -*-
"""Auto Tag - Annotation QA tool (v1).

Opens the Auto Tag dialog. The dialog scans the active view (or the
whole model) for linear MEP elements - cable trays, conduits, ducts,
pipes - over a minimum length, lists what is eligible vs already
tagged, and optionally places tags at curve midpoints in the active
view.

Shift-click: open the project's Auto Tag config (creates from the
extension default if missing).
"""

import os

from pyrevit import revit, forms

from annotation_qa.ui import AnnotationQAWindow
from bim_core import log as log_module


__title__  = "Auto\nTag"
__author__ = "BIM Manager"
__doc__    = "Find and tag untagged linear MEP runs in the active view or across the whole model."


def _open_project_config(doc):
    pn = doc.PathName
    if not pn:
        forms.alert("Save the project first.", exitscript=True)
    proj_cfg_dir = os.path.join(os.path.dirname(pn), ".bim")
    proj_cfg = os.path.join(proj_cfg_dir, "auto_tag.json")
    if not os.path.isfile(proj_cfg):
        if not os.path.isdir(proj_cfg_dir):
            os.makedirs(proj_cfg_dir)
        here = os.path.dirname(os.path.abspath(__file__))
        default = os.path.normpath(os.path.join(
            here, "..", "..", "..", "lib", "annotation_qa",
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

    log = log_module.get_logger(doc, tool_name="auto_tag")
    log.info("Tool launched. view=%s", view.Name)

    win = AnnotationQAWindow(doc, view)
    win.ShowDialog()


main()
