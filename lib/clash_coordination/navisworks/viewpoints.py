# -*- coding: utf-8 -*-
"""Viewpoint export from Navisworks.

Two operations:

  1. export_viewpoints_xml(conn, out_path) - dump the full saved
     viewpoints tree to an XML file in NW's native viewpoint XML
     format. This is what the parsing.viewpoints module reads.

  2. iter_clash_viewpoints(conn) - yield (folder_path, viewpoint_name,
     guid) tuples for every clash that has an associated
     auto-generated viewpoint.

IronPython 2.7 / CPython 3 compatible.

INTEGRATION TEST PLAN
---------------------
1. Open a NWF with saved viewpoints. export_viewpoints_xml() should
   produce a non-empty XML file with <viewfolder>/<view> entries.
2. After running clashes, iter_clash_viewpoints() should yield one
   entry per clash result (NW auto-creates them).
"""

from __future__ import print_function, division, absolute_import

import os

from clash_coordination.navisworks.connection import NavisworksCOMError


def export_viewpoints_xml(conn, out_path, logger=None):
    """Write the saved viewpoints tree to `out_path`. Returns the
    absolute path written.
    """
    doc = conn.document
    if doc is None:
        raise NavisworksCOMError("No NW document is open")
    out_path = os.path.abspath(out_path)
    folder = os.path.dirname(out_path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)

    last_err = None

    saved = getattr(doc, "SavedViewpoints", None)
    if saved is not None:
        for method in ("WriteXML", "WriteToXML", "ExportXML", "Export"):
            if hasattr(saved, method):
                try:
                    getattr(saved, method)(out_path)
                    if logger:
                        logger.info("Exported viewpoints XML -> %s", out_path)
                    return out_path
                except Exception as e:
                    last_err = e
                    continue

    for method in ("WriteViewpointsXML", "ExportViewpoints", "ExportViewpointsXML"):
        if hasattr(doc, method):
            try:
                getattr(doc, method)(out_path)
                if logger:
                    logger.info("Exported viewpoints XML -> %s", out_path)
                return out_path
            except Exception as e:
                last_err = e
                continue

    raise NavisworksCOMError(
        "Viewpoints XML export failed. Last error: {0}".format(last_err))


def _walk(node, folder_path, out):
    """Recursively walk a viewpoint folder COM node."""
    try:
        items = getattr(node, "Items", None) or getattr(node, "Viewpoints", None)
        if items is not None:
            try:
                count = items.Count
            except Exception:
                count = 0
            for i in range(count):
                try:
                    it = items.Item(i)
                except Exception:
                    try:
                        it = items[i]
                    except Exception:
                        continue
                name = getattr(it, "Name", None) or ""
                out.append((folder_path, str(name), getattr(it, "GUID", "") or ""))

        folders = getattr(node, "Folders", None) or getattr(node, "SubFolders", None)
        if folders is not None:
            try:
                count = folders.Count
            except Exception:
                count = 0
            for i in range(count):
                try:
                    sub = folders.Item(i)
                except Exception:
                    try:
                        sub = folders[i]
                    except Exception:
                        continue
                sub_name = getattr(sub, "Name", "") or ""
                next_path = folder_path + " > " + sub_name if folder_path else sub_name
                _walk(sub, next_path, out)
    except Exception:
        return


def iter_clash_viewpoints(conn):
    """Return `(folder_path, viewpoint_name, guid)` for every saved
    viewpoint in the open document."""
    doc = conn.document
    if doc is None:
        return []
    root = getattr(doc, "SavedViewpoints", None)
    if root is None:
        return []
    out = []
    _walk(root, "", out)
    return out
