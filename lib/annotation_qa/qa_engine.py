# -*- coding: utf-8 -*-
"""Scan + place orchestration.

Flow:
    1. UI calls scan(doc, view, profiles, whole_model) -> qa_engine
       collects elements per unique category referenced by the profile
       set, builds a RulePipeline per profile, evaluates each element
       against every profile that targets its category, and returns
       per-element records with discipline + subcategory + profile
       attribution.
    2. UI calls place_tags(doc, view, records, profiles) -> the engine
       places tags for every eligible record inside one Transaction.
       Tag symbols are looked up per record's owning profile.
    3. UI calls reporting.render_html(records, view_name, scan_options,
       profiles, path) -> HTML report grouped by discipline ->
       subcategory with one active-filters line per profile.

Reporting (summary_counts, breakdown_by_rule, render_html, report_path)
lives in `reporting.py`; thin re-exports stay here so existing callers
keep working.
"""

from Autodesk.Revit.DB import BuiltInCategory, Transaction

from bim_core import element_filters
from bim_core import log as log_module
from bim_core.core import category_config
from annotation_qa import placement_strategies
from annotation_qa import tagging_engine
from annotation_qa import reporting
from annotation_qa.clash_index import ClashIndex
from annotation_qa.profiles import PLACEMENT_MODE_ADJACENT
from annotation_qa.rules_engine import build_pipeline


def _logger(doc):
    """Auto Tag's named logger handle - keeps every callsite from
    repeating the tool_name."""
    return log_module.get_logger(doc, tool_name="auto_tag")


# ---------------------------------------------------------------------------
# Back-compat re-exports
# ---------------------------------------------------------------------------

report_path = reporting.report_path
summary_counts = reporting.summary_counts
breakdown_by_rule = reporting.breakdown_by_rule
render_html = reporting.render_html


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

def scan(doc, view, profiles, whole_model=False, progress=None):
    """Walk the model for every enabled profile and produce per-element
    records.

    profiles: iterable of TaggingProfile. Disabled profiles are skipped
    entirely (no records, no log noise). When two profiles share a
    category (e.g. Hydraulic Pipes + Mechanical Pipework both binding
    OST_PipeCurves with disjoint system filters), each element is
    evaluated against every profile in selection order; the first
    profile whose pipeline passes owns the element.

    progress: optional callable(processed:int, total:int) -> bool.
        Invoked periodically (every PROGRESS_STEP elements) so the UI
        can drive a progress bar. Return False to cancel; scan then
        stops and returns None. Throttled to avoid swamping the UI
        thread - per-element invocation would dominate runtime on
        whole-model scopes with 10k+ elements.

    Each record carries:
        element, id, name, length_mm, is_horizontal, already_tagged,
        in_active_view, audit_eligible, eligible, skip_reason,
        failing_rule, placed, place_error,
        discipline_key, subcategory_key, profile_key, binding_label,
        category_key, system_classification

    audit_eligible = passes the rule pipeline (independent of view).
    eligible       = audit_eligible AND visible in the active view.
                     place_tags only iterates eligible records.
    """
    logger = _logger(doc)

    enabled_profiles = [p for p in profiles if p.enabled]
    if not enabled_profiles:
        logger.warning("Scan called with no enabled profiles; returning empty.")
        return []

    logger.info("Scan started. view=%s scope=%s profiles=%s",
                view.Name,
                "whole_model" if whole_model else "active_view",
                [p.key for p in enabled_profiles])

    # Collect elements once per unique category so two profiles sharing
    # a category don't re-run the FilteredElementCollector.
    category_keys = []
    for p in enabled_profiles:
        if p.category_key not in category_keys:
            category_keys.append(p.category_key)
    elements_by_cat = element_filters.collect_elements_for_categories(
        doc, view, category_keys, whole_model=whole_model)

    tagged_ids = tagging_engine.tagged_element_ids(
        doc, view=view, whole_model=whole_model)

    # Whole-model scope: track which elements are visible in the active
    # view per category for the "eligible elsewhere" marker.
    visible_by_cat = {}
    if whole_model:
        for cat_key in category_keys:
            visible_by_cat[cat_key] = element_filters.view_visible_element_ids(
                doc, view, cat_key)

    # Pre-build one pipeline per enabled profile (cheap; rules are
    # small) and group by category so each element is only evaluated
    # against profiles that share its category.
    pipelines_by_cat = {}
    for profile in enabled_profiles:
        pipeline = build_pipeline(
            profile, scope_is_active_view=(not whole_model))
        pipelines_by_cat.setdefault(profile.category_key, []).append(
            (profile, pipeline))
        logger.info("  profile %s -> %s",
                    profile.key,
                    ", ".join(pipeline.names()) or "(none)")

    rule_failure_counts = {}
    records = []

    total = sum(len(elements_by_cat.get(k, [])) for k in pipelines_by_cat)
    processed = 0

    for cat_key, cat_pipelines in pipelines_by_cat.items():
        elements = elements_by_cat.get(cat_key, [])
        visible_ids = visible_by_cat.get(cat_key)

        for el in elements:
            record = _evaluate_element(
                el, cat_key, cat_pipelines, doc, view, tagged_ids,
                visible_ids, rule_failure_counts,
            )
            records.append(record)
            processed += 1
            if (progress is not None
                    and processed % PROGRESS_STEP == 0
                    and not progress(processed, total)):
                logger.info(
                    "Scan cancelled by user at %d/%d.", processed, total)
                return None

    if progress is not None and total:
        # Final tick so the bar settles at 100% even when total is not
        # a multiple of PROGRESS_STEP.
        progress(total, total)

    audit_count = sum(1 for r in records if r["audit_eligible"])
    eligible_count = sum(1 for r in records if r["eligible"])
    logger.info(
        "Scan finished. total=%d audit_eligible=%d eligible=%d failures=%s",
        len(records), audit_count, eligible_count, rule_failure_counts)
    return records


