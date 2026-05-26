# -*- coding: utf-8 -*-
"""Auto Dimension scan + placement orchestration.

Flow:
    1. UI calls scan(doc, view, profiles) -> the engine collects
       elements per unique category referenced by the profile set,
       builds one RulePipeline per profile, evaluates each element
       against every profile that targets its category, and returns
       per-element records with discipline + subcategory + profile
       attribution.
    2. UI calls place_dimensions(doc, view, records, profiles) ->
       for each eligible record the owning profile's measurement
       reference + reference target strategies are dispatched, the
       resulting (Reference, anchor) pairs feed NewDimension. All
       placements happen inside one Transaction.
    3. UI calls reporting.render_html / render_csv ->
       per-profile sections + flat per-element CSV.

v1 scope: current_view_only is enforced (multi-view dispatch is on
the v2 list). Whole_model scanning is intentionally NOT supported.
"""

from Autodesk.Revit.DB import (
    Dimension, FilteredElementCollector, Line, ReferenceArray, Transaction,
    XYZ,
)

from bim_core import element_filters, log as log_module
from bim_core.core import geometry_utils

from dimension_qa import (
    measurement_strategies, target_strategies,
    reporting,
)
from dimension_qa.rules_engine import build_pipeline


# Re-exports so callers can import from dimensioning_engine the same
# way they do from annotation_qa.qa_engine.
report_path     = reporting.report_path
summary_counts  = reporting.summary_counts
breakdown_by_rule = reporting.breakdown_by_rule
render_html     = reporting.render_html
render_csv      = reporting.render_csv


def _logger(doc):
    return log_module.get_logger(doc, tool_name="auto_dimension")


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

def scan(doc, view, profiles):
    """Walk the active view for every enabled profile and produce per-
    element records.

    Records gain a `profile_key` (e.g. "mechanical/duct") and
    `already_dimensioned` flag derived from the per-view dimension
    sweep. Disabled profiles are skipped entirely.
    """
    logger = _logger(doc)
    enabled_profiles = [p for p in profiles if p.enabled]
    if not enabled_profiles:
        logger.warning("Scan called with no enabled profiles; returning empty.")
        return []

    logger.info("Scan started. view=%s profiles=%s",
                view.Name, [p.key for p in enabled_profiles])

    # Per-view dimensioned-id sweep, used by NotAlreadyDimensionedRule.
    dimensioned_ids = dimensioned_element_ids(doc, view)
    logger.info("Found %d already-dimensioned elements in view.",
                len(dimensioned_ids))

    # Collect elements once per unique category.
    category_keys = []
    for p in enabled_profiles:
        if p.category_key not in category_keys:
            category_keys.append(p.category_key)
    elements_by_cat = element_filters.collect_elements_for_categories(
        doc, view, category_keys, whole_model=False)

    # Pre-build one pipeline per enabled profile.
    pipelines_by_cat = {}
    for profile in enabled_profiles:
        pipeline = build_pipeline(profile, scope_is_active_view=True)
        pipelines_by_cat.setdefault(profile.category_key, []).append(
            (profile, pipeline))
        logger.info("  profile %s -> %s",
                    profile.key,
                    ", ".join(pipeline.names()) or "(none)")

    rule_failure_counts = {}
    records = []
    for cat_key, cat_pipelines in pipelines_by_cat.items():
        elements = elements_by_cat.get(cat_key, [])
        for el in elements:
            record = _evaluate_element(
                el, cat_key, cat_pipelines, doc, view,
                dimensioned_ids, rule_failure_counts)
            records.append(record)

    audit_count = sum(1 for r in records if r["audit_eligible"])
    eligible_count = sum(1 for r in records if r["eligible"])
    logger.info(
        "Scan finished. total=%d audit_eligible=%d eligible=%d failures=%s",
        len(records), audit_count, eligible_count, rule_failure_counts)
    return records


def _evaluate_element(el, cat_key, cat_pipelines, doc, view,
                      dimensioned_ids, rule_failure_counts):
    """Same shape as Auto Tag's _evaluate_element: first profile whose
    pipeline passes owns the element; if none pass, attribute to the
    first profile and tally the failing rule."""
    last_failure = None

    for profile, pipeline in cat_pipelines:
        ctx = {
            "doc":              doc,
            "view":             view,
            "category_key":     cat_key,
            "dimensioned_ids":  dimensioned_ids,
            "profile":          profile,
        }
        ok, reason, failing_rule = pipeline.evaluate(el, ctx)
        if ok:
            return _record(el, cat_key, profile, ctx, dimensioned_ids,
                           audit_ok=True, reason=None,
                           failing_rule=None,
                           rule_failure_counts=rule_failure_counts)
        last_failure = (profile, reason, failing_rule, ctx)

    profile, reason, failing_rule, ctx = (
        last_failure if last_failure is not None
        else (cat_pipelines[0][0], "no profile matched", "unattributed", {})
    )
    rule_failure_counts[failing_rule] = (
        rule_failure_counts.get(failing_rule, 0) + 1)
    return _record(el, cat_key, profile, ctx, dimensioned_ids,
                   audit_ok=False, reason=reason,
                   failing_rule=failing_rule,
                   rule_failure_counts=rule_failure_counts)


