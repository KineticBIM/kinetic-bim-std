# -*- coding: utf-8 -*-
"""Clash Reporting - weekly Navisworks coordination automation.

Opens the coordination window. The user picks a coordination project
(or an NWF + output folder ad hoc), ticks the weekly-run options,
hits Run. The orchestrator drives Navisworks via COM to refresh the
federated model, run the selected clash tests, export viewpoints +
screenshots, and renders an Excel detail report + PDF management
summary into a dated coordination folder.

Shift-click: open the most recent coordination output folder instead
of running.
"""

__title__   = "Clash\nReporting"
__author__  = "Kinetic BIM"
__doc__     = "Run the weekly Navisworks clash coordination workflow."

import os
from pyrevit import revit, script

from clash_coordination import ui, project_config


def main():
    doc = revit.doc
    output = script.get_output()

    if __shiftclick__:  # noqa: F821 - injected by pyRevit
        last = project_config.last_output_folder(doc)
        if last and os.path.isdir(last):
            os.startfile(last)
        else:
            output.print_md(
                "No coordination output folder recorded yet. "
                "Run a coordination pack first.")
        return

    ui.show_window(doc, output=output)


main()
