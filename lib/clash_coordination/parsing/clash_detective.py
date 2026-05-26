# -*- coding: utf-8 -*-
"""Parse Navisworks ClashDetective XML report -> ClashRun.

The ClashDetective XML format has been stable in shape since
Navisworks 2014 but varies slightly between versions in whether
certain values live as XML *attributes* or as nested *elements*.
This parser tolerates both forms and converts all distances and
coordinates to SI metres at the boundary (per CLAUDE.md), so
downstream consumers never branch on units.

IronPython 2.7 / CPython 3 compatible.
"""

from __future__ import print_function, division, absolute_import

import os
from xml.etree import ElementTree as ET

from clash_coordination.data import models


# ---------------------------------------------------------------------------
# Unit conversion
# ---------------------------------------------------------------------------

_UNIT_TO_METRES = {
    "m": 1.0, "meter": 1.0, "meters": 1.0, "metre": 1.0, "metres": 1.0,
    "cm": 0.01, "centimeter": 0.01, "centimeters": 0.01,
    "mm": 0.001, "millimeter": 0.001, "millimeters": 0.001,
    "ft": 0.3048, "foot": 0.3048, "feet": 0.3048,
    "in": 0.0254, "inch": 0.0254, "inches": 0.0254,
    "yd": 0.9144, "yard": 0.9144, "yards": 0.9144,
    "km": 1000.0, "kilometer": 1000.0, "kilometers": 1000.0,
}


def _unit_factor(unit_str):
    """Return the multiplier that converts `unit_str` -> metres."""
    if not unit_str:
        return 1.0
    return _UNIT_TO_METRES.get(unit_str.strip().lower(), 1.0)


# ---------------------------------------------------------------------------
# Element helpers
# ---------------------------------------------------------------------------

def _attr(el, *names):
    """First non-empty attribute from `names` (case-insensitive).

    NW XML mixes camelCase, snake_case, and lowercase attribute names
    across versions; let callers list known variants.
    """
    for name in names:
        if name in el.attrib:
            v = el.attrib[name]
            if v != "":
                return v
        for k, v in el.attrib.items():
            if k.lower() == name.lower() and v != "":
                return v
    return None


def _child_text(el, *tags):
    """Text of the first child with one of `tags`. Case-insensitive."""
    if el is None:
        return None
    targets = set(t.lower() for t in tags)
    for child in el:
        if _tag(child).lower() in targets:
            text = (child.text or "").strip()
            return text or None
    return None


def _tag(el):
    """Tag with any namespace stripped. NW XML doesn't use namespaces
    in modern exports, but this is cheap insurance."""
    t = el.tag
    if "}" in t:
        t = t.split("}", 1)[1]
    return t


def _children_by_tag(el, tag):
    """All direct children whose tag (namespace-stripped) matches."""
    if el is None:
        return
    target = tag.lower()
    for child in el:
        if _tag(child).lower() == target:
            yield child


def _find_first(el, *tags):
    """First descendant (BFS-ish: direct children first) with one of
    `tags`. None if not found."""
    if el is None:
        return None
    targets = set(t.lower() for t in tags)
    for child in el:
        if _tag(child).lower() in targets:
            return child
    for child in el:
        found = _find_first(child, *tags)
        if found is not None:
            return found
    return None


def _to_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Discipline inference
# ---------------------------------------------------------------------------

def infer_discipline(hints, discipline_keywords=None):
    """Return the first discipline code whose keyword appears in any
    hint, or None. Hints are strings like the source NWC filename,
    layer name, item name, or category."""
    if not discipline_keywords:
        return None
    blob = " ".join(h for h in hints if h).lower()
    if not blob:
        return None
    for code, words in discipline_keywords.items():
        for w in words:
            if w and w.lower() in blob:
                return code
    return None


# ---------------------------------------------------------------------------
# Date helpers (NW serialises dates several ways)
# ---------------------------------------------------------------------------

