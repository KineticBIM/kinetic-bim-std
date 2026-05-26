# -*- coding: utf-8 -*-
"""Clash Detective COM operations.

The Clash Detective plug-in is exposed through Navisworks's plug-in
COM interface (`Document.Plugins("ClashDetective")`). list_tests,
run_tests, and export_xml_report each try the most common shapes in
order and fall back gracefully.

IronPython 2.7 / CPython 3 compatible.

INTEGRATION TEST PLAN (manual)
------------------------------
1. Open a NWF with saved clash tests. list_tests(conn) returns the
   test names.
2. run_tests(conn, [first_test_name]) - test goes from "Old" to
   "Done" in NW.
3. export_xml_report(conn, out_path) writes a well-formed XML file.
"""

from __future__ import print_function, division, absolute_import

import os

from clash_coordination.navisworks.connection import NavisworksCOMError


def _clash_detective(conn):
    doc = conn.document
    if doc is None:
        raise NavisworksCOMError("No NW document is open")
    plugins = None
    for attr in ("Plugins", "Plugin"):
        try:
            plugins = getattr(doc, attr, None)
            if plugins is not None:
                break
        except Exception:
            continue
    if plugins is None:
        raise NavisworksCOMError("Document.Plugins is unavailable")
    for plugin_id in ("ClashDetective", "Clash Detective"):
        try:
            cd = plugins.Item(plugin_id)
            if cd is not None:
                return cd
        except Exception:
            continue
        try:
            count = plugins.Count
            for i in range(count):
                p = plugins.Item(i)
                name = getattr(p, "Name", "") or getattr(p, "Identifier", "")
                if str(name).strip().lower() in ("clashdetective", "clash detective"):
                    return p
        except Exception:
            pass
    raise NavisworksCOMError(
        "Clash Detective plugin not available via Document.Plugins")


def list_tests(conn):
    """Return the names of saved clash tests in the open document."""
    cd = _clash_detective(conn)
    tests = getattr(cd, "Tests", None)
    if tests is None:
        return []

    out = []
    try:
        count = tests.Count
    except Exception:
        try:
            count = len(tests)
        except Exception:
            count = 0
    for i in range(count):
        try:
            t = tests.Item(i)
        except Exception:
            try:
                t = tests[i]
            except Exception:
                continue
        try:
            name = t.Name
        except Exception:
            name = None
        if name:
            out.append(str(name))
    return out


def _resolve_tests(cd, names):
    """Return COM test objects corresponding to `names`, in the same
    order. Names not found are silently skipped (caller logs)."""
    tests_col = getattr(cd, "Tests", None)
    if tests_col is None:
        return []

    by_name = {}
    try:
        count = tests_col.Count
    except Exception:
        count = 0
    for i in range(count):
        try:
            t = tests_col.Item(i)
            n = getattr(t, "Name", None)
            if n:
                by_name[str(n)] = t
        except Exception:
            continue

    return [by_name[n] for n in names if n in by_name]


def run_tests(conn, test_names, logger=None):
    """Run the named clash tests. Returns the list of test names that
    actually ran (i.e. were found AND the Update call didn't raise).
    """
    cd = _clash_detective(conn)
    tests = _resolve_tests(cd, test_names)
    found_names = set(getattr(t, "Name", None) for t in tests)
    missing = [n for n in test_names if n not in found_names]
    if logger and missing:
        logger.warning("Clash tests not found in NWF: %s", missing)

    ran = []
    for t in tests:
        name = getattr(t, "Name", None)
        success = False
        for method in ("Update", "Run", "RunTest"):
            if hasattr(t, method):
                try:
                    getattr(t, method)()
                    success = True
                    break
                except Exception as e:
                    if logger:
                        logger.warning("Test %r %s() raised %s", name, method, e)
        if success and name:
            ran.append(str(name))
            if logger:
                logger.info("Ran clash test: %s", name)
    return ran


def export_xml_report(conn, out_path, test_names=None, logger=None):
    """Export a ClashDetective XML report to `out_path`.

    If `test_names` is None, exports a report covering all tests in
    the document; otherwise just the named subset (subject to NW's
    own API supporting a per-test export - falls back to "all" if
    not).

    Returns the absolute path written.
    """
    cd = _clash_detective(conn)
    out_path = os.path.abspath(out_path)
    folder = os.path.dirname(out_path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)

    candidates = ("WriteXMLReport", "WriteReport", "ExportReport", "Export")
    last_err = None
    for method in candidates:
        if not hasattr(cd, method):
            continue
        try:
            if test_names:
                tests = _resolve_tests(cd, test_names)
                try:
                    getattr(cd, method)(out_path, tests)
                    if logger:
                        logger.info(
                            "Exported clash XML (%d tests) -> %s",
                            len(tests), out_path)
                    return out_path
                except Exception:
                    pass
            getattr(cd, method)(out_path)
            if logger:
                logger.info("Exported clash XML (all tests) -> %s", out_path)
            return out_path
        except Exception as e:
            last_err = e
            continue
    raise NavisworksCOMError(
        "ClashDetective XML export failed; tried {0}. Last error: {1}".format(
            candidates, last_err))
