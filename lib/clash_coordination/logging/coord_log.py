# -*- coding: utf-8 -*-
"""Coordination logger - writes into the coordination output folder.

Mirrors the bim_core.log API (`get_logger`) but resolves the log
directory from an explicit output folder argument instead of the
Revit document path. Coordination runs operate on the federated
Navisworks model, which doesn't live in any one Revit project, so
the bim_core logger's project-folder convention is the wrong target
here.

Loggers are cached per (tool_name, log_path) so repeated calls from
inside one run reuse the handler and timestamps stay coherent.

IronPython 2.7 / CPython 3 compatible.
"""

from __future__ import print_function, division, absolute_import

import datetime
import logging
import os


_LOGGERS = {}     # (tool_name, log_path) -> Logger
_LOG_PATHS = {}   # (tool_name, log_path) -> path


def _ensure_folder(folder):
    if not os.path.isdir(folder):
        os.makedirs(folder)


def get_logger(output_folder, tool_name="clash_coordination", timestamped=True):
    """Return a logger that writes into `output_folder/Logs/`.

    `output_folder` is the dated coordination folder for this run
    (e.g. `<root>/2026-05-14/`). `Logs/` is created if it doesn't
    exist; the log filename includes a timestamp so multiple runs
    on the same day don't clobber each other.

    `timestamped=False` produces a fixed `<tool_name>.log` filename,
    useful for testing.
    """
    if not output_folder:
        raise ValueError("output_folder is required for the coord logger")

    log_folder = os.path.join(output_folder, "Logs")
    _ensure_folder(log_folder)

    if timestamped:
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        filename = "{0}_{1}.log".format(tool_name, stamp)
    else:
        filename = "{0}.log".format(tool_name)
    log_path = os.path.join(log_folder, filename)

    key = (tool_name, log_path)
    cached = _LOGGERS.get(key)
    if cached is not None:
        return cached

    logger = logging.getLogger("{0}::{1}".format(tool_name, log_path))
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    if not logger.handlers:
        fh = logging.FileHandler(log_path)
        fmt = logging.Formatter(
            "%(asctime)s %(levelname)-7s %(message)s",
            "%Y-%m-%d %H:%M:%S",
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    _LOGGERS[key] = logger
    _LOG_PATHS[key] = log_path
    return logger


def log_path(output_folder, tool_name="clash_coordination"):
    """Return the file path of the most recently created logger for
    (tool_name, output_folder). None if no logger has been created
    yet."""
    target_prefix = os.path.join(output_folder, "Logs")
    for (tn, lp) in _LOG_PATHS.keys():
        if tn == tool_name and lp.startswith(target_prefix):
            return lp
    return None


def reset():
    """Drop all cached loggers + handlers. Useful between tests and
    between runs in one Revit session to avoid handler leakage."""
    for logger in _LOGGERS.values():
        for h in list(logger.handlers):
            try:
                h.close()
            except Exception:
                pass
            logger.removeHandler(h)
    _LOGGERS.clear()
    _LOG_PATHS.clear()