def _parse_date(el):
    """Return an ISO-8601 date string, or None.

    NW emits dates two ways:
      <createddate>2026-05-14T14:30:00</createddate>           (recent)
      <createddate><day>14</day><month>5</month><year>2026</year>
                   <hour>14</hour><minute>30</minute>
                   <second>0</second></createddate>            (older)
    """
    if el is None:
        return None
    txt = (el.text or "").strip()
    if txt and txt[0].isdigit():
        return txt

    parts = {}
    for c in el:
        parts[_tag(c).lower()] = (c.text or "").strip()
    if not parts:
        return None
    try:
        y = int(parts.get("year", "0") or 0)
        m = int(parts.get("month", "0") or 0)
        d = int(parts.get("day", "0") or 0)
        if not (y and m and d):
            return None
        hh = int(parts.get("hour", "0") or 0)
        mm = int(parts.get("minute", "0") or 0)
        ss = int(parts.get("second", "0") or 0)
        return "{0:04d}-{1:02d}-{2:02d}T{3:02d}:{4:02d}:{5:02d}".format(
            y, m, d, hh, mm, ss)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Status normalisation
# ---------------------------------------------------------------------------

_STATUS_ALIASES = {
    "new": "new",
    "active": "active",
    "reviewed": "reviewed",
    "approved": "approved",
    "resolved": "resolved",
    "open": "active",
    "closed": "resolved",
    "fixed": "resolved",
}


def _normalise_status(s):
    if not s:
        return ""
    return _STATUS_ALIASES.get(s.strip().lower(), s.strip().lower())


# ---------------------------------------------------------------------------
# Per-clash parsing
# ---------------------------------------------------------------------------

def _parse_pathlink(pathlink):
    """Return `(item_path, source_file, layer)` from a <pathlink>
    block. The pathlink is an ordered list of <node> children that
    walk the federated tree:
        Federated.nwf > MEC.nwc > Ducts > Round Duct: 200mm
    By convention the second node is the source NWC/NWD; the last
    is the item name; everything in between is the layer hierarchy.
    """
    if pathlink is None:
        return "", "", ""
    nodes = []
    for c in _children_by_tag(pathlink, "node"):
        if c is not None:
            nodes.append((c.text or "").strip())
    nodes = [n for n in nodes if n]
    if not nodes:
        return "", "", ""

    item_path = " > ".join(nodes)
    source_file = nodes[1] if len(nodes) >= 2 else ""
    if len(nodes) >= 4:
        layer = " > ".join(nodes[2:-1])
    elif len(nodes) == 3:
        layer = nodes[2]
    else:
        layer = ""
    return item_path, source_file, layer


def _parse_clashobject(obj, discipline_keywords=None):
    pathlink = _find_first(obj, "pathlink")
    item_path, source_file, layer = _parse_pathlink(pathlink)

    # objectattribute -> element id / category / type
    element_id = None
    category = None
    type_name = None
    for attr in _children_by_tag(obj, "objectattribute"):
        name = (_attr(attr, "name") or "").lower()
        value = _attr(attr, "value") or ""
        if not name or not value:
            continue
        if "element id" in name or name == "id":
            element_id = value
        elif "category" in name:
            category = value
        elif "type" in name:
            if not type_name:
                type_name = value

    discipline = infer_discipline(
        [source_file, layer, item_path, category],
        discipline_keywords=discipline_keywords,
    )

    return models.ClashElement(
        item_path=item_path,
        source_file=source_file,
        layer=layer,
        element_id=element_id,
        category=category,
        discipline=discipline,
        type_name=type_name,
    )


def _parse_comments(parent):
    out = []
    if parent is None:
        return out
    for c in _children_by_tag(parent, "comment"):
        body = _child_text(c, "body")
        user = _child_text(c, "user")
        created = _parse_date(_find_first(c, "createddate"))
        if not body:
            continue
        prefix = ""
        if user or created:
            prefix = "[{0}{1}{2}] ".format(
                user or "",
                " " if (user and created) else "",
                created or "",
            )
        out.append(prefix + body)
    return out


def _parse_clashpoint(parent, unit_factor):
    if parent is None:
        return None
    pos = _find_first(parent, "pos3f", "pos3d", "pos")
    if pos is None:
        return None
    x = _to_float(_attr(pos, "x")) or 0.0
    y = _to_float(_attr(pos, "y")) or 0.0
    z = _to_float(_attr(pos, "z")) or 0.0
    return (x * unit_factor, y * unit_factor, z * unit_factor)


