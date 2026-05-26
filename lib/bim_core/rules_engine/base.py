# -*- coding: utf-8 -*-
"""Rule + RulePipeline base classes."""


class Rule(object):
    """Abstract filter rule.

    Subclasses override .passes() and set .name. The pipeline calls
    .passes(element, context) once per element. context is a per-element
    mutable dict the engine pre-seeds with view / doc / category_key /
    tagged_ids / options - rules may also cache computed values into it
    (e.g. element_length_mm) so peer rules can reuse the result.
    """
    name = "rule"

    def passes(self, element, context):
        """Return (bool_passes, reason_or_None)."""
        raise NotImplementedError


class RulePipeline(object):
    """Sequential rule evaluator with short-circuit semantics.

    The first failing rule wins. Its name + reason are returned so the
    QA report can tally failures by rule and the log can blame the right
    filter.
    """

    def __init__(self, rules):
        self.rules = list(rules) if rules else []

    def evaluate(self, element, context):
        """Return (passes, failing_reason, failing_rule_name).

        On success, returns (True, None, None).
        """
        for rule in self.rules:
            ok, reason = rule.passes(element, context)
            if not ok:
                return False, reason, rule.name
        return True, None, None

    def names(self):
        return [r.name for r in self.rules]
