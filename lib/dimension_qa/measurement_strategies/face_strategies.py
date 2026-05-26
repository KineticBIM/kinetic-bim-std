# -*- coding: utf-8 -*-
"""Face-based measurement reference strategies.

A handful of strategy classes share most of their logic - they all
walk an element's solid geometry, pick the face whose normal matches
a desired direction (top / bottom / outside / inside), and return
that face's Reference. The differences are:
    - which axis the face normal must align to
    - which sign of that axis is acceptable (top vs bottom)
    - which categories the strategy applies to (rectangular elements
      have flat side faces; round ones don't)

Round elements (conduit, pipe, flex_duct) only have a single curved
side face. For these, "Top of Pipe" / "Bottom of Pipe" / "Invert
Level" are all geometrically valid concepts but Revit doesn't expose
distinct face references for them - you'd be dimensioning to the
same cylinder face. v1 fails round-element non-centreline strategies
explicitly with a clear reason; v2 may add virtual reference planes
or sketch-line workarounds.

The face walk requires Options.ComputeReferences = True - without it
face.Reference returns None and dimensioning fails with a confusing
error. The helper module enforces that.
"""

from Autodesk.Revit.DB import Options, Solid, XYZ

from dimension_qa.measurement_strategies.base import (
    MeasurementReferenceStrategy,
)


_RECTANGULAR_LINEAR = ("cable_tray", "duct")
_ROUND_LINEAR = ("conduit", "flex_duct", "pipe")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _geometry_options(view):
    """Build Options with ComputeReferences=True so face.Reference
    returns a usable Reference (not None)."""
    opts = Options()
    opts.ComputeReferences = True
    opts.IncludeNonVisibleObjects = False
    if view is not None:
        opts.View = view
    return opts


def _iter_solid_faces(element, view):
    """Yield (face, normal_xyz_or_None) for every face on the element's
    geometry. Normal is the face's normal at its centre when the face
    is planar; None for curved faces (cylinder side, etc)."""
    geom = element.get_Geometry(_geometry_options(view))
    if geom is None:
        return
    for go in geom:
        for face in _faces_of(go):
            normal = _planar_normal(face)
            yield face, normal


def _faces_of(geometry_obj):
    """Yield faces of a GeometryObject. Recurses into instances /
    geometry sets to handle nested family geometry."""
    if isinstance(geometry_obj, Solid):
        for face in geometry_obj.Faces:
            yield face
        return
    # GeometryInstance - dig into the symbol geometry.
    if hasattr(geometry_obj, "GetInstanceGeometry"):
        for sub in geometry_obj.GetInstanceGeometry():
            for face in _faces_of(sub):
                yield face


def _planar_normal(face):
    """Return the face's normal at its centre, or None for curved
    faces. We only use planar faces for top/bottom/side identification
    in v1."""
    try:
        # PlanarFace exposes FaceNormal; CylindricalFace etc. don't.
        return face.FaceNormal
    except Exception:
        return None


def _pick_face_by_normal(element, view, axis_test):
    """Pick the planar face whose normal best satisfies `axis_test`.

    axis_test(normal_xyz) -> (matches: bool, score: float)
        matches: True if the face is a candidate
        score: lower = better (engine prefers the closest match)

    Returns (face, anchor_xyz) or (None, "reason").
    """
    best = None
    best_score = float("inf")
    for face, normal in _iter_solid_faces(element, view):
        if normal is None:
            continue
        ok, score = axis_test(normal)
        if not ok:
            continue
        if score < best_score:
            best_score = score
            best = face
    if best is None:
        return None, "no planar face matched"
    try:
        anchor = _face_centre(best)
    except Exception:
        return None, "could not evaluate face centre"
    if best.Reference is None:
        return None, "face has no Reference (Options.ComputeReferences off?)"
    return (best.Reference, anchor)


def _face_centre(face):
    """Return the face's geometric centre in model coordinates.

    Uses the BoundingBoxUV midpoint, which is robust across PlanarFace
    + most curved face types. Evaluate raises for non-parametric faces;
    catch and skip via the calling _pick_face_by_normal loop.
    """
    bbox = face.GetBoundingBox()
    u_mid = (bbox.Min.U + bbox.Max.U) * 0.5
    v_mid = (bbox.Min.V + bbox.Max.V) * 0.5
    from Autodesk.Revit.DB import UV
    return face.Evaluate(UV(u_mid, v_mid))


# ---------------------------------------------------------------------------
# Concrete strategies
# ---------------------------------------------------------------------------

class TopFaceStrategy(MeasurementReferenceStrategy):
    """Top of cable tray / duct (face whose normal points roughly +Z)."""

    key = "top"
    label = "Top"

    @classmethod
    def applies_to(cls, category_key):
        return category_key in _RECTANGULAR_LINEAR + _ROUND_LINEAR

    def get_reference(self, doc, view, element, target_anchor=None):
        if _is_round(element):
            return None, ("'Top of {0}' requires a rectangular section; "
                          "this element is round - use Centreline or "
                          "Outside Face instead.".format(_label(element)))
        return _pick_face_by_normal(
            element, view, lambda n: (n.Z > 0.7, -n.Z))


