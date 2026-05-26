# -*- coding: utf-8 -*-
"""Scan options + profile config persistence for Auto Dimension.

Per-rule values (length, orientation, measurement reference, target,
style, offset) live on DimensioningProfile (see profiles.py). This
module owns:

    DEFAULT_SCAN_OPTIONS - the small set of values that genuinely
        live above any single profile.

    from_config(cfg)     - deserialise a project / company JSON file
        into (scan_options, profiles).

Mirrors annotation_qa.rules; same shape, different DEFAULT_OPTIONS.
"""

from bim_core.core import discipline_config

from dimension_qa.profiles import DimensioningProfile, default_profile_for


# ---------------------------------------------------------------------------
# Scan-level options (everything else is per-profile).
# ---------------------------------------------------------------------------

DEFAULT_SCAN_OPTIONS = {
    # Which discipline opens by default for a fresh session.
    "default_discipline_key": "mechanical",
}


# ---------------------------------------------------------------------------
# Default starting profiles
# ---------------------------------------------------------------------------

def default_profiles():
    """Starting profile set for a fresh session - one row matching the
    most common documentation default (Mechanical / Ducts).

    Filters out non-linear bindings since v1 only handles linear MEP."""
    binding = discipline_config.find_binding("mechanical", "duct")
    if binding is None:
        return []
    return [default_profile_for("mechanical", binding)]


# ---------------------------------------------------------------------------
# Config IO
# ---------------------------------------------------------------------------

def from_config(cfg):
    """Merge a JSON config (possibly partial) into (scan_options,
    profiles).

    Accepted shape:
        {"scan":     {"default_discipline_key": "mechanical"},
         "profiles": [{...}, {...}]}

    Unknown bindings (renamed in a later release) are dropped silently.
    Returns (scan_options, profiles) - profiles is a (possibly empty)
    list, scan_options is always a fresh dict.
    """
    scan = _deep_copy(DEFAULT_SCAN_OPTIONS)
    if not cfg or not isinstance(cfg, dict):
        return scan, default_profiles()

    scan_block = cfg.get("scan") or {}
    if isinstance(scan_block, dict):
        for key in DEFAULT_SCAN_OPTIONS.keys():
            if key in scan_block:
                scan[key] = scan_block[key]

    raw_profiles = cfg.get("profiles") or []
    profiles = []
    for entry in raw_profiles:
        p = DimensioningProfile.from_dict(entry)
        if p is not None:
            profiles.append(p)

    if not profiles:
        profiles = default_profiles()
    return scan, profiles


# ---------------------------------------------------------------------------
# Deep copy for UI working state
# ---------------------------------------------------------------------------

def _deep_copy(obj):
    if isinstance(obj, dict):
        return {k: _deep_copy(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_copy(v) for v in obj]
    return obj
