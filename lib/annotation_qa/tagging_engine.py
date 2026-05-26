# -*- coding: utf-8 -*-
"""Tag discovery, tag detection, tag placement.

Category metadata (which BuiltInCategory holds tags for which host
category) is now sourced from core.category_config.REGISTRY. The
CATEGORY_TO_TAG_BIC re-export below stays in place for backward
compatibility, but new code should read cfg.tag_bic directly.

place_tag() runs a PlacementStrategy to get a ranked list of XYZ
candidates, then walks them against a ClashIndex (if supplied) and
places the first non-clashing one - or the lowest-scoring one when
every candidate clashes. The chosen position + a placement_quality
flag come back on a PlacementResult so qa_engine can record per-tag
quality on its records for the HTML report.

Hosts: LocationCurve (trays, conduits, ducts, pipes) and
LocationPoint (equipment, sprinklers, fittings, fixtures) are both
handled - the strategy and core.geometry_utils.element_origin pick
the right origin internally, so place_tag does not branch on
category.
"""

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    FamilySymbol,
    IndependentTag,
    Reference,
    TagMode,
    TagOrientation,
)

from bim_core.core import category_config, geometry_utils


# Backward-compat re-export. category_config.REGISTRY[k].tag_bic is the
# canonical source.
CATEGORY_TO_TAG_BIC = {k: cfg.tag_bic
                      for k, cfg in category_config.REGISTRY.items()}


# ---------------------------------------------------------------------------
# Tag family discovery
# ---------------------------------------------------------------------------

def collect_tag_symbols(doc, category_key="cable_tray"):
    """Loaded tag FamilySymbols compatible with the host category."""
    cfg = category_config.get_safe(category_key)
    if cfg is None:
        raise ValueError("Unsupported category: {0}".format(category_key))

    collector = (FilteredElementCollector(doc)
                 .OfCategory(cfg.tag_bic)
                 .WhereElementIsElementType())
    symbols = []
    for s in collector:
        if isinstance(s, FamilySymbol):
            symbols.append(s)
    return symbols


# ---------------------------------------------------------------------------
# Tag detection
# ---------------------------------------------------------------------------

def _tag_targets(tag):
    """List of ElementIds a tag points at, across Revit API versions.

    Multi-target API arrived in Revit 2022; older versions expose a
    single TaggedLocalElementId (or TaggedElementId) instead.
    """
    try:
        return list(tag.GetTaggedLocalElementIds())
    except AttributeError:
        pass
    for attr in ("TaggedLocalElementId", "TaggedElementId"):
        try:
            eid = getattr(tag, attr)
            if eid is not None:
                return [eid]
        except Exception:
            continue
    return []


def tagged_element_ids(doc, view=None, whole_model=False):
    """Set of integer ElementIds tagged by any IndependentTag in scope.

    whole_model=False: only tags placed in the supplied view count.
    whole_model=True:  any tag anywhere in the host doc counts.
    """
    if whole_model:
        collector = FilteredElementCollector(doc).OfClass(IndependentTag)
    else:
        collector = (FilteredElementCollector(doc, view.Id)
                     .OfClass(IndependentTag))
    tagged = set()
    for tag in collector:
        for eid in _tag_targets(tag):
            if eid is not None and eid.IntegerValue > 0:
                tagged.add(eid.IntegerValue)
    return tagged


def is_tagged(element, tagged_ids):
    return element.Id.IntegerValue in tagged_ids


# ---------------------------------------------------------------------------
# Tag placement
# ---------------------------------------------------------------------------

class PlacementResult(object):
    """Outcome of place_tag(): the placed IndependentTag, where it
    landed, and how the engine got there.

    quality values, in increasing badness:
        QUALITY_CLEAN     first strategy candidate was clean
        QUALITY_NUDGED    a later strategy candidate was clean
        QUALITY_FALLBACK  every candidate clashed; lowest-score won
        QUALITY_DEFAULT   strategy yielded zero candidates; placed at
                          element_origin as terminal fallback

    qa_engine copies `quality` onto its record so reporting.render_html
    can colour the placement column accordingly.
    """

    QUALITY_CLEAN    = "clean"
    QUALITY_NUDGED   = "nudged"
    QUALITY_FALLBACK = "fallback"
    QUALITY_DEFAULT  = "default"

    def __init__(self, tag, quality, xyz_used):
        self.tag = tag
        self.quality = quality
        self.xyz_used = xyz_used


