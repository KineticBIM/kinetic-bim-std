# -*- coding: utf-8 -*-
"""Coordination profile load/save.

Three-tier lookup, matching the existing `audit_engine.runner`
convention:

  1. `<output_root>/coord_config.json`
  2. `<extension>/lib/clash_coordination/projects/<project_number>.json`
  3. `<extension>/lib/clash_coordination/configs/default.json`

`load_profile()` returns `(profile_dict, source_path)`.

IronPython 2.7 / CPython 3 compatible.
"""

from __future__ import print_function, division, absolute_import

import datetime
import io
import json
import os


PROFILE_SCHEMA_VERSION = "1.0"
DEFAULT_CONFIG_FILENAME = "default.json"
PROJECT_OVERRIDE_FILENAME = "coord_config.json"
RECENT_OUTPUT_FILENAME = "coordination_recent.json"


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _module_dir():
    return os.path.dirname(os.path.abspath(__file__))


def configs_dir():
    return os.path.join(_module_dir(), "configs")


def projects_dir():
    return os.path.join(_module_dir(), "projects")


def _project_number_from_doc(doc):
    """Best-effort project number from a Revit Document. None if doc
    is None, the doc has no ProjectInformation, or the param isn't
    set. Guarded for runs outside Revit (tests, headless runs)."""
    if doc is None:
        return None
    try:
        from Autodesk.Revit.DB import BuiltInParameter  # type: ignore
    except ImportError:
        return None
    try:
        pi = doc.ProjectInformation
        p = pi.get_Parameter(BuiltInParameter.PROJECT_NUMBER)
        return (p.AsString() if p else None) or None
    except Exception:
        return None


def candidate_paths(doc=None, output_root=None, explicit_project_number=None):
    """Return the three lookup paths in priority order."""
    paths = []
    if output_root:
        paths.append(os.path.join(output_root, PROJECT_OVERRIDE_FILENAME))
    proj_num = explicit_project_number or _project_number_from_doc(doc)
    if proj_num:
        paths.append(os.path.join(projects_dir(), "{0}.json".format(proj_num)))
    paths.append(os.path.join(configs_dir(), DEFAULT_CONFIG_FILENAME))
    return paths


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def _deep_merge(base, over):
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _read_json(path):
    with io.open(path, "r", encoding="utf-8") as fh:
        return json.loads(fh.read())


def _write_json(path, data):
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(data, indent=2, ensure_ascii=False))


def load_profile(doc=None, output_root=None, explicit_project_number=None):
    """Load and return (profile, source_path)."""
    default_path = os.path.join(configs_dir(), DEFAULT_CONFIG_FILENAME)
    if os.path.isfile(default_path):
        profile = _read_json(default_path)
    else:
        profile = {}

    source_path = default_path if os.path.isfile(default_path) else None

    paths = candidate_paths(
        doc=doc, output_root=output_root,
        explicit_project_number=explicit_project_number,
    )
    higher = [p for p in paths if p != default_path]
    # Layer in reverse so highest priority ends up on top.
    for p in reversed(higher):
        if os.path.isfile(p):
            overlay = _read_json(p)
            profile = _deep_merge(profile, overlay)
            source_path = p

    return profile, source_path


def list_committed_projects():
    """Return `[(project_number, path), ...]` for every JSON in
    `projects/` whose filename looks like a project number."""
    out = []
    folder = projects_dir()
    if not os.path.isdir(folder):
        return out
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json"):
            continue
        if name.startswith("_"):
            continue
        out.append((os.path.splitext(name)[0], os.path.join(folder, name)))
    return out


# ---------------------------------------------------------------------------
# Save - per-output-folder override
# ---------------------------------------------------------------------------

def write_project_override(output_root, profile_updates):
    """Write a partial profile to `<output_root>/coord_config.json`."""
    if not output_root:
        raise ValueError("output_root is required")
    if not os.path.isdir(output_root):
        os.makedirs(output_root)
    path = os.path.join(output_root, PROJECT_OVERRIDE_FILENAME)
    existing = {}
    if os.path.isfile(path):
        try:
            existing = _read_json(path)
        except (IOError, OSError, ValueError):
            existing = {}
    merged = _deep_merge(existing, profile_updates)
    merged.setdefault("schema_version", PROFILE_SCHEMA_VERSION)
    _write_json(path, merged)
    return path


# ---------------------------------------------------------------------------
# Recent-output tracking - for the pushbutton shift-click affordance
# ---------------------------------------------------------------------------

def _recent_path(doc=None):
    """Where we record the most recent coord run. Lives in the Revit
    project folder if we have one, otherwise the user's home dir."""
    base = None
    try:
        if doc is not None and doc.PathName:
            base = os.path.join(os.path.dirname(doc.PathName), ".bim")
    except Exception:
        base = None
    if base is None:
        base = os.path.join(os.path.expanduser("~"), ".bim")
    if not os.path.isdir(base):
        os.makedirs(base)
    return os.path.join(base, RECENT_OUTPUT_FILENAME)


def record_run(doc, output_root, run_folder):
    """Persist `(output_root, run_folder)` for later shift-click
    "open last output folder". Best-effort - swallows failure."""
    try:
        path = _recent_path(doc)
        payload = {
            "output_root": output_root,
            "run_folder": run_folder,
            "recorded_at": datetime.datetime.now().isoformat(),
        }
        _write_json(path, payload)
    except Exception:
        pass


def last_output_folder(doc):
    """Most recently recorded coord run folder, or None."""
    try:
        path = _recent_path(doc)
        if not os.path.isfile(path):
            return None
        payload = _read_json(path)
        return payload.get("run_folder") or payload.get("output_root")
    except Exception:
        return None
