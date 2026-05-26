# -*- coding: utf-8 -*-
"""Model Health Audit

Run weekly to monitor model performance and hygiene. Scans the active model
for warnings, view/template issues, CAD imports, group bloat, link state,
and unused families. Writes an HTML report next to the project file.

Shift-click: open the report folder instead of running.
"""

__title__   = "Health\nAudit"
__author__  = "BIM Manager"
__doc__     = "Run a model health audit and produce an HTML report."

import os
from pyrevit import revit, script

from audit_engine import runner


def main():
    doc = revit.doc
    output = script.get_output()

    # Shift-click: open reports folder
    if __shiftclick__:  # noqa: F821 - injected by pyRevit
        pn = doc.PathName
        base = os.path.dirname(pn) if pn else os.path.expanduser("~")
        folder = os.path.join(base, ".bim", "reports")
        if os.path.isdir(folder):
            os.startfile(folder)
        else:
            output.print_md("No reports folder yet at `{0}`.".format(folder))
        return

    output.print_md("# Running Health Audit...")
    report_path, findings = runner.run_health_audit(doc, output=output)
    output.print_md("---")
    output.print_md(
        "Report written to: [{0}]({0})".format(report_path))


main()