def _record(el, cat_key, profile, ctx, dimensioned_ids,
            audit_ok, reason, failing_rule, rule_failure_counts):
    binding = profile.binding if profile is not None else None
    eligible = bool(audit_ok)
    skip_reason = None if audit_ok else reason
    return {
        "element":               el,
        "id":                    el.Id.IntegerValue,
        "name":                  _element_name(el),
        "length_mm":             ctx.get("length_mm"),
        "is_horizontal":         _is_h(ctx),
        "already_dimensioned":   el.Id.IntegerValue in dimensioned_ids,
        "audit_eligible":        audit_ok,
        "eligible":              eligible,
        "skip_reason":           skip_reason,
        "failing_rule":          failing_rule,
        "placed":                None,
        "place_error":           None,
        "discipline_key":        profile.discipline_key if profile else None,
        "subcategory_key":       binding.key if binding is not None else None,
        "profile_key":           profile.key if profile is not None else None,
        "binding_label":         binding.label if binding is not None else None,
        "category_key":          cat_key,
        "system_classification": ctx.get("system_classification"),
    }


def _element_name(element):
    try:
        return "{0} - {1}".format(element.Category.Name, element.Name)
    except Exception:
        try:
            return element.Category.Name
        except Exception:
            return "Element"


def _is_h(ctx):
    """Reporting-only helper: True/False/None for the per-record
    'Horiz' display, derived from the same slope the orientation rules
    cache. Returns None for elements with no curve geometry.
    """
    slope = ctx.get("slope_from_horizontal_deg")
    if slope is None:
        return None
    profile = ctx.get("profile")
    tol = profile.orientation_tol_deg if profile is not None else 15.0
    return slope <= tol


# ---------------------------------------------------------------------------
# Already-dimensioned detection
# ---------------------------------------------------------------------------

def dimensioned_element_ids(doc, view):
    """Set of integer ElementIds referenced by any Dimension currently
    placed in the supplied view.

    Walks Dimension.References for every Dimension element in the view
    and adds each Reference.ElementId. Multi-segment dimensions count
    every referenced element. Used by NotAlreadyDimensionedRule.
    """
    collector = (FilteredElementCollector(doc, view.Id)
                 .OfClass(Dimension))
    out = set()
    for d in collector:
        try:
            refs = d.References
        except Exception:
            continue
        if refs is None:
            continue
        for ref in refs:
            try:
                eid = ref.ElementId
            except Exception:
                continue
            if eid is not None and eid.IntegerValue > 0:
                out.add(eid.IntegerValue)
    return out


# ---------------------------------------------------------------------------
# Place
# ---------------------------------------------------------------------------

def place_dimensions(doc, view, records, profiles):
    """Place a dimension for every eligible-and-not-yet-placed record
    in one Transaction.

    For each record:
        1. Look up the owning profile by profile_key.
        2. Dispatch the profile's measurement_reference strategy on
           the element -> (elem_ref, elem_anchor) or skip with reason.
        3. Dispatch the profile's reference_target strategy -> (
           target_ref, target_anchor) or skip with reason.
        4. Build the dimension line: parallel to the vector between
           anchors, offset perpendicular by offset_distance_mm in the
           view plane.
        5. NewDimension(view, line, ReferenceArray). If
           dimension_style_id is set on the profile, ChangeTypeId
           after creation.

    Failures are recorded per record so the report shows which strategy
    rejected which element. Transaction is rolled back on any
    unhandled exception.
    """
    logger = _logger(doc)
    profiles_by_key = {p.key: p for p in profiles}
    targets = [r for r in records
               if r["eligible"] and not r.get("placed")]
    logger.info("Place started. targets=%d profiles=%s",
                len(targets), list(profiles_by_key.keys()))

    style_cache = {}  # profile_key -> ElementId or None

    t = Transaction(doc, "Auto Dimension: Place Dimensions")
    t.Start()
    try:
        for r in targets:
            profile = profiles_by_key.get(r.get("profile_key"))
            if profile is None:
                _mark_failed(r, logger,
                             "no owning profile for record")
                continue
            err = _place_one(doc, view, r, profile, style_cache, logger)
            if err:
                _mark_failed(r, logger, err)
            else:
                r["placed"] = True
                r["place_error"] = None
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        logger.exception("Transaction aborted during dimension placement")
        raise

    placed = sum(1 for r in targets if r.get("placed"))
    failed = len(targets) - placed
    logger.info("Place finished. placed=%d failed=%d", placed, failed)
    return records


