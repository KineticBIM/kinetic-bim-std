# -*- coding: utf-8 -*-
"""FamilyNamePatternRule.

Substring match against an element's family/type/instance names. Used
to peel off discipline-specific subsets that share a Revit category -
Fire Dampers live inside OST_DuctAccessory alongside regular accessories,
and the only practical way to identify them in mixed projects is by
family name.

Patterns are stored lowercase; matching is lowercase substring against
each of family name, symbol name, and instance name. Caches the
concatenated lookup string on ctx for reuse.
"""

from bim_core.rules_engine.base import Rule


class FamilyNamePatternRule(Rule):

    name = "family_name_pattern"

    def __init__(self, patterns):
        self.patterns = tuple(p.lower() for p in (patterns or ()))

    def passes(self, element, context):
        if not self.patterns:
            return True, None

        hay = context.get("family_name_haystack")
        if hay is None:
            hay = _haystack(element)
            context["family_name_haystack"] = hay

        for pat in self.patterns:
            if pat in hay:
                return True, None

        return False, "name does not match any of {0}".format(list(self.patterns))


def _haystack(element):
    parts = []
    # Family name (most useful).
    try:
        sym = getattr(element, "Symbol", None)
        if sym is not None:
            fam = getattr(sym, "Family", None)
            if fam is not None:
                parts.append(getattr(fam, "Name", "") or "")
            parts.append(getattr(sym, "Name", "") or "")
    except Exception:
        pass
    # Instance name.
    try:
        parts.append(element.Name or "")
    except Exception:
        pass
    return " ".join(p for p in parts if p).lower()
