# -*- coding: utf-8 -*-
"""Filter rule for elements that already have a dimension in the
current view.

The dimensioned-ids set is computed once by dimensioning_engine.scan
and dropped into the per-element context, so the rule does not hit
the model itself.
"""

from bim_core.rules_engine.base import Rule


class NotAlreadyDimensionedRule(Rule):
    name = "skip_already_dimensioned"

    def passes(self, element, context):
        dimensioned_ids = context.get("dimensioned_ids") or ()
        try:
            eid = element.Id.IntegerValue
        except Exception:
            return True, None
        if eid in dimensioned_ids:
            return False, "already dimensioned"
        return True, None