# How often to call progress() during the eval loop. Tuned to keep UI
# updates frequent enough to feel live (a few times per second on a
# typical whole-model scan) without dominating runtime via Dispatcher
# round-trips. 25 -> ~400 ticks for a 10k-element model.
PROGRESS_STEP = 25


def _evaluate_element(el, cat_key, cat_pipelines, doc, view, tagged_ids,
                      visible_ids, rule_failure_counts):
    """Run every profile's pipeline against el. First passing profile
    owns the element. If none pass, attribute to the first profile (so
    the rule failure is reported under SOME bucket) and surface that
    pipeline's failure reason.
    """
    last_failure = None  # (profile, reason, failing_rule, ctx)

    for profile, pipeline in cat_pipelines:
        ctx = {
            "doc":          doc,
            "view":         view,
            "category_key": cat_key,
            "tagged_ids":   tagged_ids,
            "profile":      profile,
        }
        ok, reason, failing_rule = pipeline.evaluate(el, ctx)
        if ok:
            return _record(el, cat_key, profile, ctx, tagged_ids,
                           visible_ids,
                           audit_ok=True, reason=None,
                           failing_rule=None,
                           rule_failure_counts=rule_failure_counts)
        last_failure = (profile, reason, failing_rule, ctx)

    # No profile accepted this element. Attribute to the first profile
    # we tried and tally the rule failure.
    profile, reason, failing_rule, ctx = (
        last_failure if last_failure is not None
        else (cat_pipelines[0][0], "no profile matched", "unattributed", {})
    )
    rule_failure_counts[failing_rule] = (
        rule_failure_counts.get(failing_rule, 0) + 1)
    return _record(el, cat_key, profile, ctx, tagged_ids, visible_ids,
                   audit_ok=False, reason=reason,
                   failing_rule=failing_rule,
                   rule_failure_counts=rule_failure_counts)


