# -*- coding: utf-8 -*-
"""Orientation filter rules: horizontal-only / vertical-only.

Both rules use an angle-from-horizontal test rather than an absolute
elevation delta, so the tolerance scales with run length. A 5m tray
drifting by 100mm reads as ~1.1deg (well within "horizontal"); a
200mm fitting drifting by 100mm reads as ~27deg (correctly steep).

The two rules are mutually exclusive at the UI level; the rule
engine does not enforce that - build_pipeline only adds one or the
other.
"""

from bim_core.core import geometry_utils
from bim_core.rules_engine.base import Rule


def _cached_slope_deg(element, context):
    slope = context.get("slope_from_horizontal_deg", "__unset__")
    if slope == "__unset__":
        slope = geometry_utils.slope_from_horizontal_deg(element)
        context["slope_from_horizontal_deg"] = slope
    return slope


class HorizontalRule(Rule):
    """Pass when the element's slope from horizontal is <= tolerance.

    tolerance_deg = 0   -> perfectly flat only.
    tolerance_deg = 15  -> default. Catches typical MEP coordination
                           drift (a few degrees) while excluding
                           obvious transitions and risers.
    tolerance_deg = 90  -> permissive (always passes for any non-
                           degenerate curve).
    """

    name = "horizontal_only"

    def __init__(self, tolerance_deg=15.0):
        self.tolerance_deg = float(tolerance_deg)

    def passes(self, element, context):
        slope = _cached_slope_deg(element, context)
        if slope is None:
            return False, "no curve geometry"
        if slope <= self.tolerance_deg:
            return True, None
        return False, ("not horizontal ({0:.1f}deg slope > {1:.1f}deg)"
                       .format(slope, self.tolerance_deg))


class VerticalRule(Rule):
    """Pass when the element is within tolerance of vertical.

    tolerance_deg here measures how far the element tilts AWAY from
    vertical (90deg). tolerance_deg = 15 means slope_from_horizontal
    must be >= 75deg.
    """

    name = "vertical_only"

    def __init__(self, tolerance_deg=15.0):
        self.tolerance_deg = float(tolerance_deg)

    def passes(self, element, context):
        slope = _cached_slope_deg(element, context)
        if slope is None:
            return False, "no curve geometry"
        tilt_from_vertical = 90.0 - slope
        if tilt_from_vertical <= self.tolerance_deg:
            return True, None
        return False, ("not vertical ({0:.1f}deg from vertical > {1:.1f}deg)"
                       .format(tilt_from_vertical, self.tolerance_deg))
