# -*- coding: utf-8 -*-
"""Placement strategy registry + per-profile factory.

REGISTRY maps strategy_key -> singleton strategy and exists for
parity with dimension_qa.target_strategies. The primary public entry
point is get_for(profile), which returns the correct strategy for a
given TaggingProfile by inspecting both placement_mode AND
preferred_side AND the host category's geometry_kind:

    placement_mode == "on_element"
        -> OnElementStrategy  (single candidate at element_origin)

    placement_mode == "adjacent"
        preferred_side != "auto"
            -> CardinalOffsetStrategy  (explicit cardinal direction
               wins over curve-perpendicular, regardless of host kind)
        preferred_side == "auto" AND category geometry_kind == "linear"
            -> PerpendicularOffsetStrategy
        preferred_side == "auto" AND category geometry_kind != "linear"
            -> CardinalOffsetStrategy

Any unrecognised combination collapses to OnElementStrategy so the
engine still places something rather than silently producing zero
candidates - the rule engine has already accepted the element by the
time placement runs.
"""

from bim_core.core import category_config

from annotation_qa.profiles import (
    PLACEMENT_MODE_ADJACENT,
    PLACEMENT_MODE_ON_ELEMENT,
    PLACEMENT_SIDE_AUTO,
)

from annotation_qa.placement_strategies.on_element import OnElementStrategy
from annotation_qa.placement_strategies.perpendicular_offset import (
    PerpendicularOffsetStrategy,
)
from annotation_qa.placement_strategies.cardinal_offset import (
    CardinalOffsetStrategy,
)


_ON_ELEMENT           = OnElementStrategy()
_PERPENDICULAR_OFFSET = PerpendicularOffsetStrategy()
_CARDINAL_OFFSET      = CardinalOffsetStrategy()


REGISTRY = {
    OnElementStrategy.key:           _ON_ELEMENT,
    PerpendicularOffsetStrategy.key: _PERPENDICULAR_OFFSET,
    CardinalOffsetStrategy.key:      _CARDINAL_OFFSET,
}


def get(strategy_key):
    """Direct registry lookup. Returns None for unknown keys."""
    return REGISTRY.get(strategy_key)


def get_for(profile):
    """Resolve a strategy for a TaggingProfile.

    Always returns a strategy - on_element is the safe terminal
    fallback. See module docstring for the routing table.
    """
    if profile.placement_mode != PLACEMENT_MODE_ADJACENT:
        return _ON_ELEMENT

    # Adjacent placement. Explicit cardinal direction wins.
    if profile.preferred_side != PLACEMENT_SIDE_AUTO:
        return _CARDINAL_OFFSET

    # side == "auto": pick perpendicular for linear hosts, cardinal
    # otherwise. Unknown / missing category config -> on_element.
    cfg = category_config.get_safe(profile.category_key)
    if cfg is None:
        return _ON_ELEMENT
    if cfg.geometry_kind == "linear":
        return _PERPENDICULAR_OFFSET
    return _CARDINAL_OFFSET
