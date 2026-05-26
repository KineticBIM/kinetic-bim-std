# -*- coding: utf-8 -*-
"""Document-level Navisworks operations: open, save, refresh, link enum.

All operations expect a live `NavisConnection` from connection.py.
Functions are designed to be no-op-safe (raise rather than corrupt
state) and to log via a caller-provided logger so the orchestrator
gets one coherent trail.

IronPython 2.7 / CPython 3 compatible.

INTEGRATION TEST PLAN (manual)
------------------------------
1. open_federated(conn, "test.nwf") with a known-good NWF; assert
   conn.document is not None afterwards.
2. enumerate_links(conn) returns the same paths NW's Selection Tree
   shows under the federated root.
3. refresh_all(conn) does not error on a model with valid links;
   on a model with a missing link it returns a report flagging the
   missing path.
"""

from __future__ import print_function, division, absolute_import

import os
import time

from clash_coordination.data import models
from clash_coordination.model_refresh import validator as validator_module
from clash_coordination.navisworks.connection import NavisworksCOMError


try:
    FileNotFoundError
except NameError:
    FileNotFoundError = IOError


def open_federated(conn, nwf_path, logger=None):
    """Open a NWF/NWD in the Navisworks COM application.

    Raises FileNotFoundError if `nwf_path` doesn't exist on disk
    before we even talk to NW. Raises NavisworksCOMError on a COM
    failure during open.
    """
    if not os.path.isfile(nwf_path):
        raise FileNotFoundError(
            "Federated model not found: {0}".format(nwf_path))
    if conn.app is None:
        raise NavisworksCOMError(
            "NavisConnection.open() must be called before open_federated")

    if logger:
        logger.info("Opening federated model: %s", nwf_path)
    try:
        conn.app.OpenFile(nwf_path)
    except Exception as e:
        raise NavisworksCOMError(
            "Failed to open {0} in Navisworks: {1}".format(nwf_path, e))


def save_document(conn, logger=None):
    """Save the currently open document. No-op if no document open."""
    doc = conn.document
    if doc is None:
        if logger:
            logger.warning("save_document called with no document open")
        return
    try:
        doc.Save()
    except Exception as e:
        raise NavisworksCOMError("Failed to save NW document: {0}".format(e))


def enumerate_links(conn):
    """Return the absolute paths of NWC/NWD files linked into the
    open federated model.
    """
    doc = conn.document
    if doc is None:
        return []

    paths = []

    models_collection = None
    for attr in ("Models", "DocumentModels"):
        try:
            candidate = getattr(doc, attr, None)
            if candidate is not None:
                models_collection = candidate
                break
        except Exception:
            continue
    if models_collection is None:
        return paths

    try:
        count = models_collection.Count
    except Exception:
        try:
            count = len(models_collection)
        except Exception:
            count = 0

    for i in range(count):
        try:
            model = models_collection.Item(i)
        except Exception:
            try:
                model = models_collection[i]
            except Exception:
                continue
        for prop in ("FileName", "Source", "Path", "SourceFile"):
            try:
                value = getattr(model, prop, None)
                if value:
                    paths.append(str(value))
                    break
            except Exception:
                continue
    return paths


def refresh_all(conn, nwf_path=None, logger=None):
    """Refresh every NWC/NWD reference in the open federated model."""
    started = time.time()
    report = models.RefreshReport()

    doc = conn.document
    if doc is None:
        report.failed.append(("(no document)", "no NW document is open"))
        report.duration_s = time.time() - started
        return report

    # 1) Path-level pre-check, before we talk COM at all.
    links = enumerate_links(conn)
    federated_mtime = None
    if nwf_path and os.path.isfile(nwf_path):
        try:
            federated_mtime = os.path.getmtime(nwf_path)
        except OSError:
            federated_mtime = None
    validation = validator_module.validate_paths(
        links, federated_mtime=federated_mtime)
    report.missing.extend(validation.missing)
    if logger and validation.missing:
        logger.warning("Missing link files: %s", validation.missing)

    # 2) Drive NW to do the actual refresh.
    refresh_done = False
    for method in ("RefreshAll", "Refresh"):
        if hasattr(doc, method):
            try:
                getattr(doc, method)()
                refresh_done = True
                break
            except Exception as e:
                report.failed.append(
                    ("(refresh)", "{0}() raised {1}".format(method, e)))
    if not refresh_done:
        for method in ("RefreshAll", "Refresh"):
            if hasattr(conn.app, method):
                try:
                    getattr(conn.app, method)()
                    refresh_done = True
                    break
                except Exception as e:
                    report.failed.append(
                        ("(refresh)",
                         "Application.{0}() raised {1}".format(method, e)))

    if refresh_done:
        for p in links:
            if p not in validation.missing:
                report.refreshed.append(p)
        if logger:
            logger.info("Refreshed %d linked files.", len(report.refreshed))
    else:
        if logger:
            logger.error("Could not invoke any Refresh method on NW document.")

    report.duration_s = time.time() - started
    return report


def federated_meta(conn):
    """Light bag of metadata about the open federated model, for the
    run record (filename, mtime, link count). All fields optional -
    missing ones come back as None."""
    doc = conn.document
    out = {"filename": None, "mtime": None, "link_count": None}
    if doc is None:
        return out
    try:
        out["filename"] = doc.FileName
    except Exception:
        pass
    if out["filename"] and os.path.isfile(out["filename"]):
        try:
            out["mtime"] = os.path.getmtime(out["filename"])
        except OSError:
            pass
    try:
        out["link_count"] = len(enumerate_links(conn))
    except Exception:
        pass
    return out
