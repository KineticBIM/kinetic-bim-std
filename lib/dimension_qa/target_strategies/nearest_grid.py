# -*- coding: utf-8 -*-
"""NearestGridStrategy - dim end target at the nearest perpendicular
grid line.

Algorithm:
    1. Collect every Grid visible in the supplied view.
    2. Filter to grids whose direction is roughly PERPENDICULAR to the
       element's run direction. Dim'ing a horizontal pipe to a parallel
       grid line is meaningless; we want the perpendicular ones.
    3. Of the perpendicular grids, pick the one whose curve is closest
       (perpendicular distance) to the element_anchor.
    4. Return Reference(grid) + the foot of the perpendicular from
       element_anchor onto the grid as anchor_xyz.

Returns (None, reason) when no grid is suitably perpendicular - the
report attributes the skip to "no perpendicular grid in view".
"""

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    Grid,
    Reference,
    XYZ,
)

from bim_core.core import geometry_utils

from dimension_qa.target_strategies.base import ReferenceTargetStrategy


# Grids whose direction is more parallel than this (i.e. dot product
# of normalised directions > _PARALLEL_TOL) are skipped. 0.3 ~ within
# 17 degrees of parallel.
_PARALLEL_TOL = 0.3


class NearestGridStrategy(ReferenceTargetStrategy):

    key = "nearest_grid"
    label = "Nearest Grid"

    def get_target(self, doc, view, element, element_anchor):
        elem_dir = geometry_utils.direction_vector(element)
        if elem_dir is None:
            return None, "element has no direction vector"

        grids = list(FilteredElementCollector(doc, view.Id).OfClass(Grid))
        if not grids:
            return None, "no grids visible in view"

        best = None
        best_dist = float("inf")
        best_foot = None
        for grid in grids:
            line = _grid_line(grid)
            if line is None:
                continue
            grid_dir = _line_direction(line)
            if grid_dir is None:
                continue
            # Skip grids that aren't perpendicular enough to the
            # element run.
            if abs(elem_dir.DotProduct(grid_dir)) > _PARALLEL_TOL:
                continue
            foot, dist = _project_point_onto_line(element_anchor, line)
            if foot is None:
                continue
            if dist < best_dist:
                best = grid
                best_dist = dist
                best_foot = foot

        if best is None:
            return None, "no perpendicular grid in view"

        try:
            ref = Reference(best)
        except Exception as exc:
            return None, "Reference(grid) failed: {0}".format(exc)
        return ref, best_foot


# ---------------------------------------------------------------------------
# Grid geometry helpers
# ---------------------------------------------------------------------------

def _grid_line(grid):
    """Get the grid's curve as a Line. Falls back to None for arc
    grids (we don't dim to arc grids in v1; pipework doesn't usually
    intersect them on plan in a way that produces clean dims)."""
    try:
        curve = grid.Curve
    except Exception:
        return None
    if curve is None:
        return None
    # Distinguish a Line from an Arc - Line has IsBound and a constant
    # direction; we do a sloppy check by trying GetEndPoint(0) +
    # GetEndPoint(1) and reading the type name.
    try:
        kind = type(curve).__name__
    except Exception:
        kind = ""
    if kind != "Line":
        return None
    return curve


def _line_direction(line):
    try:
        p0 = line.GetEndPoint(0)
        p1 = line.GetEndPoint(1)
    except Exception:
        return None
    v = p1 - p0
    if v.GetLength() < 1e-9:
        return None
    return v.Normalize()


def _project_point_onto_line(point, line):
    """Return (foot_xyz, distance) - foot is the perpendicular
    projection of point onto line; distance is the 3D distance from
    point to foot."""
    try:
        origin = line.GetEndPoint(0)
        direction = _line_direction(line)
        if direction is None:
            return None, None
        v = point - origin
        t = v.DotProduct(direction)
        foot = origin + direction.Multiply(t)
        return foot, point.DistanceTo(foot)
    except Exception:
        return None, None
