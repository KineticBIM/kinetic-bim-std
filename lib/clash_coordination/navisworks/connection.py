# -*- coding: utf-8 -*-
"""Navisworks COM connection.

Wraps the version-specific ProgID dance behind a small NavisConnection
class. Callers do:

    with NavisConnection() as nw:
        nw.app.OpenFile(nwf_path)
        ...

The connection probes NW versions newest-first and binds to the
first one that responds. If none does, it raises NavisworksNotInstalled
with an actionable message.

IronPython 2.7 / CPython 3 compatible.

INTEGRATION TEST PLAN (manual)
------------------------------
1. Open a CPython prompt in the pyRevit Python and run:
       from clash_coordination.navisworks import connection
       conn = connection.NavisConnection()
       conn.open()
       print(conn.app)
       conn.close()
2. Verify the COM ProgID printed matches the installed NW version.
3. Verify Navisworks is left in a closed state after .close().
"""

from __future__ import print_function, division, absolute_import


# Newest-first list of known Navisworks COM ProgID suffixes. Add new
# entries at the top as new NW versions ship.
#   Suffix  | Navisworks release
#   --------|--------------------
#   23      | 2025
#   22      | 2024
#   21      | 2023
#   20      | 2022
#   19      | 2021
#   18      | 2020
#   17      | 2019
#   16      | 2018
#   15      | 2017
KNOWN_PROGIDS = [
    "Navisworks.Application.23",
    "Navisworks.Application.22",
    "Navisworks.Application.21",
    "Navisworks.Application.20",
    "Navisworks.Application.19",
    "Navisworks.Application.18",
    "Navisworks.Application.17",
    "Navisworks.Application.16",
    "Navisworks.Application.15",
    "Navisworks.Application",
]


class NavisworksNotInstalled(RuntimeError):
    """Raised when no Navisworks COM server responds."""


class NavisworksCOMError(RuntimeError):
    """Wrapper for COM-side errors."""


def _import_com():
    """Import pywin32 (CPython) or fall back to clr/.NET interop
    (IronPython). Returns a (dispatch, get_active, init, uninit)
    tuple of callables hiding the implementation difference."""
    # Try pywin32 first - documented path, works under CPython 3 and
    # under IronPython if installed.
    try:
        import win32com.client as wcc
        import pythoncom
        return (
            wcc.Dispatch,
            wcc.GetActiveObject,
            pythoncom.CoInitialize,
            pythoncom.CoUninitialize,
        )
    except ImportError:
        pass

    # IronPython fallback - System.Activator.CreateInstance via clr.
    try:
        import clr  # noqa: F401
        from System import Type, Activator
        from System.Runtime.InteropServices import Marshal

        def _dispatch(progid):
            t = Type.GetTypeFromProgID(progid)
            if t is None:
                raise NavisworksCOMError("ProgID not registered: {0}".format(progid))
            return Activator.CreateInstance(t)

        def _get_active(progid):
            return Marshal.GetActiveObject(progid)

        def _noop():
            return None

        return _dispatch, _get_active, _noop, _noop
    except Exception as e:
        raise RuntimeError(
            "Could not import a COM client. Need either pywin32 "
            "(`pip install pywin32` into the pyRevit Python) or "
            "IronPython's CLR. Underlying error: {0}".format(e))


class NavisConnection(object):
    """Lazy Navisworks COM connection.

    Use as a context manager OR explicit open/close:

        with NavisConnection() as nw:
            nw.app.OpenFile(...)

        conn = NavisConnection()
        try:
            conn.open()
            ...
        finally:
            conn.close()
    """

    def __init__(
        self,
        preferred_progid=None,
        visible=True,
        attach_to_running=True,
    ):
        self.preferred_progid = preferred_progid
        self.visible = visible
        self.attach_to_running = attach_to_running

        self.app = None
        self.progid = None
        self._coinit = False
        self._owns_app = False

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def open(self):
        dispatch, get_active, coinit, _coun = _import_com()
        try:
            coinit()
            self._coinit = True
        except Exception:
            pass

        candidates = []
        if self.preferred_progid:
            candidates.append(self.preferred_progid)
        candidates.extend(KNOWN_PROGIDS)
        tried = []
        last_err = None

        if self.attach_to_running:
            for progid in candidates:
                if not progid:
                    continue
                try:
                    self.app = get_active(progid)
                    self.progid = progid
                    self._owns_app = False
                    self._post_open()
                    return
                except Exception as e:
                    last_err = e
                    tried.append("attach:" + progid)

        for progid in candidates:
            if not progid:
                continue
            try:
                self.app = dispatch(progid)
                self.progid = progid
                self._owns_app = True
                self._post_open()
                return
            except Exception as e:
                last_err = e
                tried.append("dispatch:" + progid)

        raise NavisworksNotInstalled(
            "Could not bind to any Navisworks COM server. Tried: {0}. "
            "Underlying error: {1}".format(", ".join(tried), last_err))

    def _post_open(self):
        try:
            self.app.Visible = self.visible
        except Exception:
            pass

    def close(self):
        _, _, _, coun = _import_com()
        try:
            if self.app is not None and self._owns_app:
                try:
                    self.app.Quit()
                except Exception:
                    pass
        finally:
            self.app = None
            if self._coinit:
                try:
                    coun()
                except Exception:
                    pass
                self._coinit = False

    @property
    def document(self):
        """Currently open MainDocument, or None if no file is open."""
        if self.app is None:
            return None
        try:
            return self.app.MainDocument
        except Exception:
            return None
