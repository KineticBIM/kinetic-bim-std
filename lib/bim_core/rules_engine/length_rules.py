# -*- coding: utf-8 -*-
"""Length-based filter rules."""

from bim_core.core import geometry_utils
from bim_core.rules_engine.base import Rule


_CACHE_KEY = "length_mm"


def _cached_length(element, context):
    if _CACHE_KEY in context:
        return context[_CACHE_KEY]
    length = geometry_utils.element_length_mm(element)
    context[_CACHE_KEY] = length
    return length


class MinimumLengthRule(Rule):
    name = "min_length"

    def __init__(self, min_length_mm):
        self.min_length_mm = float(min_length_mm)

    def passes(self, element, context):
        length_mm = _cached_length(element, context)
        if length_mm is None:
            return False, "no curve length"
        if length_mm < self.min_length_mm:
            return False, "below min length ({0:.0f}mm < {1:.0f}mm)".format(
                length_mm, self.min_length_mm)
        return True, None


class MaximumLengthRule(Rule):
    name = "max_length"

    def __init__(self, max_length_mm):
        # None means "no upper bound" - rule short-circuits to pass.
        self.max_length_mm = (float(max_length_mm)
                              if max_length_mm is not None else None)

    def passes(self, element, context):
        if self.max_length_mm is None:
            return True, None
        length_mm = _cached_length(element, context)
        if length_mm is None:
            # Don't double-fail an element that the min-length rule
            # already handled - let it through here.
            return True, None
        if length_mm > self.max_length_mm:
            return False, "above max length ({0:.0f}mm > {1:.0f}mm)".format(
                length_mm, self.max_length_mm)
        return True, None
