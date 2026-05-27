# -*- coding: utf-8 -*-
"""Auto Dimension config persistence.

The bridge between disk JSON and the UI's in-memory state. Two
operations:

    load_for_doc(doc)
        Resolve a config source for `doc` and return
        (scan_options, profiles). Search order:
            1. <dirname(doc.PathName)>/.bim/auto_dimension.json
            2. <extension>/lib/dimension_qa/configs/default.json
            3. In-code rules.DEFAULT_SCAN_OPTIONS + default_profiles()
        Falls through silently on a missing file; logs a warning if a
        present file fails to parse. Never raises - the UI must always
        end up with usable defaults.

    save_for_doc(doc, scan_options, profiles)
        Serialise current state to <dirname(doc.PathName)>/.bim/
        auto_dimension.json. Returns the path written, or None when
        the doc is unsaved (no PathName, so nowhere to put a project
        config). Errors are logged and swallowed: a failed save should
        never block the user from closing the dialog.

This module owns the path conventions so script.py and the UI agree
on where the config lives. If the location ever moves, this is the
only file that changes.

Imports only stdlib so it loads under both IronPython 2.7 and
CPython 3.11+ (the analysis venv).
"""

import io
import json
import os

from dimension_qa import rules


PROJECT_CONFIG_FILENAME = "auto_dimension.json"
PROJECT_CONFIG_SUBDIR   = ".bim"


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def extension_default_path():
    """<extension>/lib/dimension_qa/configs/default.json - always
    present; bundled with the extension."""
    return os.path.join(os.path.dirname(__file__), "configs", "default.json")


def project_config_path(doc):
    """<dirname(doc.PathName)>/.bim/auto_dimension.json, or None when
    the doc has no path yet (unsaved / detached models)."""
    if doc is None:
        return None
    try:
        pn = doc.PathName
    except Exception:
        return None
    if not pn:
        return None
    return os.path.join(os.path.dirname(pn),
                        PROJECT_CONFIG_SUBDIR,
                        PROJECT_CONFIG_FILENAME)


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_for_doc(doc, logger=None):
    """Return (scan_options, profiles) from the most-specific source
    available. See module docstring for the search order.
    """
    # 1. Project config.
    proj = project_config_path(doc)
    if proj and os.path.isfile(proj):
        cfg = _read_json(proj, logger)
        if cfg is not None:
            if logger:
                logger.info("Loaded config from project: %s", proj)
            return rules.from_config(cfg)

    # 2. Extension default.
    ext = extension_default_path()
    if os.path.isfile(ext):
        cfg = _read_json(ext, logger)
        if cfg is not None:
            if logger:
                logger.info("Loaded config from extension default: %s", ext)
            return rules.from_config(cfg)

    # 3. In-code fallback - guarantees a usable state even with both
    #    files missing or unreadable.
    if logger:
        logger.info("No config files found; using in-code defaults.")
    return (rules._deep_copy(rules.DEFAULT_SCAN_OPTIONS),
            rules.default_profiles())


def _read_json(path, logger):
    """Parse a JSON file. Returns the dict on success, or None on any
    error (with a logged warning). Open-mode keeps IronPython and
    CPython happy: io.open + utf-8 returns unicode/str respectively;
    json.loads handles both."""
    try:
        with io.open(path, "r", encoding="utf-8") as fh:
            return json.loads(fh.read())
    except Exception as exc:
        if logger:
            logger.warning("Failed to read JSON %s: %s", path, exc)
        return None


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def save_for_doc(doc, scan_options, profiles, logger=None):
    """Persist scan_options + profiles to the project's
    auto_dimension.json.

    Returns the path written, or None when the doc is unsaved (nothing
    to write to) or an error occurred. Save errors do NOT raise -
    the UI's close handler is the typical caller and must always
    complete.
    """
    proj = project_config_path(doc)
    if proj is None:
        if logger:
            logger.info(
                "Skip config save: document has no path (unsaved/detached).")
        return None

    payload = {
        "scan":     dict(scan_options or {}),
        "profiles": [p.to_dict() for p in (profiles or [])],
    }

    try:
        folder = os.path.dirname(proj)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        # ensure_ascii=False keeps the human-edit experience readable
        # (no \uXXXX escapes for non-ASCII project names). io.open with
        # encoding handles the IronPython / CPython unicode story
        # uniformly.
        with io.open(proj, "w", encoding="utf-8") as fh:
            fh.write(_dumps(payload))
        if logger:
            logger.info("Saved config to %s (%d profiles)",
                        proj, len(payload["profiles"]))
        return proj
    except Exception as exc:
        if logger:
            logger.warning("Failed to save config to %s: %s", proj, exc)
        return None


def _dumps(payload):
    """json.dumps wrapper that always yields unicode (for io.open's
    text-mode write). json.dumps with ensure_ascii=False returns str
    in Py3 and unicode in IronPython 2.7; both write cleanly."""
    out = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)
    if isinstance(out, bytes):
        out = out.decode("utf-8")
    return out
