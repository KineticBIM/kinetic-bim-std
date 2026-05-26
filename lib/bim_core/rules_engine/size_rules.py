# -*- coding: utf-8 -*-
"""Per-category size filter rule.

A single SizeRule handles every category. The constraint dict tells it
which dimensions to enforce. core.parameter_utils.CATEGORY_DIMENSIONS
gives the list of valid keys per category.

Constraint dict shape:
    {"width_mm_min": 100.0, "width_mm_max": None, ...}
A value of None means "no bound" - the rule treats it as absent.
"""

from bim_core.core import parameter_utils
from bim_core.rules_engine.base import Rule


class SizeRule(Rule):
    name = "size"

    def __init__(self, category_key, constraints):
        self.category_key = category_key
        self.constraints = dict(constraints) if constraints else {}

    def passes(self, element, context):
        dims = parameter_utils.CATEGORY_DIMENSIONS.get(self.category_key, ())
        for dim in dims:
            min_v = self.constraints.get("{0}_mm_min".format(dim))
            max_v = self.constraints.get("{0}_mm_max".format(dim))
            if min_v is None and max_v is None:
                continue
            size_mm = parameter_utils.get_size_mm(
                element, self.category_key, dim)
            if size_mm is None:
                # Parameter missing - prefer "don't false-reject" over a
                # confusing failure. The audit log still has the element.
                continue
            label = parameter_utils.DIMENSION_LABELS.get(dim, dim).lower()
            if min_v is not None and size_mm < min_v:
                return False, "{0} {1:.0f}mm < min {2:.0f}mm".format(
                    label, size_mm, min_v)
            if max_v is not None and size_mm > max_v:
                return False, "{0} {1:.0f}mm > max {2:.0f}mm".format(
                    label, size_mm, max_v)
        return True, None
