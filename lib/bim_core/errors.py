# -*- coding: utf-8 -*-
"""User-facing error display helpers for Kinetic BIM tools.

Wraps pyRevit's forms.alert with three pieces of polish missing from
the raw `forms.alert("...{0}".format(exc))` patterns scattered through
the tools:

    1. The full traceback goes to the tool's bim_core.log logger so
       support can read it later, but only the friendly summary plus
       short exception message is shown to the user.
    2. A consistent title prefix ("[Auto Tag]") is prepended so the
       user knows which tool produced the error.
    3. The log file path is appended to the dialog body so the user
       can find the detail when reporting to support.

Replaces:
    forms.alert("Scan failed: {0}".format(exc), exitscript=False)
    logger.exception("Scan failed")
                   with
    errors.show_error("auto_tag",
                      "Couldn't scan the model.",
                      exc=exc, logger=logger)
"""

from pyrevit import forms

from bim_core import log as log_module


def show_error(tool_name, summary, exc=None, logger=None, exitscript=False):
    """Show a friendly error dialog and log the full traceback.

    Args:
        tool_name: Snake_case tool identifier matching the bim_core.log
            log filename (e.g. "auto_tag"). Drives the dialog title
            ("[Auto Tag]") and the log lookup when logger is omitted.
        summary: One-line user-facing message. Plain English, no Python
            jargon. E.g. "Couldn't read the sheet list".
        exc: The exception object. Its str() form is appended under
            the summary in the dialog; the full traceback goes to
            the log.
        logger: Optional bim_core.log logger. If omitted, resolved
            via tool_name.
        exitscript: When True, terminates the script after the dialog
            closes (matches pyRevit forms.alert convention). Default
            False so the caller can continue.
    """
    title = _display_title(tool_name)

    if exc is not None:
        if logger is None and tool_name:
            try:
                logger = log_module.get_logger(tool_name=tool_name)
            except Exception:
                logger = None
        if logger is not None:
            try:
                logger.exception("%s: %s", summary, exc)
            except Exception:
                pass

    body_lines = ["[{0}]".format(title), summary]
    if exc is not None:
        exc_msg = str(exc).strip()
        if exc_msg:
            body_lines.append("")
            body_lines.append("Detail: " + exc_msg)
    log_p = log_module.log_path(tool_name) if tool_name else None
    if log_p:
        body_lines.append("")
        body_lines.append("Log: " + log_p)

    forms.alert("\n".join(body_lines), exitscript=exitscript)


def _display_title(tool_name):
    """Convert 'auto_tag' -> 'Auto Tag' for dialog titles."""
    if not tool_name:
        return "Kinetic BIM"
    parts = [p.capitalize() for p in tool_name.replace("_", " ").split() if p]
    return " ".join(parts) or "Kinetic BIM"
