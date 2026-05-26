# -*- coding: utf-8 -*-
"""ClashIndex - per-scan cache for tag placement clash avoidance.

The index is built once per Auto Tag run and queried per candidate
XYZ proposed by a PlacementStrategy. Internally it stores 2D
rectangles (umin, vmin, umax, vmax) projected onto the active view's
plane, so overlap tests are plain XY arithmetic rather than 3D box
maths.

Caches three populations:

    annotation_rects  IndependentTag / TextNote / Dimension instances
                      already in the view. The most common source of
                      "tag landed on another tag" complaints.
    model_rects       Visible model element bboxes for the categories
                      the caller asks about. qa_engine passes the
                      categories currently being tagged + a baseline
                      "always present" set (walls, columns, framing)
                      so a tag never lands on the geometry it's
                      pointing at.
    crop_rect         The view's crop region as a 2D rect when the
                      crop box is active. Candidates that extend
                      outside count as a clash so tags don't get cut
                      off on sheets.

Bbox estimation for the candidate tag is intentionally cheap: paper
text size (read from the tag FamilySymbol when possible, otherwise a
default) multiplied by view.Scale. No regen per candidate. See the
v6 design notes in profiles.py for the trade-off versus the slower
'place-regen-measure' approach.
"""

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    Dimension,
    FilteredElementCollector,
    IndependentTag,
    TextNote,
    XYZ,
)

from bim_core.core import category_config, geometry_utils


# ---------------------------------------------------------------------------
# Defaults.
# ---------------------------------------------------------------------------

# Tag bbox estimate when the tag FamilySymbol carries no usable text
# size parameter. 40mm x 6mm on paper covers a typical MEP tag with a
# short identifier; oversize tags (multi-line annotations) will be
# under-estimated and may not flag every clash. Adjustable per project
# if a tag standard demands it.
_DEFAULT_TAG_WIDTH_PAPER_MM  = 40.0
_DEFAULT_TAG_HEIGHT_PAPER_MM = 6.0

# Structural + annotation surfaces that are blockers regardless of
# which MEP categories the scan touches. Walls/framing/columns stop
# tags landing inside building fabric; floors/roofs/ceilings catch
# horizontal surfaces; grids/levels/generic-annotation/detail/filled
# regions stop tags overlapping sheet annotations.
_STRUCTURAL_AND_ANNOTATION_BLOCKER_BICS = (
    BuiltInCategory.OST_Walls,
    BuiltInCategory.OST_StructuralFraming,
    BuiltInCategory.OST_StructuralColumns,
    BuiltInCategory.OST_Floors,
    BuiltInCategory.OST_Roofs,
    BuiltInCategory.OST_Ceilings,
    BuiltInCategory.OST_Grids,
    BuiltInCategory.OST_Levels,
    BuiltInCategory.OST_GenericAnnotation,
    BuiltInCategory.OST_DetailComponents,
    BuiltInCategory.OST_FilledRegion,
)


def _baseline_blocker_bics():
    """Union of the structural/annotation surfaces above with every
    MEP category registered in category_config. Auto-deriving means a
    new category gets clash protection for free — no second place to
    update when a discipline grows.

    Tags should never land on any model element the user can see in
    MEP views; restricting blockers to "only what's being scanned this
    run" lets a duct tag land on a pipe.
    """
    bics = list(_STRUCTURAL_AND_ANNOTATION_BLOCKER_BICS)
    seen = set(bics)
    for cfg in category_config.REGISTRY.values():
        if cfg.bic not in seen:
            bics.append(cfg.bic)
            seen.add(cfg.bic)
    return tuple(bics)


# ---------------------------------------------------------------------------
# View-plane geometry helpers.
# ---------------------------------------------------------------------------

def project_xyz(view, point):
    """3D XYZ -> (u, v) in the view's plane.

    u = component along view.RightDirection, v = component along
    view.UpDirection. Both measured from view.Origin so the returned
    coordinates are stable across the scan.
    """
    rel = point - view.Origin
    return (rel.DotProduct(view.RightDirection),
            rel.DotProduct(view.UpDirection))


