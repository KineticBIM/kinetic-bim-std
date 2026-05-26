# -*- coding: utf-8 -*-
"""Plain classes describing a coordination run.

IronPython 2.7 / CPython 3 compatible - no type hints, no @dataclass,
no typing imports. The constructors accept keyword arguments matching
what @dataclass would have auto-generated, so call-site code (and
the test suite) stays the same.

Coordinate convention: all distances and locations are in **metres**
(SI), per the repo-wide convention in CLAUDE.md. parsing/
clash_detective.py converts at the boundary if a NW report uses
other units so consumers never have to branch.
"""

from __future__ import print_function, division, absolute_import


SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Element-level
# ---------------------------------------------------------------------------

class ClashElement(object):
    """One side of a clash - the NW item that participates in the pair.

    item_path is the slash-separated path Navisworks displays in the
    clash result ("Federated.nwf > MEC.nwc > Ducts > Round Duct..."),
    used verbatim in reports because that's how coordinators identify
    clashing items in NW itself.
    """

    def __init__(
        self,
        item_path="",
        source_file="",
        layer="",
        element_id=None,
        category=None,
        discipline=None,
        type_name=None,
    ):
        self.item_path = item_path
        self.source_file = source_file
        self.layer = layer
        self.element_id = element_id
        self.category = category
        self.discipline = discipline
        self.type_name = type_name

    def to_dict(self):
        return {
            "item_path": self.item_path,
            "source_file": self.source_file,
            "layer": self.layer,
            "element_id": self.element_id,
            "category": self.category,
            "discipline": self.discipline,
            "type_name": self.type_name,
        }


# ---------------------------------------------------------------------------
# Clash-level
# ---------------------------------------------------------------------------

class ClashResult(object):
    """One clash row inside a ClashTest.

    Mirrors the fields Navisworks exports in its ClashDetective XML
    report, plus a couple of platform-extension fields:

    - assigned_group: future-ready hook for issue-tracker integration.
      V1 always leaves this None; V2 (ACC) will populate it.
    - screenshot_path / viewpoint_path: filesystem paths to the
      exported assets, populated by the exporters after a successful
      coordination run.
    """

    def __init__(
        self,
        clash_id="",
        name="",
        status="",
        distance_m=None,
        description="",
        grid_location="",
        location_xyz_m=None,
        found_date=None,
        approved_date=None,
        approved_by=None,
        comments=None,
        item1=None,
        item2=None,
        assigned_group=None,
        viewpoint_path=None,
        screenshot_path=None,
    ):
        self.clash_id = clash_id
        self.name = name
        self.status = status
        self.distance_m = distance_m
        self.description = description
        self.grid_location = grid_location
        self.location_xyz_m = location_xyz_m
        self.found_date = found_date
        self.approved_date = approved_date
        self.approved_by = approved_by
        self.comments = comments if comments is not None else []
        self.item1 = item1 if item1 is not None else ClashElement()
        self.item2 = item2 if item2 is not None else ClashElement()
        self.assigned_group = assigned_group
        self.viewpoint_path = viewpoint_path
        self.screenshot_path = screenshot_path

    @property
    def discipline_pair(self):
        """`"MEC vs STR"` style key for grouping. None disciplines
        appear as "?" so a clash with one unclassified side is still
        groupable rather than dropping out of the count."""
        a = (self.item1.discipline or "?").upper()
        b = (self.item2.discipline or "?").upper()
        if a > b:
            a, b = b, a
        return "{0} vs {1}".format(a, b)


# ---------------------------------------------------------------------------
# Test-level
# ---------------------------------------------------------------------------

class ClashTest(object):
    """One saved Clash Detective test in the NWF."""

    def __init__(
        self,
        name="",
        test_type="",
        status="",
        last_run=None,
        tolerance_m=None,
        clashes=None,
    ):
        self.name = name
        self.test_type = test_type
        self.status = status
        self.last_run = last_run
        self.tolerance_m = tolerance_m
        self.clashes = clashes if clashes is not None else []

    @property
    def count(self):
        return len(self.clashes)

    def counts_by_status(self):
        out = {}
        for c in self.clashes:
            k = (c.status or "").lower() or "unknown"
            out[k] = out.get(k, 0) + 1
        return out


