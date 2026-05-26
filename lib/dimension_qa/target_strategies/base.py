# -*- coding: utf-8 -*-
"""ReferenceTargetStrategy - decides WHAT a dimension measures TO.

A target strategy returns the (Reference, anchor_xyz) pair for the
"other end" of the dimension. Examples (v1 ships only the first):

    NearestGridStrategy       - the closest perpendicular grid line
    NearestWallStrategy       - the closest wall in the view (v2)
    NearestColumnStrategy     - the closest column in the view (v2)
    SelectedReferenceStrategy - a reference the user picks (v2)

Strategies are stateless singletons registered in
target_strategies/__init__.py keyed by strategy_key. The dimensioning
engine calls strategy.get_target(doc, view, element_anchor) once per
element; failures return (None, "reason") and the engine skips the
element.
"""


class ReferenceTargetStrategy(object):

    key = "base"
    label = "Base"

    @classmethod
    def applies_to(cls, category_key):
        """True when the strategy makes sense for this category. v1
        uses category-agnostic targets; the hook is here for v2 when
        a target may only apply to e.g. linear runs."""
        return True

    def get_target(self, doc, view, element, element_anchor):
        """Return (Reference, anchor_xyz) or (None, error_string).

        element is supplied so direction-aware target strategies (e.g.
        nearest perpendicular grid) can read its run direction.
        element_anchor is the point the measurement reference picked,
        used by distance-minimising strategies.
        """
        raise NotImplementedError
