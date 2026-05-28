# -*- coding: utf-8 -*-
"""QA Compliance Check

Run before every issuance to verify the model meets the project BEP. Loads
the project's QA config from <project>/.bim/qa_config.json (or by project
number, or falls back to default) and produces a pass/fail HTML report.

Shift-click: open the QA config file for editing.
"""

__title__   = "QA\nCheck"
__author__  = "Kinetic BIM"
__doc__     = "Run a project-specific QA compliance check."

import os
from pyrevit import revit, forms, script

from audit_engine import runner
from bim_core import errors, licensing


def main():
    licensing.require("qa_check")
    doc = revit.doc
    output = script.get_output()

    # Shift-click: open project QA config (creating from default if missing)
    if __shiftclick__:  # noqa: F821 - injected by pyRevit
        pn = doc.PathName
        if not pn:
            output.print_md("Save the project first.")
            return
        proj_cfg_dir = os.path.join(os.path.dirname(pn), ".bim")
        proj_cfg = os.path.join(proj_cfg_dir, "qa_config.json")
        if not os.path.isfile(proj_cfg):
            try:
                if not os.path.isdir(proj_cfg_dir):
                    os.makedirs(proj_cfg_dir)
                here = os.path.dirname(os.path.abspath(runner.__file__))
                default = os.path.join(here, "configs", "default.json")
                with open(default, "r") as src, open(proj_cfg, "w") as dst:
                    dst.write(src.read())
            except Exception as exc:
                errors.show_error("qa_check",
                                  "Couldn't create the project QA config.",
                                  exc=exc)
                return
            output.print_md(
                "Created project QA config from default at `{0}`.".format(proj_cfg))
        os.startfile(proj_cfg)
        return

    output.print_md("# Running QA Check...")
    try:
        with forms.ProgressBar(
                title="QA Check - scanning model...",
                cancellable=True) as pb:
            def _progress(done, total, current):
                if pb.cancelled:
                    return False
                pb.update_progress(done, total)
                if current:
                    pb.title = "QA Check - {0}...".format(current)
                return True
            result = runner.run_qa_check(
                doc, output=output, progress=_progress)
    except Exception as exc:
        errors.show_error("qa_check",
                          "Couldn't complete the QA check.",
                          exc=exc)
        return

    if result is None:
        output.print_md("---")
        output.print_md("(check cancelled)")
        return

    report_path, findings = result
    output.print_md("---")
    output.print_md(
        "Report written to: [{0}]({0})".format(report_path))


main()
