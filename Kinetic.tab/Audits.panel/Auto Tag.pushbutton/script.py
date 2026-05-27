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
from bim_core import errors, log as log_module


__title__  = "Auto\nTag"
__author__ = "Kinetic BIM"
__doc__    = "Find and tag untagged linear MEP runs in the active view or across the whole model."


def _open_project_config(doc):
    pn = doc.PathName
    if not pn:
        forms.alert("Save the project first.", exitscript=True)
    proj_cfg_dir = os.path.join(os.path.dirname(pn), ".bim")
    proj_cfg = os.path.join(proj_cfg_dir, "auto_tag.json")
    if not os.path.isfile(proj_cfg):
        # Seed the project config from the extension default. Any
        # failure here (corrupt install, locked-down filesystem,
        # read-only project folder) becomes a friendly dialog instead
        # of a pyRevit traceback.
        try:
            if not os.path.isdir(proj_cfg_dir):
                os.makedirs(proj_cfg_dir)
            here = os.path.dirname(os.path.abspath(__file__))
            default = os.path.normpath(os.path.join(
                here, "..", "..", "..", "lib", "annotation_qa",
                "configs", "default.json"))
            with open(default, "rb") as src:
                data = src.read()
            with open(proj_cfg, "wb") as dst:
                dst.write(data)
        except Exception as exc:
            errors.show_error(
                "auto_tag",
                "Couldn't create the project Auto Tag config.",
                exc=exc,
                exitscript=True)
    try:
        os.startfile(proj_cfg)
    except Exception as exc:
        errors.show_error(
            "auto_tag",
            "Couldn't open the project config. The file is at:\n"
            "{0}".format(proj_cfg),
            exc=exc)


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
