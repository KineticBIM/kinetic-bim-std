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


def show_error_modal(tool_name, summary, exc=None, tb=None, logger=None):
    """Show a modal error dialog from a WPF window context.

    Sibling of show_error for tools whose UI is a WPF window rather
    than a pyRevit pushbutton screen. forms.alert does not own a WPF
    dialog parent, so we route through System.Windows.MessageBox to
    get correct modality and z-order. Body composition mirrors
    show_error: friendly summary, optional exception detail, and the
    log path the user can hand to support.

    tb: optional pre-formatted traceback string. Provide it when the
        caller catches the exception on a worker thread and only
        invokes the dialog later from the dispatcher thread — by then
        sys.exc_info has cleared, so logger.exception would record an
        empty traceback. When omitted, falls back to logger.exception
        (correct only inside the original except block).
    """
    import clr  # type: ignore
    clr.AddReference("PresentationFramework")
    from System.Windows import (   # type: ignore  # noqa: E402
        MessageBox, MessageBoxButton, MessageBoxImage,
    )

    title = _display_title(tool_name)

    if exc is not None:
        if logger is None and tool_name:
            try:
                logger = log_module.get_logger(tool_name=tool_name)
            except Exception:
                logger = None
        if logger is not None:
            try:
                if tb:
                    logger.error("%s: %s\n%s", summary, exc, tb)
                else:
                    logger.exception("%s: %s", summary, exc)
            except Exception:
                pass

    body_lines = [summary]
    if exc is not None:
        exc_msg = str(exc).strip()
        if exc_msg:
            body_lines.append("")
            body_lines.append("Detail: " + exc_msg)
    log_p = log_module.log_path(tool_name) if tool_name else None
    if log_p:
        body_lines.append("")
        body_lines.append("Log: " + log_p)

    MessageBox.Show(
        "\n".join(body_lines),
        title,
        MessageBoxButton.OK,
        MessageBoxImage.Error,
    )


def _display_title(tool_name):
    """Convert 'auto_tag' -> 'Auto Tag' for dialog titles."""
    if not tool_name:
        return "Kinetic BIM"
    parts = [p.capitalize() for p in tool_name.replace("_", " ").split() if p]
    return " ".join(parts) or "Kinetic BIM"
