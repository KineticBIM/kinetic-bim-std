# -*- coding: utf-8 -*-
"""Reference target strategy registry.

REGISTRY maps strategy_key -> singleton strategy. v1 ships only
NearestGridStrategy; the registry shape exists so v2 strategies
(NearestWall, NearestColumn, SelectedReference) plug in without
touching the engine.

ORDER lists the keys in the order the per-row dropdown shows them.
Future v2 entries should be appended in priority order.
"""

from dimension_qa.target_strategies.nearest_grid import NearestGridStrategy


_NEAREST_GRID = NearestGridStrategy()


REGISTRY = {
    "nearest_grid": _NEAREST_GRID,
}


ORDER = ("nearest_grid",)


def get(strategy_key):
    return REGISTRY.get(strategy_key)


def applicable_for(category_key):  # noqa: ARG001 - v1 targets are universal
    """Return ordered (key, label) tuples for the dropdown. v1 targets
    don't gate on category but the hook is here so v2 can expose
    Nearest Wall only on horizontal MEP runs etc."""
    out = []
    for key in ORDER:
        s = REGISTRY.get(key)
        if s is None:
            continue
        if not s.applies_to(category_key):
            continue
        out.append((s.key, s.label))
    return out


def default_target():
    """Default target for fresh profiles."""
    return "nearest_grid"