def place_tag(doc, view, element, profile, strategy,
              clash_index=None, tag_symbol=None):
    """Place a tag for `element` in `view` via the supplied strategy.

    profile     - TaggingProfile. Drives effective_add_leader and is
                  passed through to the strategy for offset_mm / side.
    strategy    - PlacementStrategy resolved by qa_engine via
                  placement_strategies.get_for(profile). Yields one or
                  more candidate XYZs in preferred order.
    clash_index - optional ClashIndex. When supplied, candidates are
                  scored and the first clean one wins; if none are
                  clean, the lowest-score candidate is used and the
                  result is flagged QUALITY_FALLBACK. When None,
                  candidates[0] is used directly with no checking
                  (used when every enabled profile is on_element mode
                  so the index isn't worth building).

    MUST run inside an active Transaction. Returns a PlacementResult.
    Raises ValueError if the strategy yields nothing AND the element
    has no element_origin to fall back to.
    """
    candidates = list(strategy.propose_positions(view, element, profile))

    if not candidates:
        # Strategy bailed. Terminal fallback: tag on element_origin so
        # the user gets *something*; the report flags it as DEFAULT so
        # they know the strategy didn't get to weigh in.
        chosen = geometry_utils.element_origin(element)
        if chosen is None:
            raise ValueError(
                "Element {0} has no placement point (no LocationPoint "
                "or LocationCurve).".format(element.Id.IntegerValue))
        quality = PlacementResult.QUALITY_DEFAULT

    elif clash_index is None or len(candidates) == 1:
        # No clash checking requested, or the strategy is single-
        # candidate (on_element). Use the first candidate verbatim -
        # quality stays CLEAN because we have not detected a clash.
        chosen = candidates[0]
        quality = PlacementResult.QUALITY_CLEAN

    else:
        chosen, quality = _pick_candidate(candidates, clash_index, tag_symbol)

    if tag_symbol is not None and not tag_symbol.IsActive:
        tag_symbol.Activate()
        doc.Regenerate()

    ref = Reference(element)
    tag = IndependentTag.Create(
        doc,
        view.Id,
        ref,
        profile.effective_add_leader,
        TagMode.TM_ADDBY_CATEGORY,
        TagOrientation.Horizontal,
        chosen,
    )

    # Older Revit versions return an ElementId rather than the tag object.
    if not isinstance(tag, IndependentTag):
        try:
            tag = doc.GetElement(tag)
        except Exception:
            tag = None

    if tag is not None and tag_symbol is not None:
        try:
            tag.ChangeTypeId(tag_symbol.Id)
        except Exception:
            # If the requested type isn't valid for this tag instance,
            # the default type stays; surfaced via the QA report.
            pass
    return PlacementResult(tag, quality, chosen)


def delete_existing_tags(doc, view, category_keys, whole_model=False):
    """Delete every IndependentTag in scope belonging to the tag
    categories matching `category_keys`.

    Uses cfg.tag_bic (e.g. OST_DuctTags for 'duct') from
    category_config.REGISTRY rather than walking each tag's targets,
    because the host->tag category mapping is 1:1 in practice. Multi-
    category tags - rare in MEP coordination - whose own category
    doesn't match one of these BICs won't be collected; if a project
    relies on them, the target-walking variant in `tagged_element_ids`
    is the place to extend from.

    Scope mirrors the scan:
        whole_model=False : tags placed in `view` only
        whole_model=True  : every tag of these categories in `doc`

    MUST run inside an active Transaction. Returns the number of tags
    deleted. Raises if Delete fails; the caller's transaction then
    rolls back so the model is never left half-deleted.
    """
    tag_bics = []
    for key in category_keys:
        cfg = category_config.get_safe(key)
        if cfg is None:
            continue
        if cfg.tag_bic not in tag_bics:
            tag_bics.append(cfg.tag_bic)

    if not tag_bics:
        return 0

    tag_ids = []
    for tag_bic in tag_bics:
        if whole_model:
            collector = FilteredElementCollector(doc).OfCategory(tag_bic)
        else:
            collector = (FilteredElementCollector(doc, view.Id)
                         .OfCategory(tag_bic))
        for tag in collector:
            tag_ids.append(tag.Id)

    for tid in tag_ids:
        doc.Delete(tid)

    return len(tag_ids)


def _pick_candidate(candidates, clash_index, tag_symbol):
    """Walk candidates in order; return (xyz, quality).

    First clean candidate wins. If none are clean, return the
    candidate with the smallest (collision_count, penetration_area)
    tuple - that's the "least bad" fallback.
    """
    best_score = None
    best_xyz = None
    for i, cand in enumerate(candidates):
        score = clash_index.score(cand, tag_symbol)
        if score[0] == 0:
            quality = (PlacementResult.QUALITY_CLEAN if i == 0
                       else PlacementResult.QUALITY_NUDGED)
            return cand, quality
        if best_score is None or score < best_score:
            best_score = score
            best_xyz = cand
    return best_xyz, PlacementResult.QUALITY_FALLBACK