# ---------------------------------------------------------------------------
# Refresh-level
# ---------------------------------------------------------------------------

class RefreshReport(object):
    """Result of refreshing the federated model's linked NWC/NWD files.

    Populated by `model_refresh.refresher` after walking the federated
    model's link table. Empty lists are valid (e.g. a model with no
    links).
    """

    def __init__(
        self,
        refreshed=None,
        missing=None,
        outdated=None,
        failed=None,
        duration_s=0.0,
    ):
        self.refreshed = refreshed if refreshed is not None else []
        self.missing = missing if missing is not None else []
        self.outdated = outdated if outdated is not None else []
        self.failed = failed if failed is not None else []
        self.duration_s = duration_s

    @property
    def all_ok(self):
        return not (self.missing or self.failed)


# ---------------------------------------------------------------------------
# Run-level
# ---------------------------------------------------------------------------

class ClashRun(object):
    """One end-to-end coordination run.

    Captures everything a downstream consumer (reporting, history,
    UI) needs without having to touch Navisworks or re-parse XML.
    """

    def __init__(
        self,
        schema_version=SCHEMA_VERSION,
        project_number=None,
        project_name=None,
        nwf_path="",
        output_root="",
        run_date="",
        run_timestamp="",
        duration_s=0.0,
        tests=None,
        refresh_report=None,
        options=None,
        total=0,
        total_by_status=None,
        total_by_test=None,
        total_by_discipline_pair=None,
        delta_new=None,
        delta_resolved=None,
        previous_snapshot_date=None,
    ):
        self.schema_version = schema_version
        self.project_number = project_number
        self.project_name = project_name
        self.nwf_path = nwf_path
        self.output_root = output_root
        self.run_date = run_date
        self.run_timestamp = run_timestamp
        self.duration_s = duration_s
        self.tests = tests if tests is not None else []
        self.refresh_report = refresh_report
        self.options = options if options is not None else {}
        self.total = total
        self.total_by_status = total_by_status if total_by_status is not None else {}
        self.total_by_test = total_by_test if total_by_test is not None else {}
        self.total_by_discipline_pair = (
            total_by_discipline_pair if total_by_discipline_pair is not None else {})
        self.delta_new = delta_new
        self.delta_resolved = delta_resolved
        self.previous_snapshot_date = previous_snapshot_date

    def all_clashes(self):
        out = []
        for t in self.tests:
            out.extend(t.clashes)
        return out


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

# "Active" in management-summary terms = not resolved / approved.
# Adjusted by config.status_buckets at the orchestrator layer; this
# fallback set covers Navisworks' built-in statuses.
_DEFAULT_RESOLVED = set(["resolved", "approved"])
_DEFAULT_ACTIVE = set(["new", "active"])


def update_totals(run, status_buckets=None):
    """Populate the aggregate counters on the ClashRun in place.

    status_buckets, if provided, comes from the coordination config
    and overrides the default active/resolved sets. Shape:
        {"active": ["new", "active"], "resolved": ["resolved", "approved"]}
    Status names are matched case-insensitively.
    """
    by_status = {}
    by_test = {}
    by_pair = {}
    total = 0

    for test in run.tests:
        by_test[test.name] = test.count
        for c in test.clashes:
            total += 1
            key = (c.status or "").lower() or "unknown"
            by_status[key] = by_status.get(key, 0) + 1
            by_pair[c.discipline_pair] = by_pair.get(c.discipline_pair, 0) + 1

    run.total = total
    run.total_by_status = by_status
    run.total_by_test = by_test
    run.total_by_discipline_pair = by_pair


def active_count(run, status_buckets=None):
    """Sum of clashes in the configured 'active' status set."""
    active = _DEFAULT_ACTIVE
    if status_buckets and "active" in status_buckets:
        active = set([s.lower() for s in status_buckets["active"]])
    return sum(v for k, v in run.total_by_status.items() if k in active)


def resolved_count(run, status_buckets=None):
    """Sum of clashes in the configured 'resolved' status set."""
    resolved = _DEFAULT_RESOLVED
    if status_buckets and "resolved" in status_buckets:
        resolved = set([s.lower() for s in status_buckets["resolved"]])
    return sum(v for k, v in run.total_by_status.items() if k in resolved)