def project_bbox(view, bbox):
    """Project a Revit BoundingBoxXYZ onto the view plane.

    Returns (umin, vmin, umax, vmax). Walks all eight corners because
    BoundingBoxXYZ is axis-aligned in world coordinates, not in view
    coordinates - skipping corners would underestimate the rect for
    sections / elevations whose axes don't line up with world XYZ.
    Returns None if bbox is None.
    """
    if bbox is None:
        return None
    p0 = bbox.Min
    p1 = bbox.Max
    corners = (
        XYZ(p0.X, p0.Y, p0.Z),
        XYZ(p1.X, p0.Y, p0.Z),
        XYZ(p0.X, p1.Y, p0.Z),
        XYZ(p1.X, p1.Y, p0.Z),
        XYZ(p0.X, p0.Y, p1.Z),
        XYZ(p1.X, p0.Y, p1.Z),
        XYZ(p0.X, p1.Y, p1.Z),
        XYZ(p1.X, p1.Y, p1.Z),
    )
    us = []
    vs = []
    for c in corners:
        u, v = project_xyz(view, c)
        us.append(u)
        vs.append(v)
    return (min(us), min(vs), max(us), max(vs))


def rect_overlap_area(a, b):
    """Intersection area of two (umin,vmin,umax,vmax) rects.

    Zero when they don't overlap; never negative.
    """
    umin = max(a[0], b[0])
    vmin = max(a[1], b[1])
    umax = min(a[2], b[2])
    vmax = min(a[3], b[3])
    du = umax - umin
    dv = vmax - vmin
    if du <= 0.0 or dv <= 0.0:
        return 0.0
    return du * dv


def rect_contains(outer, inner):
    """True iff inner is fully inside outer."""
    return (inner[0] >= outer[0] and inner[1] >= outer[1]
            and inner[2] <= outer[2] and inner[3] <= outer[3])


def rect_exterior_area(rect, outer):
    """Area of `rect` outside `outer`.

    Used as the penalty for candidates that escape the view crop. A
    candidate fully inside the crop returns 0; a candidate that pokes
    out by a small strip returns that strip's area.
    """
    total = max(0.0, rect[2] - rect[0]) * max(0.0, rect[3] - rect[1])
    return max(0.0, total - rect_overlap_area(rect, outer))


# ---------------------------------------------------------------------------
# Tag bbox estimation.
# ---------------------------------------------------------------------------

def estimate_candidate_rect(view, xyz, tag_symbol=None,
                            width_paper_mm=None,
                            height_paper_mm=None):
    """Approximate 2D rect a tag would occupy if placed at xyz.

    Height comes from the tag FamilySymbol's TEXT_SIZE parameter when
    available (in internal feet, converted to paper-mm via view.Scale)
    so projects that use a 2.5mm vs 5mm tag standard get appropriately
    sized rects. Width is a default constant - reading character count
    pre-placement would mean evaluating the tag's label expression,
    which is more complexity than v1 wants. Oversized labels may slip
    past clash detection; the placement report flags fallback cases
    so the user notices.
    """
    if width_paper_mm is None:
        width_paper_mm = _DEFAULT_TAG_WIDTH_PAPER_MM
    if height_paper_mm is None:
        height_paper_mm = _read_tag_text_height_mm(tag_symbol)
        if height_paper_mm is None:
            height_paper_mm = _DEFAULT_TAG_HEIGHT_PAPER_MM

    scale = view.Scale if view.Scale else 1
    model_width_ft  = geometry_utils.mm_to_internal(width_paper_mm  * scale)
    model_height_ft = geometry_utils.mm_to_internal(height_paper_mm * scale)

    u, v = project_xyz(view, xyz)
    hw = model_width_ft  * 0.5
    hh = model_height_ft * 0.5
    return (u - hw, v - hh, u + hw, v + hh)


