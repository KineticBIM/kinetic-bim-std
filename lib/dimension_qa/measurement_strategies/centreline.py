# -*- coding: utf-8 -*-
"""CentrelineStrategy - the universal default.

WHY THIS USES AN END-CAP FACE, NOT Reference(element):
    Revit's NewDimension API requires the dim line to be perpendicular
    to every reference. For two LINE references whose directions are
    perpendicular to each other - the v1 default of "linear MEP run +
    perpendicular grid" - no aligned dim line satisfies that
    constraint, and Revit raises "Direction of dimension is invalid".
    A FACE reference's compatibility rule is "dim line PARALLEL to
    face normal" instead. So returning a face whose normal is along
    the element's run direction (i.e. an end cap) makes face + grid
    refs compatible - the dim line ends up along the run direction,
    perpendicular to the grid, and the dim succeeds.

    Practically the dim then reads "distance from cable tray end to
    grid", which is what BIM documentation usually wants for tray-to-
    perpendicular-grid annotation. (The "distance from centreline to
    perpendicular grid" isn't a meaningful single number anyway - the
    two lines cross or pass close in plan.)

Falls back to Reference(element) when no end-cap face is extractable
(curved/arc cable trays, exotic family geometry). The legacy
Reference(element) path will fail at NewDimension for perpendicular
targets but the engine surfaces the failure cleanly per record.
"""

from Autodesk.Revit.DB import Options, Reference, Solid, UV

from bim_core.core import geometry_utils

from dimension_qa.measurement_strategies.base import (
    MeasurementReferenceStrategy,
)


# Faces whose normal is within this dot-product threshold of the run
# direction count as end caps. cos(45deg) ~ 0.7 - generous enough to
# tolerate slightly off-axis caps on radius bends, tight enough to
# exclude the side faces.
_END_CAP_ALIGNMENT = 0.7


class CentrelineStrategy(MeasurementReferenceStrategy):

    key = "centreline"
    label = "Centreline"

    @classmethod
    def applies_to(cls, category_key):
        return category_key in ("cable_tray", "conduit", "duct",
                                "flex_duct", "pipe")

    def get_reference(self, doc, view, element, target_anchor=None):
        ref, anchor, err = _end_cap_face(element, view, target_anchor)
        if ref is not None:
            return ref, anchor

        # Fallback: legacy line ref. Works when the target reference is
        # also a line ref AND parallel to the element (none such targets
        # ship in v1 - the only target is NearestGrid which is
        # perpendicular by design).
        midpoint = geometry_utils.element_midpoint(element)
        if midpoint is None:
            return None, "no curve geometry; {0}".format(err or "")
        try:
            return Reference(element), midpoint
        except Exception as exc:
            return None, "Reference(element) failed: {0}".format(exc)


# ---------------------------------------------------------------------------
# End-cap face extraction
# ---------------------------------------------------------------------------

def _end_cap_face(element, view, target_anchor):
    """Find the planar face whose normal is most aligned with the
    element's run direction. When target_anchor is supplied, ties
    break in favour of the face whose centre is CLOSEST to the target
    so the dim measures the smaller of the two possible end-to-grid
    distances.

    Returns (Reference, anchor_xyz, None) on success or
    (None, None, error_string) on failure.
    """
    run_dir = geometry_utils.direction_vector(element)
    if run_dir is None:
        return None, None, "no run direction"

    opts = Options()
    opts.ComputeReferences = True
    opts.IncludeNonVisibleObjects = False
    if view is not None:
        opts.View = view

    geom = element.get_Geometry(opts)
    if geom is None:
        return None, None, "no geometry"

    candidates = []  # (alignment_score, distance_to_target, face, centre)
    for go in geom:
        for face in _iter_planar_faces(go):
            try:
                normal = face.FaceNormal
            except Exception:
                continue
            score = abs(normal.DotProduct(run_dir))
            if score < _END_CAP_ALIGNMENT:
                continue  # not an end cap
            centre = _face_centre(face)
            if centre is None:
                continue
            tie = (centre.DistanceTo(target_anchor)
                   if target_anchor is not None else 0.0)
            candidates.append((score, tie, face, centre))

    if not candidates:
        return None, None, "no end-cap face"

    # Strongest alignment first; among ties, the cap closest to the
    # target. (Negate alignment so sort ascending puts strongest first.)
    candidates.sort(key=lambda c: (-c[0], c[1]))
    _, _, best_face, anchor = candidates[0]
    if best_face.Reference is None:
        return None, None, ("end-cap face has no Reference - "
                            "Options.ComputeReferences off?")
    return best_face.Reference, anchor, None


def _iter_planar_faces(geometry_obj):
    """Yield planar faces of a GeometryObject, recursing into instance
    geometry. Curved faces (cylinders, etc) are skipped because end-cap
    detection compares face normals."""
    if isinstance(geometry_obj, Solid):
        for face in geometry_obj.Faces:
            try:
                _ = face.FaceNormal  # raises for non-planar faces
                yield face
            except Exception:
                continue
        return
    if hasattr(geometry_obj, "GetInstanceGeometry"):
        for sub in geometry_obj.GetInstanceGeometry():
            for face in _iter_planar_faces(sub):
                yield face


def _face_centre(face):
    try:
        bbox = face.GetBoundingBox()
        u_mid = (bbox.Min.U + bbox.Max.U) * 0.5
        v_mid = (bbox.Min.V + bbox.Max.V) * 0.5
        return face.Evaluate(UV(u_mid, v_mid))
    except Exception:
        return None
