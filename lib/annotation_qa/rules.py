# -*- coding: utf-8 -*-
"""Scan options + profile config persistence for the Auto Tag tool.

In v5 the per-rule values (min/max length, orientation, size,
skip-tagged, leader, tag family) live on TaggingProfile objects
(see profiles.py). This module owns:

    DEFAULT_SCAN_OPTIONS - the small set of values that genuinely
        live above any single profile (scope toggle, default
        discipline to expand on first launch).

    from_config(cfg)     - deserialise a project / company JSON file
        into (scan_options, profiles). Handles both the v5 shape
        ({"scan": {...}, "profiles": [...]}) and the legacy v3/v4
        shape ({"rule": {"selected_bindings": [...], ...}}). Legacy
        entries get lifted into per-binding TaggingProfile objects so
        the new engine has something to drive on without manual
        intervention.

Unknown keys are ignored; missing keys fall back to defaults, so
older configs keep working when the schema grows.

This module imports only sibling Python (no Revit API), so it loads
under both IronPython 2.7 and CPython 3.11+.
"""

from bim_core.core import discipline_config
from annotation_qa.profiles import TaggingProfile, default_profile_for


# ---------------------------------------------------------------------------
# Scan-level options (everything else is per-profile).
# ---------------------------------------------------------------------------

DEFAULT_SCAN_OPTIONS = {
    # False = active-view scope (the BIM-friendly default).
    "whole_model":            False,
    # Which discipline the dropdown opens on for a fresh session.
    "default_discipline_key": "mechanical",
    # Project-specific extra clash blockers. List of BuiltInCategory
    # name strings (e.g. "OST_Furniture", "OST_Casework"). These are
    # unioned with the auto-derived baseline in ClashIndex so a
    # project can add bespoke blockers without editing code. Unknown
    # names are logged and skipped.
    "clash_extra_blocker_categories": [],
}


# ---------------------------------------------------------------------------
# Default starting profiles
# ---------------------------------------------------------------------------

def default_profiles():
    """Starting profile set for a fresh session - one row matching the
    v4 default (Mechanical / Ducts). Keeps the UI immediately
    actionable without an empty grid."""
    binding = discipline_config.find_binding("mechanical", "duct")
    if binding is None:
        return []
    return [default_profile_for("mechanical", binding)]


# ---------------------------------------------------------------------------
# Config IO
# ---------------------------------------------------------------------------

def from_config(cfg):
    """Merge a JSON config (possibly partial) into (scan_options, profiles).

    Accepts three shapes:

    1. v5 (current):
        {"scan": {"whole_model": false},
         "profiles": [
             {"discipline": "mechanical", "binding": "duct",
              "min_length_mm": 1500, ...},
             ...
         ]}

    2. v4 (multi-binding, global rule values):
        {"rule": {
             "selected_bindings": [["mechanical", "duct"],
                                   ["electrical", "cable_tray"]],
             "min_length_mm": 1000.0, "horizontal_only": true,
             "size_filters": {"cable_tray": {"width_mm_min": 100}, ...},
             "last_tag_per_category": {"cable_tray": 12345, ...},
             ...
         }}
       Each selected_bindings entry is hydrated into a TaggingProfile
       carrying the global rule values, the matching size_filters
       sub-dict, and the matching last_tag_per_category symbol id.

    3. v3 (single-cat):
        {"rule": {"category_key": "cable_tray",
                  "min_length_mm": 1000, ...}}
       Migrates to a single profile via
       discipline_config.find_binding_for_category.

    Unknown bindings (renamed in a later release) are dropped silently.
    Returns (scan_options, profiles) - profiles is a (possibly empty)
    list, scan_options is always a fresh dict.
    """
    scan = _deep_copy(DEFAULT_SCAN_OPTIONS)
    if not cfg or not isinstance(cfg, dict):
        return scan, default_profiles()

    if "profiles" in cfg or "scan" in cfg:
        profiles = _load_v5(cfg, scan)
        if not profiles:
            profiles = default_profiles()
        return scan, profiles

    if "rule" in cfg:
        profiles = _migrate_v4_or_v3(cfg["rule"] or {}, scan)
        if not profiles:
            profiles = default_profiles()
        return scan, profiles

    return scan, default_profiles()


# ---------------------------------------------------------------------------
# v5 loader
# ---------------------------------------------------------------------------

def _load_v5(cfg, scan):
    scan_block = cfg.get("scan") or {}
    if isinstance(scan_block, dict):
        for key in DEFAULT_SCAN_OPTIONS.keys():
            if key in scan_block:
                scan[key] = scan_block[key]

    raw_profiles = cfg.get("profiles") or []
    profiles = []
    for entry in raw_profiles:
        p = TaggingProfile.from_dict(entry)
        if p is not None:
            profiles.append(p)
    return profiles


# ---------------------------------------------------------------------------
# v4 / v3 migration
# ---------------------------------------------------------------------------

def _migrate_v4_or_v3(rule, scan):
    """Lift legacy global-options fields onto a per-binding profile set."""
    if "whole_model" in rule:
        scan["whole_model"] = bool(rule["whole_model"])

    selected = rule.get("selected_bindings") or []
    if not selected and rule.get("category_key"):
        # Single-cat v3: synthesize one binding.
        disc_key, binding = discipline_config.find_binding_for_category(
            rule["category_key"])
        if binding is not None:
            selected = [(disc_key, binding.key)]

    profiles = []
    size_cfg_all = rule.get("size_filters", {}) or {}
    tag_memory = rule.get("last_tag_per_category", {}) or {}

    for entry in selected:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        disc_key, sub_key = entry[0], entry[1]
        binding = discipline_config.find_binding(disc_key, sub_key)
        if binding is None:
            continue
        p = default_profile_for(disc_key, binding)
        # Lift the global rule values onto the per-profile defaults
        # (only when the field was actually set in the legacy config).
        if "min_length_mm" in rule:
            p.min_length_mm = rule["min_length_mm"]
        if "max_length_mm" in rule:
            p.max_length_mm = rule["max_length_mm"]
        if "horizontal_only" in rule:
            p.horizontal_only = bool(rule["horizontal_only"])
        if "vertical_only" in rule:
            p.vertical_only = bool(rule["vertical_only"])
        # Legacy v3/v4 configs had "orientation_tol_mm" (absolute Z
        # delta). That field was replaced with "orientation_tol_deg"
        # in 2026-05-22; ignore the legacy mm value and accept the
        # new key if a fresher config was saved over a v3/v4 layout.
        if ("orientation_tol_deg" in rule
                and rule["orientation_tol_deg"] is not None):
            p.orientation_tol_deg = rule["orientation_tol_deg"]
        if "skip_already_tagged" in rule:
            p.skip_already_tagged = bool(rule["skip_already_tagged"])
        if "add_leader" in rule:
            p.add_leader = bool(rule["add_leader"])
        # Per-category size filters: lift the relevant cat sub-dict
        # straight into the profile's flat size_filters slot.
        cat_size = size_cfg_all.get(p.category_key, {}) or {}
        for k, v in cat_size.items():
            if k in p.size_filters:
                p.size_filters[k] = v
        # Per-category tag memory.
        if p.category_key in tag_memory:
            p.tag_symbol_id = tag_memory[p.category_key]
        profiles.append(p)
    return profiles


# ---------------------------------------------------------------------------
# Deep copy for UI working state
# ---------------------------------------------------------------------------

def _deep_copy(obj):
    """Stdlib-only nested copy. Used by ui.py for the scan_options dict."""
    if isinstance(obj, dict):
        return {k: _deep_copy(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_copy(v) for v in obj]
    return obj
