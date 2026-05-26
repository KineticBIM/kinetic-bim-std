# -*- coding: utf-8 -*-
"""Weekly coordination snapshots.

Every coordination run writes a `weekly_snapshot.json` next to its
reports. V1 only WRITES these; V2 (planned) will ingest them into
SQLite or ACC Issues and render trend charts.

IronPython 2.7 / CPython 3 compatible.

Snapshot schema (schema_version 1.0)
------------------------------------

```jsonc
{
  "schema_version": "1.0",
  "project_number": "23001",
  "project_name": "Example Hospital",
  "nwf_path": "C:/.../Federated.nwf",
  "run_date": "2026-05-14",
  "run_timestamp": "2026-05-14T14:30:00",

  // Summary block for fast trend rendering.
  "summary": {
    "total": 482,
    "by_status": {"new": 41, "active": 418, "resolved": 23},
    "by_test": { ... },
    "by_discipline_pair": {"MEC vs STR": 312, ...}
  },

  // Per-clash detail.
  "clashes": [ ... ],

  // Delta vs previous snapshot, if available.
  "delta": {
    "previous_snapshot_date": "2026-05-07",
    "new": 41,
    "resolved": 23
  }
}
```

Bump SNAPSHOT_SCHEMA_VERSION on any schema-incompatible change.
"""

from __future__ import print_function, division, absolute_import

import io
import json
import os

from clash_coordination.data import models
from clash_coordination.output import folder_layout


SNAPSHOT_SCHEMA_VERSION = "1.0"
SNAPSHOT_FILENAME = "weekly_snapshot.json"


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def _clash_to_dict(c):
    """Compact, history-oriented dict for one clash."""
    return {
        "clash_id": c.clash_id,
        "name": c.name,
        "status": c.status,
        "discipline_pair": c.discipline_pair,
        "distance_m": c.distance_m,
        "grid_location": c.grid_location,
        "location_xyz_m": list(c.location_xyz_m) if c.location_xyz_m else None,
        "found_date": c.found_date,
        "approved_date": c.approved_date,
        "approved_by": c.approved_by,
        "assigned_group": c.assigned_group,
        "comments": list(c.comments),
        "item1": c.item1.to_dict(),
        "item2": c.item2.to_dict(),
    }


def _summary_for_run(run):
    by_test = {}
    for test in run.tests:
        by_test[test.name] = {
            "total": test.count,
            "by_status": test.counts_by_status(),
            "test_type": test.test_type,
            "last_run": test.last_run,
        }
    return {
        "total": run.total,
        "by_status": dict(run.total_by_status),
        "by_test": by_test,
        "by_discipline_pair": dict(run.total_by_discipline_pair),
    }


def _clash_to_test_map(run):
    """{clash_id: test_name} - lets us emit the per-clash test on
    each clash row without bloating the per-test block."""
    out = {}
    for test in run.tests:
        for c in test.clashes:
            if c.clash_id:
                out[c.clash_id] = test.name
    return out


def build_snapshot(run):
    """Return the snapshot dict for `run` without writing anything."""
    test_map = _clash_to_test_map(run)
    clashes = []
    for test in run.tests:
        for c in test.clashes:
            d = _clash_to_dict(c)
            d["test"] = test.name
            clashes.append(d)

    snapshot = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "project_number": run.project_number,
        "project_name": run.project_name,
        "nwf_path": run.nwf_path,
        "run_date": run.run_date,
        "run_timestamp": run.run_timestamp,
        "summary": _summary_for_run(run),
        "clashes": clashes,
    }

    if run.delta_new is not None or run.delta_resolved is not None:
        snapshot["delta"] = {
            "previous_snapshot_date": run.previous_snapshot_date,
            "new": run.delta_new,
            "resolved": run.delta_resolved,
        }

    snapshot["clash_to_test"] = test_map
    return snapshot


def write_snapshot(run, run_folder):
    """Write the snapshot for `run` into `run_folder` and return the
    absolute path of the written file."""
    snapshot = build_snapshot(run)
    path = os.path.join(run_folder, SNAPSHOT_FILENAME)
    # io.open with encoding works under both IronPython 2.7 and Py3.
    with io.open(path, "w", encoding="utf-8") as fh:
        # json.dumps -> unicode in Py2, str in Py3 - both fine for
        # io.open(encoding="utf-8").
        fh.write(json.dumps(snapshot, indent=2, ensure_ascii=False))
    return path


# ---------------------------------------------------------------------------
# Reading + deltas
# ---------------------------------------------------------------------------

class SnapshotVersionError(ValueError):
    """Raised when a snapshot's schema_version doesn't match what
    this code can read."""


def read_snapshot(path):
    """Read and minimally-validate a snapshot file."""
    with io.open(path, "r", encoding="utf-8") as fh:
        data = json.loads(fh.read())
    sv = data.get("schema_version")
    if sv != SNAPSHOT_SCHEMA_VERSION:
        raise SnapshotVersionError(
            "Snapshot at {0} has schema_version={1}, expected {2}".format(
                path, sv, SNAPSHOT_SCHEMA_VERSION))
    return data


def find_previous_snapshot(output_root, before_date):
    """Return the absolute path of the most recent snapshot strictly
    older than `before_date`, or None."""
    folder = folder_layout.previous_run_folder(output_root, before_date)
    if not folder:
        return None
    candidate = os.path.join(folder, SNAPSHOT_FILENAME)
    return candidate if os.path.isfile(candidate) else None


def _ids_by_status(snapshot):
    """Return `(active_ids, resolved_ids)` for a snapshot dict."""
    active = set()
    resolved = set()
    for c in snapshot.get("clashes", []):
        cid = c.get("clash_id")
        if not cid:
            continue
        status = (c.get("status") or "").lower()
        if status in ("resolved", "approved"):
            resolved.add(cid)
        else:
            active.add(cid)
    return active, resolved


def compute_deltas(current, previous_snapshot):
    """Return `(delta_new, delta_resolved)` of the current run vs the
    previous snapshot, or `(None, None)` if no previous snapshot."""
    if not previous_snapshot:
        return None, None

    prev_active, prev_resolved = _ids_by_status(previous_snapshot)
    prev_ids = prev_active | prev_resolved

    delta_new = 0
    delta_resolved = 0
    for c in current.all_clashes():
        cid = c.clash_id
        if not cid:
            continue
        status = (c.status or "").lower()
        is_resolved_now = status in ("resolved", "approved")
        was_resolved = cid in prev_resolved
        was_active = cid in prev_active

        if cid not in prev_ids:
            if not is_resolved_now:
                delta_new += 1
        else:
            if was_resolved and not is_resolved_now:
                delta_new += 1
            elif was_active and is_resolved_now:
                delta_resolved += 1

    return delta_new, delta_resolved


def annotate_run_with_deltas(run, output_root=None):
    """Look up the previous snapshot for this project's output_root,
    compute deltas, store them on the run in place."""
    root = output_root or run.output_root
    if not root or not run.run_date:
        return
    prev_path = find_previous_snapshot(root, run.run_date)
    if not prev_path:
        return
    try:
        prev = read_snapshot(prev_path)
    except (SnapshotVersionError, IOError, OSError, ValueError):
        return
    dn, dr = compute_deltas(run, prev)
    run.delta_new = dn
    run.delta_resolved = dr
    run.previous_snapshot_date = prev.get("run_date")
