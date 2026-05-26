# -*- coding: utf-8 -*-
"""Dated coordination folder layout.

Produces and validates the standard coordination folder structure:

    <output_root>/
        2026-05-14/
            Reports/
            Viewpoints/
            Screenshots/
            Logs/

Pure stdlib - works under IronPython 2.7 and CPython 3.
"""

from __future__ import print_function, division, absolute_import

import datetime
import os


SUBFOLDERS = ("Reports", "Viewpoints", "Screenshots", "Logs")


def today_stamp():
    """Return today's date as YYYY-MM-DD. Centralised so tests can
    monkey-patch a known date."""
    return datetime.date.today().isoformat()


def coordination_run_folder(output_root, run_date=None, create=True):
    """Return the absolute path to the dated coordination folder,
    creating it and its standard subfolders if `create` is True.

    run_date defaults to today (YYYY-MM-DD). A non-default value
    lets the caller backdate (rare - debugging) or reuse an existing
    folder (e.g. a re-run later the same day, which lands in the
    same folder).
    """
    if not output_root:
        raise ValueError("output_root is required")
    date = run_date or today_stamp()
    folder = os.path.join(output_root, date)
    if create:
        for sub in SUBFOLDERS:
            target = os.path.join(folder, sub)
            if not os.path.isdir(target):
                os.makedirs(target)
    return folder


def subfolder_paths(run_folder):
    """Return `{name_lower: absolute_path}` for the standard subfolders.

    Doesn't create anything - call coordination_run_folder(...) first
    with create=True.
    """
    return dict((name.lower(), os.path.join(run_folder, name)) for name in SUBFOLDERS)


def _parse_date_or_none(name):
    """Return a datetime.date for a YYYY-MM-DD-formatted name, else None.

    Hand-rolled because datetime.date.fromisoformat is Python 3.7+
    only and we run under IronPython 2.7 too.
    """
    if not name or len(name) != 10 or name[4] != "-" or name[7] != "-":
        return None
    try:
        year = int(name[0:4])
        month = int(name[5:7])
        day = int(name[8:10])
        return datetime.date(year, month, day)
    except (ValueError, TypeError):
        return None


def latest_run_folder(output_root):
    """Return the absolute path to the most recent dated coord folder
    under output_root, or None if there are no dated subfolders.

    Used by the pushbutton shift-click affordance to "open the most
    recent coordination output folder".
    """
    if not output_root or not os.path.isdir(output_root):
        return None
    candidates = []
    for name in os.listdir(output_root):
        full = os.path.join(output_root, name)
        if not os.path.isdir(full):
            continue
        d = _parse_date_or_none(name)
        if d is None:
            continue
        candidates.append((name, full))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    return candidates[-1][1]


def previous_run_folder(output_root, before_date):
    """Return the absolute path to the most recent dated coord folder
    strictly before `before_date`. Used by history.snapshots to find
    the previous week's snapshot for delta computation.
    """
    if not output_root or not os.path.isdir(output_root):
        return None
    target = _parse_date_or_none(before_date)
    if target is None:
        return None
    candidates = []
    for name in os.listdir(output_root):
        full = os.path.join(output_root, name)
        if not os.path.isdir(full):
            continue
        d = _parse_date_or_none(name)
        if d is None or d >= target:
            continue
        candidates.append((d, full))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    return candidates[-1][1]
