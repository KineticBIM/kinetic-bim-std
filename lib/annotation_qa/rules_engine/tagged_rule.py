# -*- coding: utf-8 -*-
"""Filter rule for elements that already have a tag in the current scope.

The tagged-ids set is computed once by qa_engine.scan and dropped into
the per-element context, so the rule does not hit the model itself.
"""

from bim_core.rules_engine.base import Rule


class NotAlreadyTaggedRule(Rule):
    name = "skip_already_tagged"

    def passes(self, element, context):
        tagged_ids = context.get("tagged_ids") or ()
        try:
            eid = element.Id.IntegerValue
        except Exception:
            return True, None
        if eid in tagged_ids:
            return False, "already tagged"
        return True, None
