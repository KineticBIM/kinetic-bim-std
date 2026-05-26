# -*- coding: utf-8 -*-
"""Screenshot export from Navisworks.

For every saved viewpoint we want a PNG, named consistently so the
HTML summary and Excel report can reference it by predictable path:

    <ScreenshotsFolder>/<safe_clash_name>.png

IronPython 2.7 / CPython 3 compatible.

INTEGRATION TEST PLAN
---------------------
1. Open a NWF, run a clash test, call capture_clash_screenshots()
   pointing at the run's Screenshots/ folder. Verify one PNG per
   clash lands on disk.
2. Open one of the PNGs - it should show the clash highlighted
   exactly as NW shows it when the viewpoint is activated.
"""

from __future__ import print_function, division, absolute_import

import os

from clash_coordination.navisworks.viewpoints import iter_clash_viewpoints


def _safe_filename(text):
    """Replace filesystem-unsafe characters with `_`."""
    bad = ':/\\?*"<>|\r\n\t'
    out = "".join("_" if c in bad else c for c in (text or ""))
    return out.strip().strip(".")


def _activate_viewpoint(conn, viewpoint_name):
    """Make `viewpoint_name` the current viewpoint. Returns True on
    success."""
    doc = conn.document
    if doc is None:
        return False
    saved = getattr(doc, "SavedViewpoints", None)
    if saved is None:
        return False
    for method in ("Activate", "ActivateViewpoint", "Apply"):
        if hasattr(saved, method):
            try:
                getattr(saved, method)(viewpoint_name)
                return True
            except Exception:
                continue
    for method in ("SetCurrentViewpoint", "SetCurrentSavedViewpoint"):
        if hasattr(doc, method):
            try:
                getattr(doc, method)(viewpoint_name)
                return True
            except Exception:
                continue
    return False


def _take_snapshot(conn, out_path, size):
    """Render the current view to a PNG file at `out_path`. Returns
    True on success."""
    width, height = size
    doc = conn.document
    if doc is None:
        return False
    for method in ("SnapshotImage", "SaveImage", "ExportImage"):
        if hasattr(doc, method):
            try:
                getattr(doc, method)(out_path, int(width), int(height))
                return True
            except Exception:
                try:
                    getattr(doc, method)(out_path)
                    return True
                except Exception:
                    continue
    if hasattr(conn.app, "SnapshotImage"):
        try:
            conn.app.SnapshotImage(out_path, int(width), int(height))
            return True
        except Exception:
            pass
    return False


def capture_viewpoints(
    conn, out_folder, viewpoint_names,
    size=(1920, 1080), name_pattern="{name}.png", logger=None,
):
    """Snapshot each named viewpoint into `out_folder`. Returns the
    list of PNG paths actually written.
    """
    if not os.path.isdir(out_folder):
        os.makedirs(out_folder)

    written = []
    for i, vp_name in enumerate(viewpoint_names):
        if not _activate_viewpoint(conn, vp_name):
            if logger:
                logger.warning("Could not activate viewpoint: %s", vp_name)
            continue
        safe = _safe_filename(vp_name) or "viewpoint_{0}".format(i)
        filename = name_pattern.format(name=safe, index=i)
        out_path = os.path.join(out_folder, filename)
        if _take_snapshot(conn, out_path, size):
            written.append(out_path)
            if logger:
                logger.info("Snapshot saved: %s", out_path)
        else:
            if logger:
                logger.warning("Failed to snapshot viewpoint: %s", vp_name)
    return written


def capture_clash_screenshots(
    conn, out_folder, test_names,
    size=(1920, 1080), logger=None,
):
    """Snapshot every Clash Detective auto-generated viewpoint that
    belongs to one of the named clash tests.
    """
    if not os.path.isdir(out_folder):
        os.makedirs(out_folder)

    all_views = iter_clash_viewpoints(conn)
    targets = []
    prefixes = ["{0}:".format(name) for name in test_names]
    for _folder, name, _guid in all_views:
        for pref in prefixes:
            if name.startswith(pref):
                targets.append(name)
                break
    if logger:
        logger.info(
            "Capturing %d clash viewpoints across %d tests",
            len(targets), len(test_names))
    return capture_viewpoints(
        conn, out_folder, targets, size=size,
        name_pattern="{name}.png", logger=logger,
    )
