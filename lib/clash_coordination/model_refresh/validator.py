# -*- coding: utf-8 -*-
"""Path validation for federated model links.

Plain Python (IronPython 2.7 / CPython 3) - no Navisworks dependency.
The navisworks/document layer reads the link table from the open
federated model and hands this module a list of paths; this module
checks they exist on disk and returns a ValidationReport.

Splitting it out from the COM layer means: (1) this code is fully
unit-tested, (2) when a Navisworks API change breaks the link
enumeration in the future, the broken seam is small and obvious.
"""

from __future__ import print_function, division, absolute_import

import os


class ValidationReport(object):
    """Result of checking that a federated model's link paths
    resolve on disk."""

    def __init__(
        self,
        checked=None,
        found=None,
        missing=None,
        stale=None,
        notes=None,
    ):
        self.checked = checked if checked is not None else []
        self.found = found if found is not None else []
        self.missing = missing if missing is not None else []
        self.stale = stale if stale is not None else []
        self.notes = notes if notes is not None else {}

    @property
    def all_ok(self):
        return not (self.missing or self.stale)

    def summarise(self):
        if self.all_ok:
            return "All {0} linked files resolved.".format(len(self.found))
        return (
            "Linked files: {0} OK, {1} missing, {2} stale.".format(
                len(self.found), len(self.missing), len(self.stale)))


def validate_paths(link_paths, federated_mtime=None):
    """Check whether each path in `link_paths` exists on disk.

    `federated_mtime`, when given, is the modification time of the
    NWF. A link file newer than the NWF gets a note logged but isn't
    flagged as stale - it's NORMAL for source models to be updated
    after the NWF was last saved.
    """
    report = ValidationReport()
    for path in link_paths:
        report.checked.append(path)
        if not path:
            report.missing.append(path)
            report.notes[path] = "empty path"
            continue
        if os.path.isfile(path):
            report.found.append(path)
            if federated_mtime is not None:
                try:
                    src_mtime = os.path.getmtime(path)
                except OSError:
                    src_mtime = None
                if src_mtime is not None and src_mtime > federated_mtime:
                    report.notes[path] = "source updated since NWF saved"
        else:
            report.missing.append(path)
            report.notes[path] = "not found on disk"
    return report
