# -*- coding: utf-8 -*-
"""Per-tool file logger.

Each tool calls get_logger(doc, tool_name) to get its own logger that
writes to %LOCALAPPDATA%\\KineticBIM\\logs\\<tool_name>.log. The location
is user-local and independent of the active document, so it works
identically for local, cloud (Autodesk Docs / BIM 360), and unsaved
models. Loggers are cached per tool_name so multiple modules in one
tool share the same handler.

If the log directory or file cannot be created (locked-down machine,
roaming-profile quirks, etc.) get_logger falls back to a NullHandler
and the tool still runs.
"""

import os
import logging


_LOGGERS = {}   # tool_name -> Logger
_LOG_PATHS = {}   # tool_name -> path string, or None if file logging unavailable


def _resolve_log_dir(doc=None):
    # doc is accepted for API compatibility with existing callers but
    # is intentionally ignored: log location must not depend on the
    # model path (cloud-hosted models surface paths like "Autodesk Docs:"
    # that crash os.makedirs).
    base = (os.environ.get("LOCALAPPDATA")
            or os.environ.get("APPDATA")
            or os.path.expanduser("~"))
    base = os.path.expandvars(base or "")
    if not base:
        base = os.path.expanduser("~")
    folder = os.path.normpath(os.path.join(base, "KineticBIM", "logs"))
    # IronPython 2.7's os.makedirs has no exist_ok kwarg, so guard manually.
    # Tolerate races and unwritable targets — get_logger's FileHandler step
    # will fail next and fall back to NullHandler, which is the right surface
    # for the user-visible behavior.
    try:
        if not os.path.isdir(folder):
            os.makedirs(folder)
    except (OSError, IOError):
        pass
    return folder


def get_logger(doc=None, tool_name="bim_tool"):
    """Return the singleton logger for the named tool.

    tool_name is used both as the logger name (shows up in formatter
    output) and as the log file's basename - keep it filesystem-safe.
    """
    cached = _LOGGERS.get(tool_name)
    if cached is not None:
        return cached

    logger = logging.getLogger(tool_name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if not logger.handlers:
        handler = None
        resolved_path = None
        try:
            folder = _resolve_log_dir(doc)
            candidate = os.path.join(folder, "{0}.log".format(tool_name))
            handler = logging.FileHandler(candidate, encoding="utf-8")
            resolved_path = candidate
        except (OSError, IOError, ValueError):
            handler = logging.NullHandler()

        try:
            handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)-7s %(message)s",
                "%Y-%m-%d %H:%M:%S",
            ))
        except Exception:
            pass
        logger.addHandler(handler)
        _LOG_PATHS[tool_name] = resolved_path

    _LOGGERS[tool_name] = logger
    return logger


def log_path(tool_name="bim_tool"):
    """Path of the named tool's active log file. None if get_logger
    hasn't been called for it yet, or if file logging fell back to
    a NullHandler."""
    return _LOG_PATHS.get(tool_name)
