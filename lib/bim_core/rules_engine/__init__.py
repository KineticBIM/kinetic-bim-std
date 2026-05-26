# -*- coding: utf-8 -*-
"""Shared rule classes.

This package only exposes the *primitives*: the Rule + RulePipeline
base classes and the generic shape-of-an-element rules every tool
reuses. The composition step (which rules to chain together for a
given scan) lives in each tool's own rules_engine/__init__.py
(annotation_qa, dimension_qa, ...).

Re-exporting the classes here lets callers import them with
`from bim_core.rules_engine import Rule, RulePipeline` instead of
walking the submodule path.
"""

from bim_core.rules_engine.base import Rule, RulePipeline
from bim_core.rules_engine.length_rules import (
    MinimumLengthRule, MaximumLengthRule,
)
from bim_core.rules_engine.orientation_rules import (
    HorizontalRule, VerticalRule,
)
from bim_core.rules_engine.size_rules import SizeRule
from bim_core.rules_engine.visibility_rules import VisibilityRule
from bim_core.rules_engine.system_classification_rule import (
    SystemClassificationRule,
)
from bim_core.rules_engine.family_name_rule import FamilyNamePatternRule