class BottomFaceStrategy(MeasurementReferenceStrategy):
    """Bottom of cable tray / duct (face whose normal points roughly -Z)."""

    key = "bottom"
    label = "Bottom"

    @classmethod
    def applies_to(cls, category_key):
        return category_key in _RECTANGULAR_LINEAR + _ROUND_LINEAR

    def get_reference(self, doc, view, element, target_anchor=None):
        if _is_round(element):
            return None, ("'Bottom of {0}' requires a rectangular section; "
                          "this element is round - use Centreline or "
                          "Outside Face instead.".format(_label(element)))
        return _pick_face_by_normal(
            element, view, lambda n: (n.Z < -0.7, n.Z))


class OutsideFaceStrategy(MeasurementReferenceStrategy):
    """Side face perpendicular to the element's run axis.

    For rectangular elements: picks one of the two side faces (the
    engine doesn't yet decide which side faces the dimensioning target;
    it picks the first matching face deterministically). The dim line
    offset will compensate visually if the user's chosen offset puts
    the dim text outside the element.

    For round elements: returns the cylinder side face's Reference
    (Revit treats the whole cylinder as one face). The dimension still
    pins to the element's outside surface along the dim line direction,
    which is what the user wants. anchor is the element midpoint.
    """

    key = "outside_face"
    label = "Outside Face"

    @classmethod
    def applies_to(cls, category_key):
        return category_key in _RECTANGULAR_LINEAR + _ROUND_LINEAR

    def get_reference(self, doc, view, element, target_anchor=None):
        if _is_round(element):
            return _pick_curved_side_reference(element, view)
        # Rectangular: a side face has a normal perpendicular to Z
        # (so Z component near 0).
        return _pick_face_by_normal(
            element, view, lambda n: (abs(n.Z) < 0.3, abs(n.Z)))


class InsideFaceStrategy(MeasurementReferenceStrategy):
    """Inside face of a duct / cable tray.

    Revit doesn't model wall thickness on cable trays / ducts in most
    practice setups - the "inside" face is the same face as the outside
    face. We return the same reference as OutsideFaceStrategy so the
    profile + report still surface the user's choice; the dimension
    value will match outside.
    """

    key = "inside_face"
    label = "Inside Face"

    @classmethod
    def applies_to(cls, category_key):
        # Spec exposes Inside on cable trays + ducts only.
        return category_key in _RECTANGULAR_LINEAR

    def get_reference(self, doc, view, element, target_anchor=None):
        return _pick_face_by_normal(
            element, view, lambda n: (abs(n.Z) < 0.3, abs(n.Z)))


class InvertLevelStrategy(MeasurementReferenceStrategy):
    """Bottom-of-inside-diameter on a pipe.

    Round pipes don't expose a flat invert face, so v1 uses the
    cylinder side reference and notes the limitation. The dim text
    will read as the perpendicular distance from the cylinder's
    closest point on the dim line - in practice that's the bottom of
    the pipe when the dim line is below the run. Documented limit.
    """

    key = "invert_level"
    label = "Invert Level"

    @classmethod
    def applies_to(cls, category_key):
        return category_key == "pipe"

    def get_reference(self, doc, view, element, target_anchor=None):
        return _pick_curved_side_reference(element, view)


# Aliases per the spec - the same underlying strategy is exposed under
# different labels per category. The registry pairs (category, key)
# with a strategy instance so the same instance can be reused.
class OutsideEdgeStrategy(OutsideFaceStrategy):
    """Outside Edge of cable tray / conduit (alias of Outside Face)."""

    key = "outside_edge"
    label = "Outside Edge"

    @classmethod
    def applies_to(cls, category_key):
        return category_key in ("cable_tray", "conduit")


class InsideEdgeStrategy(InsideFaceStrategy):
    """Inside Edge of cable tray (alias of Inside Face)."""

    key = "inside_edge"
    label = "Inside Edge"

    @classmethod
    def applies_to(cls, category_key):
        return category_key == "cable_tray"


# ---------------------------------------------------------------------------
# Round-element helpers
# ---------------------------------------------------------------------------

def _is_round(element):
    """True for conduit / pipe / round flex duct.

    We sniff via category id rather than isinstance to avoid pulling
    every MEP discipline DLL just for this check.
    """
    try:
        cat = element.Category
        if cat is None:
            return False
        # OST_Conduit = -2008180, OST_PipeCurves = -2008044,
        # OST_FlexDuctCurves = -2008020. These are stable across Revit
        # versions; matching by integer avoids the per-version enum.
        return cat.Id.IntegerValue in (-2008180, -2008044, -2008020)
    except Exception:
        return False


def _label(element):
    try:
        return element.Category.Name
    except Exception:
        return "element"


def _pick_curved_side_reference(element, view):
    """For round MEP elements, return the curved (cylinder) side face's
    Reference + the element midpoint as anchor. There's only ever one
    such face for a straight pipe/conduit/flex duct, so the first match
    wins.
    """
    from bim_core.core import geometry_utils
    geom = element.get_Geometry(_geometry_options(view))
    if geom is None:
        return None, "no geometry"
    for go in geom:
        for face in _faces_of(go):
            # Curved face = no FaceNormal property exposed.
            try:
                _ = face.FaceNormal
                continue  # planar; skip
            except Exception:
                pass
            # Found a curved face.
            if face.Reference is None:
                return None, ("curved face has no Reference (geometry "
                              "options misconfigured)")
            anchor = geometry_utils.element_midpoint(element)
            if anchor is None:
                return None, "no curve midpoint"
            return face.Reference, anchor
    return None, "no curved side face on this element"
