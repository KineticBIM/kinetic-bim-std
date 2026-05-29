# -*- coding: utf-8 -*-
"""About Kinetic BIM Standard.

Surfaces version, tool list, license status, support contact, and the
local logs folder path (so support can ask users to attach logs when
reporting issues without anyone having to remember where they live).

Shift-click: open the logs folder directly in Explorer.
"""

__title__   = "About"
__author__  = "Kinetic BIM"
__doc__     = "Version, license status, support contact, log location."

import os

from pyrevit import forms

from bim_core import licensing
from bim_core.version import __version__


SUPPORT_EMAIL = "support@kineticbim.com"
COPYRIGHT     = "(c) 2026 Kinetic Build (NZ)"

INTRO = [
    "Kinetic BIM Standard is a suite of Revit tools that automate",
    "your documentation, QA, and coordination workflow:",
]

# (name, one-line description) for the About dialog. Descriptions are
# condensed from each tool's bundle.yaml tooltip.
TOOLS = [
    ("Auto Tag",
     "Tag untagged MEP runs (tray, conduit, duct, pipe)."),
    ("Auto Dimension",
     "Dimension linear MEP runs to the nearest grid."),
    ("Sheet Automation",
     "Bulk create, rename, renumber sheets from Excel/CSV."),
    ("Health Audit",
     "Weekly model performance and hygiene check."),
    ("QA Check",
     "Compliance check against the project BEP."),
    ("Clash Reporting",
     "Navisworks clash workflow into a dated report pack."),
]


def _logs_folder():
    """Mirror bim_core.log._resolve_log_dir's path convention so
    the dialog shows the same folder the loggers actually write to.
    Kept in sync manually rather than imported because log.py's
    resolver is private and has a side effect (creating the folder)
    we don't want from a passive About dialog."""
    base = (os.environ.get("LOCALAPPDATA")
            or os.environ.get("APPDATA")
            or os.path.expanduser("~"))
    return os.path.normpath(os.path.join(base, "KineticBIM", "logs"))


def _license_status_line():
    """Read the licensing hook for a one-liner. M1's check() is a
    no-op (always True), so this always reads 'Licensed' today; M2
    will make this meaningful (Standard / Pro / expired / not
    activated etc.)."""
    try:
        ok = licensing.check("about")
    except licensing.LicenseError as exc:
        return "License check error: {0}".format(exc)
    return "Licensed (Standard)" if ok else "Not licensed"


def main():
    logs = _logs_folder()

    if __shiftclick__:  # noqa: F821 - injected by pyRevit
        if os.path.isdir(logs):
            os.startfile(logs)
        else:
            forms.alert(
                "No logs folder yet at:\n{0}\n\n"
                "Run any Kinetic BIM tool first to create it.".format(logs))
        return

    tool_lines = []
    for name, desc in TOOLS:
        tool_lines.append("  " + name)
        tool_lines.append("      " + desc)

    body = "\n".join([
        "Kinetic BIM Standard",
        "Version {0}".format(__version__),
        "",
    ] + INTRO + [
        "",
        _license_status_line(),
        "",
        "Tools:",
    ] + tool_lines + [
        "",
        "Support: " + SUPPORT_EMAIL,
        "Logs:    " + logs,
        "         (Shift-click About to open this folder)",
        "",
        COPYRIGHT,
    ])
    forms.alert(body)


main()
