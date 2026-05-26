# -*- coding: utf-8 -*-
"""SystemClassificationRule.

Filters elements by their MEP system classification (e.g. SupplyHydronic,
DomesticColdWater, FireProtectWet). Used to disambiguate OST_PipeCurves /
OST_PipeAccessory / OST_PipeFitting across the Mechanical, Hydraulic and
Fire disciplines - the same Revit category appears under several
disciplines with disjoint classification sets.

Reads via core.system_classification.read_classification, which never
raises. The rule caches the classification string on ctx so peer rules
and the QA report can reuse it without a second API hit.
"""

from bim_core.core import system_classification
from bim_core.rules_engine.base import Rule


class SystemClassificationRule(Rule):

    name = "system_classification"

    def __init__(self, allowed_classifications):
        # frozenset()/None/[] all mean "no filter" (rule still runs but
        # always passes; in practice build_pipeline skips construction
        # entirely in that case).
        self.allowed = (frozenset(allowed_classifications)
                        if allowed_classifications else frozenset())

    def passes(self, element, context):
        cls = context.get("system_classification", _MISSING)
        if cls is _MISSING:
            cls = system_classification.read_classification(element)
            context["system_classification"] = cls

        if not self.allowed:
            return True, None

        if cls is None:
            return False, "no MEP system classification"

        if cls not in self.allowed:
            return False, "system '{0}' not in {1}".format(
                cls, sorted(self.allowed))

        return True, None


_MISSING = object()