def _place_one(doc, view, record, profile, style_cache, logger):
    """Resolve refs + build dim line + call NewDimension. Returns None
    on success or an error string on failure.

    Order matters: target resolves FIRST using the element's
    geometric midpoint as a seed, then the measurement strategy
    resolves WITH the target anchor in hand. CentrelineStrategy uses
    target_anchor to pick the closer end-cap face on linear MEP, which
    makes the resulting reference compatible with NewDimension when
    the target is a perpendicular grid (the line/line case Revit
    rejects with 'Direction of dimension is invalid').
    """
    element = record["element"]

    midpoint = geometry_utils.element_midpoint(element)
    if midpoint is None:
        return "no element midpoint"

    t_strategy = target_strategies.get(profile.reference_target)
    if t_strategy is None:
        return "unknown reference target '{0}'".format(
            profile.reference_target)
    target_ref, target_anchor = t_strategy.get_target(
        doc, view, element, midpoint)
    if target_ref is None:
        return "target '{0}': {1}".format(
            profile.reference_target, target_anchor)

    m_strategy = measurement_strategies.get(
        profile.category_key, profile.measurement_reference)
    if m_strategy is None:
        return "unknown measurement reference '{0}'".format(
            profile.measurement_reference)
    elem_ref, elem_anchor = m_strategy.get_reference(
        doc, view, element, target_anchor=target_anchor)
    if elem_ref is None:
        return "measurement '{0}': {1}".format(
            profile.measurement_reference, elem_anchor)

    line = _build_dim_line(view, elem_anchor, target_anchor,
                           profile.offset_distance_mm)
    if line is None:
        return "could not build dimension line (anchors coincide?)"

    refs = ReferenceArray()
    refs.Append(elem_ref)
    refs.Append(target_ref)

    try:
        dim = doc.Create.NewDimension(view, line, refs)
    except Exception as exc:
        return "NewDimension failed: {0}".format(exc)

    if profile.dimension_style_id is not None:
        style_id = _resolve_style_id(doc, profile, style_cache)
        if style_id is not None:
            try:
                dim.ChangeTypeId(style_id)
            except Exception as exc:
                logger.warning(
                    "ChangeTypeId failed for record id=%s: %s",
                    record["id"], exc)
    return None


def _build_dim_line(view, elem_anchor, target_anchor, offset_distance_mm):
    """Build a Line through both anchors, offset perpendicular to the
    anchor-anchor direction in the view plane by offset_distance_mm.

    Returns None when the anchors coincide (degenerate case the engine
    surfaces as a placement failure).

    Both anchors are projected to the element's Z before the line is
    built. Grids in Revit carry their own elevation (Grid.Curve sits
    at the grid's level, not necessarily at the cable tray's level);
    leaving the anchors at their native Z values would produce a
    sloped 3D dim line that doesn't lie in the plan-view plane and
    Revit rejects it.
    """
    common_z = elem_anchor.Z
    elem_anchor = XYZ(elem_anchor.X, elem_anchor.Y, common_z)
    target_anchor = XYZ(target_anchor.X, target_anchor.Y, common_z)

    v = target_anchor - elem_anchor
    length = v.GetLength()
    if length < 1e-9:
        return None
    along = v.Normalize()

    # Perpendicular within the view plane: cross product of the view's
    # normal vector with the along-vector. For a horizontal plan view
    # (view_normal = -Z) and along = +X this evaluates to -Y; the dim
    # ends up south of the elements. Sign is consistent across the
    # session - we don't try to be clever about which side avoids
    # overlap in v1.
    try:
        view_normal = view.ViewDirection
    except Exception:
        view_normal = XYZ.BasisZ
    perp = view_normal.CrossProduct(along)
    if perp.GetLength() < 1e-9:
        # along is parallel to view_normal - happens in section views
        # when dim'ing along the view direction. Fall back to in-XY-
        # plane perpendicular.
        perp = XYZ(-along.Y, along.X, 0)
        if perp.GetLength() < 1e-9:
            return None
    perp = perp.Normalize()
    offset_ft = geometry_utils.mm_to_internal(offset_distance_mm)
    p1 = elem_anchor + perp.Multiply(offset_ft)
    p2 = target_anchor + perp.Multiply(offset_ft)
    try:
        return Line.CreateBound(p1, p2)
    except Exception:
        return None


def _resolve_style_id(doc, profile, style_cache):
    """Resolve profile.dimension_style_id (an int) into a Revit
    ElementId, cached per profile.key. Returns None when the saved
    id is no longer loaded (placement falls back to the view's
    default dimension type)."""
    cached = style_cache.get(profile.key, _SENTINEL)
    if cached is not _SENTINEL:
        return cached
    from Autodesk.Revit.DB import ElementId
    try:
        eid = ElementId(profile.dimension_style_id)
        elem = doc.GetElement(eid)
    except Exception:
        elem = None
    style_cache[profile.key] = eid if elem is not None else None
    return style_cache[profile.key]


_SENTINEL = object()


def _mark_failed(record, logger, error):
    record["placed"] = False
    record["place_error"] = error
    logger.error("Place failed for id=%s name=%s: %s",
                 record["id"], record["name"], error)