def _read_tag_text_height_mm(tag_symbol):
    """Pull the tag FamilySymbol's text height in mm, or None.

    Returns None when no symbol is passed or the parameter is absent /
    unreadable - the caller falls back to the default.
    """
    if tag_symbol is None:
        return None
    try:
        p = tag_symbol.get_Parameter(BuiltInParameter.TEXT_SIZE)
    except Exception:
        return None
    if p is None:
        return None
    try:
        ft = p.AsDouble()
    except Exception:
        return None
    if ft <= 0:
        return None
    return geometry_utils.internal_to_mm(ft)


# ---------------------------------------------------------------------------
# ClashIndex.
# ---------------------------------------------------------------------------

class ClashIndex(object):
    """One-per-scan cache of view-plane rects to test tag candidates against."""

    def __init__(self, doc, view, model_category_bics=None,
                 extra_blocker_bics=None):
        self._view = view
        self._annotation_rects = list(self._collect_annotation_rects(doc, view))

        bics = []
        seen = set()
        for bic in _baseline_blocker_bics():
            if bic not in seen:
                bics.append(bic)
                seen.add(bic)
        # model_category_bics is kept for callers that want to inject
        # categories not in category_config; since the baseline now
        # includes every registered MEP BIC, in-registry entries are
        # already covered and the dedup loop is a no-op for them.
        for extras in (model_category_bics, extra_blocker_bics):
            if not extras:
                continue
            for bic in extras:
                if bic is not None and bic not in seen:
                    bics.append(bic)
                    seen.add(bic)
        self._model_rects = list(self._collect_model_rects(doc, view, bics))

        self._crop_rect = self._collect_crop_rect(view)

    # ----- collectors -------------------------------------------------------

    def _collect_annotation_rects(self, doc, view):
        for cls in (IndependentTag, TextNote, Dimension):
            for el in FilteredElementCollector(doc, view.Id).OfClass(cls):
                rect = self._element_rect(el)
                if rect is not None:
                    yield rect

    def _collect_model_rects(self, doc, view, bics):
        for bic in bics:
            collector = (FilteredElementCollector(doc, view.Id)
                         .OfCategory(bic)
                         .WhereElementIsNotElementType())
            for el in collector:
                rect = self._element_rect(el)
                if rect is not None:
                    yield rect

    def _collect_crop_rect(self, view):
        try:
            if not view.CropBoxActive:
                return None
            return project_bbox(view, view.CropBox)
        except Exception:
            return None

    def _element_rect(self, element):
        try:
            bbox = element.get_BoundingBox(self._view)
        except Exception:
            return None
        return project_bbox(self._view, bbox)

    # ----- queries ----------------------------------------------------------

    def has_clash(self, candidate_xyz, tag_symbol=None):
        """True iff the estimated tag rect overlaps any cached rect or
        falls outside the view crop."""
        rect = estimate_candidate_rect(self._view, candidate_xyz, tag_symbol)
        return self._score(rect)[0] > 0

    def score(self, candidate_xyz, tag_symbol=None):
        """Rank a candidate when every option clashes.

        Returns (collision_count, total_penetration_area). The engine
        picks the candidate with the smallest tuple - fewest
        collisions, then least penetration area as a tie-breaker.
        """
        rect = estimate_candidate_rect(self._view, candidate_xyz, tag_symbol)
        return self._score(rect)

    def add_placed_tag(self, xyz, tag_symbol=None):
        """Register a newly placed tag's estimated rect in the cache.

        The constructor's FilteredElementCollector pass only sees what
        was in the model when the scan started; without this, two
        adjacent placements in the same run could land on top of each
        other. The engine calls this after every successful placement
        so the next candidate scoring already sees the tag it just
        dropped.
        """
        rect = estimate_candidate_rect(self._view, xyz, tag_symbol)
        self._annotation_rects.append(rect)

    def _score(self, rect):
        collisions = 0
        penetration = 0.0
        for other in self._annotation_rects:
            area = rect_overlap_area(rect, other)
            if area > 0:
                collisions += 1
                penetration += area
        for other in self._model_rects:
            area = rect_overlap_area(rect, other)
            if area > 0:
                collisions += 1
                penetration += area
        if self._crop_rect is not None and not rect_contains(
                self._crop_rect, rect):
            collisions += 1
            penetration += rect_exterior_area(rect, self._crop_rect)
        return collisions, penetration