def _record(el, cat_key, profile, ctx, tagged_ids, visible_ids,
            audit_ok, reason, failing_rule, rule_failure_counts):
    in_av = (visible_ids is None) or (el.Id.IntegerValue in visible_ids)
    if audit_ok and not in_av:
        eligible = False
        skip_reason = "eligible elsewhere - not in active view"
        failing_rule = "scope"
    elif audit_ok:
        eligible = True
        skip_reason = None
    else:
        eligible = False
        skip_reason = reason

    binding = profile.binding if profile is not None else None

    return {
        "element":               el,
        "id":                    el.Id.IntegerValue,
        "name":                  _element_name(el),
        "length_mm":             ctx.get("length_mm"),
        "is_horizontal":         _is_h(ctx),
        "already_tagged":        el.Id.IntegerValue in tagged_ids,
        "in_active_view":        in_av,
        "audit_eligible":        audit_ok,
        "eligible":              eligible,
        "skip_reason":           skip_reason,
        "failing_rule":          failing_rule,
        "placed":                None,
        "place_error":           None,
        "placement_quality":     None,
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
    """Reporting-only: True/False/None for the 'Horiz' record column,
    derived from the slope the orientation rules cache."""
    slope = ctx.get("slope_from_horizontal_deg")
    if slope is None:
        return None
    profile = ctx.get("profile")
    tol = profile.orientation_tol_deg if profile is not None else 15.0
    return slope <= tol


# ---------------------------------------------------------------------------
# Place
# ---------------------------------------------------------------------------

def _resolve_extra_blocker_bics(name_list, logger):
    """Resolve scan_options["clash_extra_blocker_categories"] (a list of
    BuiltInCategory name strings) into enum values. Unknown names are
    logged and dropped so a typo in project JSON never crashes a scan.
    """
    if not name_list:
        return ()
    if not isinstance(name_list, (list, tuple)):
        logger.warning(
            "clash_extra_blocker_categories must be a list, got %r - ignored.",
            type(name_list).__name__)
        return ()
    resolved = []
    for raw in name_list:
        if not isinstance(raw, str):
            logger.warning(
                "clash_extra_blocker_categories entry must be a string, "
                "got %r - skipped.", raw)
            continue
        bic = getattr(BuiltInCategory, raw, None)
        if bic is None:
            logger.warning(
                "clash_extra_blocker_categories: unknown BuiltInCategory "
                "%r - skipped.", raw)
            continue
        resolved.append(bic)
    return tuple(resolved)


def place_tags(doc, view, records, profiles, scan_options=None):
    """Tag every eligible-and-not-yet-placed record in one Transaction.

    Each record carries its owning profile_key; the matching profile
    supplies the tag symbol id (resolved against the loaded family
    symbols for its category), the placement strategy (resolved via
    placement_strategies.get_for), and the leader preference. If the
    saved symbol id is no longer loaded, falls back to the first
    available symbol for that category - the placement still happens,
    just with Revit's default type for the tag instance.

    Clash avoidance: a ClashIndex is built once before placement when
    at least one enabled profile is in 'adjacent' mode. Every
    placement scores its strategy's candidates against the cache and
    picks the first clean one (or the lowest-scoring fallback). The
    chosen position is added back into the cache so subsequent
    placements during the same scan don't land on top of each other.
    Pure 'on_element' runs skip the cache build entirely - matches
    pre-v6 cost.
    """
    logger = _logger(doc)

    profiles_by_key = {p.key: p for p in profiles}
    targets = [r for r in records if r["eligible"] and not r.get("placed")]

    enabled_profiles = [p for p in profiles if p.enabled]
    use_clash_index = any(
        p.placement_mode == PLACEMENT_MODE_ADJACENT for p in enabled_profiles)

    clash_index = None
    if use_clash_index:
        scan_bics = []
        for p in enabled_profiles:
            cfg = category_config.get_safe(p.category_key)
            if cfg is not None and cfg.bic not in scan_bics:
                scan_bics.append(cfg.bic)
        extra_bics = _resolve_extra_blocker_bics(
            (scan_options or {}).get("clash_extra_blocker_categories"),
            logger)
        clash_index = ClashIndex(
            doc, view,
            model_category_bics=scan_bics,
            extra_blocker_bics=extra_bics)

    logger.info("Place started. targets=%d profiles=%s clash_index=%s",
                len(targets),
                list(profiles_by_key.keys()),
                "on" if use_clash_index else "off")

    # Cache resolved (FamilySymbol, PlacementStrategy) per profile key
    # so we don't re-collect tags or re-route the factory per record.
    symbol_cache = {}
    strategy_cache = {}

    t = Transaction(doc, "Auto Tag: Place Tags")
    t.Start()
    try:
        for r in targets:
            profile = profiles_by_key.get(r.get("profile_key"))
            if profile is None:
                r["placed"] = False
                r["place_error"] = "no owning profile"
                r["placement_quality"] = None
                logger.warning(
                    "Skip place for id=%s: profile_key=%s not in current set",
                    r["id"], r.get("profile_key"))
                continue
            sym = _resolve_symbol(doc, profile, symbol_cache)
            strategy = _resolve_strategy(profile, strategy_cache)
            try:
                result = tagging_engine.place_tag(
                    doc, view, r["element"], profile, strategy,
                    clash_index=clash_index,
                    tag_symbol=sym,
                )
                r["placed"] = True
                r["place_error"] = None
                r["placement_quality"] = result.quality
                if clash_index is not None and result.xyz_used is not None:
                    clash_index.add_placed_tag(result.xyz_used, sym)
                logger.debug("Placed tag for id=%s via %s [%s]",
                             r["id"], profile.key, result.quality)
            except Exception as exc:
                r["placed"] = False
                r["place_error"] = str(exc)
                r["placement_quality"] = None
                logger.error("Place failed for id=%s name=%s: %s",
                             r["id"], r["name"], exc)
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        logger.exception("Transaction aborted during tag placement")
        raise

    placed = sum(1 for r in targets if r.get("placed"))
    failed = len(targets) - placed
    by_quality = {}
    for r in targets:
        q = r.get("placement_quality")
        if q:
            by_quality[q] = by_quality.get(q, 0) + 1
    logger.info("Place finished. placed=%d failed=%d quality=%s",
                placed, failed, by_quality)
    return records


def _resolve_strategy(profile, cache):
    """Memoised placement_strategies.get_for(profile) by profile.key."""
    if profile.key in cache:
        return cache[profile.key]
    strategy = placement_strategies.get_for(profile)
    cache[profile.key] = strategy
    return strategy


def _resolve_symbol(doc, profile, cache):
    """Return the FamilySymbol the profile wants to place, or None.

    None means "use Revit's default for this category" - place_tag
    falls through to category-default placement. Lookup order:
    cached, then symbol id from profile.tag_symbol_id, then first
    available symbol for the profile's category.
    """
    if profile.key in cache:
        return cache[profile.key]
    symbols = tagging_engine.collect_tag_symbols(doc, profile.category_key)
    if not symbols:
        cache[profile.key] = None
        return None
    chosen = None
    if profile.tag_symbol_id is not None:
        for s in symbols:
            try:
                if s.Id.IntegerValue == profile.tag_symbol_id:
                    chosen = s
                    break
            except Exception:
                continue
    if chosen is None:
        chosen = symbols[0]
    cache[profile.key] = chosen
    return chosen
