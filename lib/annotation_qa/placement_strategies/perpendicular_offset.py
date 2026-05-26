# -*- coding: utf-8 -*-
"""PerpendicularOffsetStrategy - tag offset perpendicular to a linear
host's run, in the view plane.

Used when profile.placement_mode == "adjacent", the host has a
LocationCurve (geometry_kind == "linear"), and preferred_side ==
"auto". For explicit "above"/"below"/"left"/"right" choices the
factory routes to CardinalOffsetStrategy instead, since cardinal
directions are view-plane axes that don't depend on the host's run.

Algorithm:
    1. Take the host's run direction (geometry_utils.direction_vector).
       Bails out for curves with no direction vector - the factory
       falls back to OnElementStrategy.
    2. Project that 3D direction onto the view plane by subtracting
       its component along view.ViewDirection. If the projected
       tangent is effectively zero (run is perpendicular to the view,
       e.g. a riser shown in plan), yield nothing - the engine falls
       back to OnElementStrategy.
    3. Compute the in-plane perpendicular: perp = view_normal x tangent.
    4. Yield candidates at +/- offset_mm and +/- 1.5x offset_mm. The
       1.5x step gives the clash loop somewhere to escape to in dense
       views without expanding the search space so much that placements
       end up far from their hosts.

Arc-host curves use the straight endpoint-to-endpoint vector via
geometry_utils.direction_vector. Tag placement on arcs is rare in
typical MEP work; if it becomes an issue, switch to
curve.ComputeDerivatives(0.5, True).BasisX.
"""

from bim_core.core import geometry_utils

from annotation_qa.placement_strategies.base import PlacementStrategy


# Below this projected-tangent length (in Revit internal feet) we
# treat the run as perpendicular to the view and bail out. 1e-6 ft is
# ~0.3 microns - well below any geometry tolerance Revit cares about.
_MIN_PROJECTED_TANGENT = 1.0e-6

# Distance multipliers tried, in order. The clash loop walks these as
# fallbacks; pure preference order is (+1x, -1x, +1.5x, -1.5x).
_DISTANCE_MULTIPLIERS = (1.0, 1.5)


class PerpendicularOffsetStrategy(PlacementStrategy):

    key = "perpendicular_offset"
    label = "Perpendicular offset"

    @classmethod
    def applies_to(cls, category_key):
        from bim_core.core import category_config
        cfg = category_config.get_safe(category_key)
        return cfg is not None and cfg.geometry_kind == "linear"

    def propose_positions(self, view, element, profile):
        origin = geometry_utils.element_origin(element)
        if origin is None:
            return

        tangent = geometry_utils.direction_vector(element)
        if tangent is None:
            return

        perp = _view_plane_perpendicular(view, tangent)
        if perp is None:
            return

        offset_ft = geometry_utils.mm_to_internal(profile.offset_mm)

        for mult in _DISTANCE_MULTIPLIERS:
            step = offset_ft * mult
            yield origin + perp.Multiply(step)
            yield origin + perp.Multiply(-step)


def _view_plane_perpendicular(view, tangent):
    """Return the in-view perpendicular to tangent as a normalised XYZ,
    or None if tangent has no projection onto the view plane.

    view_normal x tangent_in_view gives a vector that is (a) in the
    view plane (perpendicular to view_normal) and (b) perpendicular to
    the tangent. Exactly what we want for "step sideways off the run".
    """
    view_normal = view.ViewDirection
    along_normal = view_normal.Multiply(tangent.DotProduct(view_normal))
    in_plane = tangent - along_normal
    if in_plane.GetLength() < _MIN_PROJECTED_TANGENT:
        return None
    in_plane = in_plane.Normalize()
    perp = view_normal.CrossProduct(in_plane)
    if perp.GetLength() < _MIN_PROJECTED_TANGENT:
        return None
    return perp.Normalize()
