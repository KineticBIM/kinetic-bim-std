# -*- coding: utf-8 -*-
"""Auto Tag rule engine.

A rule is a small class with a .passes(element, context) method that
returns (ok, reason). The pipeline runs rules in order and short-
circuits on the first failure - the failing rule's reason becomes the
element's skip_reason and its name is recorded for the report.

Adding a new filter:
    1. Drop a Rule subclass into this package.
    2. Wire it into build_pipeline() below, reading its config from
       the TaggingProfile (plus the profile's binding for binding-
       scoped filters like system classification / family name).
    3. Add the rule key to the relevant CategoryConfig's
       supported_rules so the pipeline only fires it where it makes
       sense.

The qa_engine consumes only build_pipeline; it has no knowledge of
which specific rules exist. New rules ship without touching qa_engine.
"""

from bim_core.rules_engine import (
    Rule, RulePipeline,
    MinimumLengthRule, MaximumLengthRule,
    HorizontalRule, VerticalRule,
    SizeRule,
    VisibilityRule,
    SystemClassificationRule,
    FamilyNamePatternRule,
)
from annotation_qa.rules_engine.tagged_rule import NotAlreadyTaggedRule


def build_pipeline(profile, scope_is_active_view=True):
    """Compose a RulePipeline from a TaggingProfile.

    Every rule check is gated by the profile's category capabilities
    (profile.supports("min_length") etc.). Linear MEP categories run
    the full length / orientation / size pipeline. Point categories
    (equipment, fittings, fixtures, sprinklers, devices, generic
    models) get a much shorter pipeline: any binding filters +
    visibility + skip_already_tagged.

    scope_is_active_view:
        True  - active-view scope; include VisibilityRule (defense in
                depth - the collector excludes IsHidden elements but
                can miss category-hidden cases).
        False - whole-model scope; qa_engine handles "is this in the
                active view?" via the in_active_view flag.

    Rule order is significant: cheap rules first to short-circuit
    expensive ones. System classification + family name run before
    length/orientation so a non-matching element is rejected before
    we spend geometry on it. NotAlreadyTaggedRule runs last so its
    reason is distinguishable from "would never tag" reasons above.

    The user can leave min_length blank (None) to mean "no lower
    bound" - in that case MinimumLengthRule is omitted entirely
    rather than defaulted, so the report shows no exclusions for it.
    """
    rules = []
    cfg = profile.cfg
    if cfg is None:
        return RulePipeline(rules)

    binding = profile.binding

    # --- Binding filters (cheap, identity-shaped) ------------------------
    if (binding is not None
            and binding.has_system_filter()
            and profile.supports("system_classification")):
        rules.append(SystemClassificationRule(binding.system_classifications))
    if (binding is not None
            and binding.has_family_filter()
            and profile.supports("family_name_pattern")):
        rules.append(FamilyNamePatternRule(binding.family_name_patterns))

    # --- Length -----------------------------------------------------------
    if profile.supports("min_length") and profile.min_length_mm is not None:
        rules.append(MinimumLengthRule(profile.min_length_mm))
    if profile.supports("max_length") and profile.max_length_mm is not None:
        rules.append(MaximumLengthRule(profile.max_length_mm))

    # --- Orientation ------------------------------------------------------
    tol = profile.orientation_tol_deg
    if profile.supports("horizontal_only") and profile.horizontal_only:
        rules.append(HorizontalRule(tolerance_deg=tol))
    elif profile.supports("vertical_only") and profile.vertical_only:
        rules.append(VerticalRule(tolerance_deg=tol))

    # --- Size -------------------------------------------------------------
    if profile.supports("size") and cfg.size_dimensions:
        if any(v is not None for v in profile.size_filters.values()):
            rules.append(SizeRule(profile.category_key, profile.size_filters))

    # --- Visibility (active-view scope only) ------------------------------
    if scope_is_active_view and profile.supports("visibility"):
        rules.append(VisibilityRule())

    # --- Already tagged ---------------------------------------------------
    if (profile.supports("skip_already_tagged")
            and profile.skip_already_tagged):
        rules.append(NotAlreadyTaggedRule())

    return RulePipeline(rules)
