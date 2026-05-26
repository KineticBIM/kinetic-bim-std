# -*- coding: utf-8 -*-
"""Drive Navisworks via the navisworks/ COM layer to refresh the
federated model, then post-process the refresh outcome.

This is a thin orchestration layer between the COM seam and the
plain-Python validator. Keeping the seam thin means: if NW's COM
API changes shape in a future version, the impact is contained to
`navisworks/document.py`, and this module + everything above it
keeps working.

IronPython 2.7 / CPython 3 compatible.
"""

from __future__ import print_function, division, absolute_import

import os

from clash_coordination.navisworks import document as nw_document


# IronPython 2.7 doesn't have FileNotFoundError. Alias to IOError so
# the same `raise FileNotFoundError(...)` works under both runtimes,
# and CPython 3 tests using `pytest.raises(FileNotFoundError)` still
# hit the right class (the alias only takes effect when the builtin
# is missing).
try:
    FileNotFoundError
except NameError:
    FileNotFoundError = IOError


def refresh_federated_model(conn, nwf_path, fail_on_missing=False, logger=None):
    """Open + refresh the federated model.

    If the model isn't already open, opens it. Refreshes all links.
    Returns a RefreshReport.

    If `fail_on_missing` is True and any link path doesn't resolve
    on disk, raises FileNotFoundError after producing the report
    (so the report is still inspectable via the exception's args).
    """
    doc = conn.document
    if doc is None or _normalise_path(_get_doc_filename(doc)) != _normalise_path(nwf_path):
        nw_document.open_federated(conn, nwf_path, logger=logger)

    report = nw_document.refresh_all(conn, nwf_path=nwf_path, logger=logger)
    if fail_on_missing and report.missing:
        if logger:
            logger.error(
                "Aborting: %d link file(s) missing from disk: %s",
                len(report.missing), report.missing)
        raise FileNotFoundError(
            "Missing linked files: {0}".format(report.missing))
    return report


def _get_doc_filename(doc):
    if doc is None:
        return ""
    for attr in ("FileName", "CurrentFileName", "Path"):
        try:
            v = getattr(doc, attr, None)
            if v:
                return str(v)
        except Exception:
            continue
    return ""


def _normalise_path(p):
    if not p:
        return ""
    try:
        return os.path.normcase(os.path.abspath(p))
    except Exception:
        return p
