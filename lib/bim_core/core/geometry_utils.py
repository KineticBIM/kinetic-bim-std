# -*- coding: utf-8 -*-
"""Geometry and unit helpers.

Wraps Revit's unit API across versions (post-2021 UnitTypeId / older
DisplayUnitType) and exposes the curve operations the rule engine and
tag placement code rely on: length, endpoints, midpoint, elevation
delta, horizontal-run, direction vector, and orientation tests.

All length-like values returned by this module are in millimetres
unless the function name says "_internal" (= Revit feet).
"""

from Autodesk.Revit.DB import BuiltInParameter, UnitUtils

try:
    # Revit 2021+
    from Autodesk.Revit.DB import UnitTypeId
    _HAS_UNIT_TYPE_ID = True
except ImportError:
    from Autodesk.Revit.DB import DisplayUnitType
    _HAS_UNIT_TYPE_ID = False


# --------------------------------------------------------------------- units

def mm_to_internal(mm):
    """Millimetres -> Revit internal feet."""
    if _HAS_UNIT_TYPE_ID:
        return UnitUtils.ConvertToInternalUnits(mm, UnitTypeId.Millimeters)
    return UnitUtils.ConvertToInternalUnits(mm, DisplayUnitType.DUT_MILLIMETERS)


def internal_to_mm(ft):
    """Revit internal feet -> millimetres."""
    if _HAS_UNIT_TYPE_ID:
        return UnitUtils.ConvertFromInternalUnits(ft, UnitTypeId.Millimeters)
    return UnitUtils.ConvertFromInternalUnits(ft, DisplayUnitType.DUT_MILLIMETERS)


# --------------------------------------------------------- geometry queries

def element_length_mm(element):
    """Length in mm, or None if the element has no measurable curve."""
    p = element.get_Parameter(BuiltInParameter.CURVE_ELEM_LENGTH)
    if p is not None:
        return internal_to_mm(p.AsDouble())
    loc = getattr(element, "Location", None)
    if loc is None or not hasattr(loc, "Curve"):
        return None
    return internal_to_mm(loc.Curve.Length)


def element_endpoints(element):
    """(start_xyz, end_xyz) or (None, None) for non-curve elements."""
    loc = getattr(element, "Location", None)
    if loc is None or not hasattr(loc, "Curve"):
        return None, None
    curve = loc.Curve
    return curve.GetEndPoint(0), curve.GetEndPoint(1)


def element_midpoint(element):
    """XYZ at curve parameter 0.5, or None if no LocationCurve."""
    loc = getattr(element, "Location", None)
    if loc is None or not hasattr(loc, "Curve"):
        return None
    return loc.Curve.Evaluate(0.5, True)


def element_origin(element):
    """Unified placement point for both LocationPoint and LocationCurve
    elements.

    - LocationPoint  -> the point itself (used for equipment, fixtures,
                        accessories, fittings, sprinklers, devices).
    - LocationCurve  -> the curve midpoint (used for cable trays,
                        conduits, ducts, pipes).
    - Anything else  -> None.

    This is what tagging_engine.place_tag calls regardless of category:
    one helper, two geometries, no branching at the caller.
    """
    loc = getattr(element, "Location", None)
    if loc is None:
        return None
    # Point-based first - some elements have both, but Point is canonical
    # for LocationPoint-derived elements.
    try:
        pt = getattr(loc, "Point", None)
        if pt is not None:
            return pt
    except Exception:
        pass
    if hasattr(loc, "Curve") and loc.Curve is not None:
        return loc.Curve.Evaluate(0.5, True)
    return None


def elevation_difference_mm(element):
    """Absolute Z delta between curve endpoints, in mm. None for non-curve."""
    p0, p1 = element_endpoints(element)
    if p0 is None or p1 is None:
        return None
    return internal_to_mm(abs(p1.Z - p0.Z))


def horizontal_run_mm(element):
    """XY-plane distance between curve endpoints, in mm. None for non-curve."""
    p0, p1 = element_endpoints(element)
    if p0 is None or p1 is None:
        return None
    dx = p1.X - p0.X
    dy = p1.Y - p0.Y
    return internal_to_mm((dx * dx + dy * dy) ** 0.5)


def slope_from_horizontal_deg(element):
    """Angle of the element's straight-line endpoint vector from the XY
    plane, in degrees. 0 = perfectly horizontal, 90 = perfectly
    vertical. None for non-curve elements and for degenerate zero-
    length curves.

    Calculated from straight-line endpoints rather than total curve
    length so a slightly-curved run reads as the slope between its
    ends, not as the average tangent angle.
    """
    import math
    p0, p1 = element_endpoints(element)
    if p0 is None or p1 is None:
        return None
    dx = p1.X - p0.X
    dy = p1.Y - p0.Y
    dz = p1.Z - p0.Z
    horizontal_run = (dx * dx + dy * dy) ** 0.5
    vertical_run = abs(dz)
    if horizontal_run < 1e-12 and vertical_run < 1e-12:
        return None
    return math.degrees(math.atan2(vertical_run, horizontal_run))


def direction_vector(element):
    """Normalised XYZ direction of the curve, or None.

    Returned object is a Revit XYZ; magnitude == 1 when the curve has
    non-zero length.
    """
    p0, p1 = element_endpoints(element)
    if p0 is None or p1 is None:
        return None
    v = p1 - p0
    length = v.GetLength()
    if length <= 0:
        return None
    return v.Normalize()


# --------------------------------------------------------- orientation tests

def is_horizontal(element, tolerance_mm=50.0):
    """True when the curve's elevation delta is within tolerance_mm.

    50mm is the spec default - tight enough to reject risers, loose enough
    to keep mostly-flat trapeze drops in scope.
    """
    dz = elevation_difference_mm(element)
    if dz is None:
        return False
    return dz <= tolerance_mm


def is_vertical(element, tolerance_mm=50.0):
    """True when the curve's XY-plane run is within tolerance_mm.

    A vertical riser has near-zero horizontal travel; the same tolerance
    is used as for is_horizontal so the two tests are visually symmetric
    and can share an "Elevation tolerance" UI control.
    """
    dxy = horizontal_run_mm(element)
    if dxy is None:
        return False
    return dxy <= tolerance_mm
