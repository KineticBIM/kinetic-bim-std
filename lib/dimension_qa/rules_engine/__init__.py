# -*- coding: utf-8 -*-
"""Auto Dimension rule pipeline composition.

build_pipeline(profile, scope_is_active_view) returns a RulePipeline
composed from one DimensioningProfile. Same shape as Auto Tag's
build_pipeline, different rule set: NotAlreadyDimensionedRule replaces
NotAlreadyTaggedRule; SizeRule isn't shown in the v1 UI but composes
the same way if profiles ever carry size_filters.

Rule order is significant: cheap rules first to short-circuit
expensive ones. NotAlreadyDimensionedRule runs last so its reason is
distinguishable from "would never dim" reasons above it.
"""

from bim_core.rules_engine import (
    Rule, RulePipeline,
    MinimumLengthRule, MaximumLengthRule,
    HorizontalRule, VerticalRule,
    VisibilityRule,
    SystemClassificationRule,
    FamilyNamePatternRule,
)
from dimension_qa.rules_engine.already_dimensioned_rule import (
    NotAlreadyDimensionedRule,
)


def build_pipeline(profile, scope_is_active_view=True):
    """Compose a RulePipeline from one DimensioningProfile."""
    rules = []
    cfg = profile.cfg
    if cfg is None:
        return RulePipeline(rules)
    binding = profile.binding

    if (binding is not None
            and binding.has_system_filter()
            and profile.supports("system_classification")):
        rules.append(SystemClassificationRule(binding.system_classifications))
    if (binding is not None
            and binding.has_family_filter()
            and profile.supports("family_name_pattern")):
        rules.append(FamilyNamePatternRule(binding.family_name_patterns))

    if profile.supports("min_length") and profile.min_length_mm is not None:
        rules.append(MinimumLengthRule(profile.min_length_mm))
    if profile.supports("max_length") and profile.max_length_mm is not None:
        rules.append(MaximumLengthRule(profile.max_length_mm))

    tol = profile.orientation_tol_deg
    if profile.supports("horizontal_only") and profile.horizontal_only:
        rules.append(HorizontalRule(tolerance_deg=tol))
    elif profile.supports("vertical_only") and profile.vertical_only:
        rules.append(VerticalRule(tolerance_deg=tol))

    if scope_is_active_view and profile.supports("visibility"):
        rules.append(VisibilityRule())

    if profile.skip_already_dimensioned:
        rules.append(NotAlreadyDimensionedRule())

    return RulePipeline(rules)