def _parse_clashresult(el, unit_factor, discipline_keywords=None):
    status = _attr(el, "resultstatus", "status") or _child_text(el, "resultstatus", "status")
    status = _normalise_status(status)

    distance_raw = _attr(el, "distance") or _child_text(el, "distance")
    distance = _to_float(distance_raw)
    if distance is not None:
        distance *= unit_factor

    grid_location = (_attr(el, "gridlocation") or
                     _child_text(el, "gridlocation") or "")
    description = (_attr(el, "description") or
                   _child_text(el, "description") or "")
    name = _attr(el, "name", "resultname") or _child_text(el, "resultname") or ""
    clash_id = _attr(el, "guid", "id") or ""

    found_date = _parse_date(_find_first(el, "createddate", "founddate"))
    approved_date = _parse_date(_find_first(el, "approveddate"))
    approved_by = _child_text(el, "approvedby")

    location_xyz = _parse_clashpoint(_find_first(el, "clashpoint"), unit_factor)

    objects_parent = _find_first(el, "clashobjects")
    items = []
    if objects_parent is not None:
        for obj in _children_by_tag(objects_parent, "clashobject"):
            items.append(_parse_clashobject(obj, discipline_keywords))
    while len(items) < 2:
        items.append(models.ClashElement())

    comments = _parse_comments(_find_first(el, "comments"))

    return models.ClashResult(
        clash_id=clash_id,
        name=name,
        status=status,
        distance_m=distance,
        description=description,
        grid_location=grid_location,
        location_xyz_m=location_xyz,
        found_date=found_date,
        approved_date=approved_date,
        approved_by=approved_by,
        comments=comments,
        item1=items[0],
        item2=items[1],
    )


# ---------------------------------------------------------------------------
# Per-test parsing
# ---------------------------------------------------------------------------

def _parse_clashtest(el, unit_factor, discipline_keywords=None):
    name = _attr(el, "name") or ""
    test_type = _attr(el, "test_type", "type") or ""
    status = _attr(el, "status") or ""
    tolerance = _to_float(_attr(el, "tolerance"))
    if tolerance is not None:
        tolerance *= unit_factor
    last_run = _parse_date(_find_first(el, "lastruntime", "lastrun"))

    clashes = []
    clashes_parent = _find_first(el, "clashes", "clashresults")
    if clashes_parent is not None:
        for c in _children_by_tag(clashes_parent, "clashresult"):
            clashes.append(_parse_clashresult(c, unit_factor, discipline_keywords))

    return models.ClashTest(
        name=name,
        test_type=test_type,
        status=status,
        last_run=last_run,
        tolerance_m=tolerance,
        clashes=clashes,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_clash_report(xml_source, discipline_keywords=None, only_tests=None):
    """Parse a ClashDetective XML report.

    `xml_source` is either a path to an XML file or an already-parsed
    ElementTree root (useful for tests).

    Returns a dict:
        {
            "units": "m" (always - converted at boundary),
            "filename": "Federated.nwf" (if NW included it),
            "tests": [ClashTest, ...],
        }

    `only_tests`, when given, filters the returned tests to those
    whose name appears in the list. Useful when the user ran a
    subset of saved tests; we still parse them all but report only
    the ones that were selected for this run.
    """
    if isinstance(xml_source, ET.Element):
        root = xml_source
    elif hasattr(xml_source, "read"):
        root = ET.parse(xml_source).getroot()
    elif isinstance(xml_source, str) and os.path.isfile(xml_source):
        root = ET.parse(xml_source).getroot()
    else:
        root = ET.fromstring(xml_source)

    unit_factor = _unit_factor(_attr(root, "units"))
    filename = _attr(root, "filename")

    tests_parent = _find_first(root, "clashtests")
    tests = []
    if tests_parent is not None:
        for t in _children_by_tag(tests_parent, "clashtest"):
            test = _parse_clashtest(t, unit_factor, discipline_keywords)
            if only_tests and test.name not in only_tests:
                continue
            tests.append(test)

    return {
        "units": "m",
        "filename": filename,
        "tests": tests,
    }


def populate_run(run, parsed):
    """Attach parsed tests to a ClashRun and update aggregate counters
    in place. Convenience wrapper for the orchestrator.
    """
    run.tests = list(parsed.get("tests", []))
    models.update_totals(run)
    return run
