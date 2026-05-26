# -*- coding: utf-8 -*-
"""PlacementStrategy - decides WHERE a tag's head sits in the view.

Each strategy is a stateless singleton that yields one or more
candidate XYZ positions, in preferred order, for a given (view,
element, profile) triple. The Auto Tag engine places the first
candidate it can without clash; if every candidate clashes it falls
back to the lowest-scoring one and records the placement quality on
the report row.

Strategies are intentionally clash-blind. Knowing *where* to try is
their job; deciding *whether* a candidate clashes is the engine's
job, via the ClashIndex. This split keeps each strategy short and
unit-testable, and lets new strategies appear without touching the
clash code.

This module imports only standard library names. Concrete strategies
that need Revit's XYZ / view types live in their own files and import
the Revit API there.
"""


class PlacementStrategy(object):

    key = "base"
    label = "Base"

    @classmethod
    def applies_to(cls, category_key):  # noqa: ARG003
        """True when the strategy makes sense for this category.

        The factory uses this to gate which strategies show up in the
        UI dropdown for a given binding. v1 strategies are either
        category-agnostic or gated by geometry_kind via the factory,
        so the default returns True.
        """
        return True

    def propose_positions(self, view, element, profile):
        """Yield XYZ candidates in preferred order.

        view     - the Revit View the tag will be placed in. Strategies
                   that need view-plane axes read view.RightDirection /
                   view.UpDirection / view.ViewDirection.
        element  - the host element being tagged.
        profile  - the TaggingProfile that owns this placement. Carries
                   offset_mm and preferred_side; strategies should
                   honour both.

        Implementations must yield at least one XYZ. If the strategy
        cannot resolve a position at all (e.g. element has no origin),
        it should yield nothing - the engine will skip the element and
        record the cause in the report.
        """
        raise NotImplementedError
