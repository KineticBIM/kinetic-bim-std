# -*- coding: utf-8 -*-
"""CardinalOffsetStrategy - tag offset along view-plane cardinal axes.

Used for two cases:

    a) profile.placement_mode == "adjacent" AND the host has no usable
       run direction - typically point-based families (equipment,
       sprinklers, fittings, fixtures).
    b) profile.placement_mode == "adjacent" AND profile.preferred_side
       is an explicit direction ("above" / "below" / "left" / "right"),
       regardless of host kind. The user has overridden the
       perpendicular-to-run default with a view-plane preference, so
       we honour it.

Candidate ordering differs by branch:

    Explicit side (above / below / left / right):
        Tiered priority. The chosen direction is tried at increasing
        offset multipliers first so a mild clash is escaped by pushing
        further along the same axis rather than ditching the side the
        user asked for. Only when the chosen direction is genuinely
        impossible do we fall through to neighbouring directions, and
        the opposite direction is reserved as a terminal fallback.

        Tier 1: chosen direction   x {1, 1.5, 2, 2.5, 3}  (5)
        Tier 2: chosen +-45 deg    x {1, 1.5, 2}          (6)
        Tier 3: chosen +-90 deg    x {1, 1.5}             (4)
        Tier 4: opposite +-45 deg  x {1}                  (2)
        Tier 5: opposite direction x {1}                  (1)
        Total: 18 candidates.

    Auto:
        Eight directions starting at above-right (the most common
        documentation-convention position for point families),
        rotating counter-clockwise, each at 1x then 1.5x offset_mm.
        16 candidates.

In both branches the clash loop terminates at the first clean
candidate; in practice the first 2-3 cover most placements.
"""

from bim_core.core import geometry_utils

from annotation_qa.placement_strategies.base import PlacementStrategy
from annotation_qa.profiles import (
    PLACEMENT_SIDE_ABOVE,
    PLACEMENT_SIDE_BELOW,
    PLACEMENT_SIDE_LEFT,
    PLACEMENT_SIDE_RIGHT,
)


# Eight directions in (right_axis_weight, up_axis_weight) form,
# counter-clockwise starting at "right". Diagonals use sqrt(2)/2 so
# every direction is a unit vector; the offset_mm magnitude is applied
# uniformly.
_SQRT2_INV = 2.0 ** -0.5
_OFFSETS_8 = (
    (1.0,        0.0),         # right
    (_SQRT2_INV, _SQRT2_INV),  # above-right
    (0.0,        1.0),         # above
    (-_SQRT2_INV, _SQRT2_INV), # above-left
    (-1.0,       0.0),         # left
    (-_SQRT2_INV, -_SQRT2_INV),# below-left
    (0.0,        -1.0),        # below
    (_SQRT2_INV, -_SQRT2_INV), # below-right
)

# Index into _OFFSETS_8 for each explicit side.
_SIDE_TO_INDEX = {
    PLACEMENT_SIDE_RIGHT: 0,
    PLACEMENT_SIDE_ABOVE: 2,
    PLACEMENT_SIDE_LEFT:  4,
    PLACEMENT_SIDE_BELOW: 6,
}

# Auto-mode anchor: above-right is the most common
# documentation-convention tag position for point families.
_AUTO_START_INDEX = 1

# Auto-mode distances (uniform per-direction sweep).
_AUTO_DISTANCE_MULTIPLIERS = (1.0, 1.5)

# Distance multipliers per tier when an explicit side is chosen.
_TIER_CHOSEN_MULTS    = (1.0, 1.5, 2.0, 2.5, 3.0)
_TIER_NEAR_MULTS      = (1.0, 1.5, 2.0)
_TIER_ORTHO_MULTS     = (1.0, 1.5)
_TIER_OPPOSITE_NEAR_MULTS = (1.0,)
_TIER_OPPOSITE_MULTS  = (1.0,)


def _tiered_sequence(start_idx):
    """Yield (direction_index, distance_multiplier) tuples in priority
    order for an explicit-side request.

    See module docstring for the tier definitions and counts.
    """
    # _OFFSETS_8 is in CCW order starting from RIGHT, so +1 in the index
    # rotates one step counter-clockwise on screen, -1 clockwise. The
    # ccw / cw naming here is rotation around the index cycle, not
    # screen-space left/right.
    n = len(_OFFSETS_8)
    ccw_45 = (start_idx + 1) % n
    cw_45  = (start_idx - 1) % n
    ccw_90 = (start_idx + 2) % n
    cw_90  = (start_idx - 2) % n
    ccw_135 = (start_idx + 3) % n
    cw_135  = (start_idx - 3) % n
    opposite = (start_idx + 4) % n

    # Tier 1: chosen direction, escalating distance.
    for mult in _TIER_CHOSEN_MULTS:
        yield start_idx, mult
    # Tier 2: +-45 deg neighbours.
    for mult in _TIER_NEAR_MULTS:
        yield ccw_45, mult
        yield cw_45,  mult
    # Tier 3: +-90 deg orthogonals.
    for mult in _TIER_ORTHO_MULTS:
        yield ccw_90, mult
        yield cw_90,  mult
    # Tier 4: opposite +-45 deg (last-resort lateral).
    for mult in _TIER_OPPOSITE_NEAR_MULTS:
        yield ccw_135, mult
        yield cw_135,  mult
    # Tier 5: opposite direction (terminal fallback).
    for mult in _TIER_OPPOSITE_MULTS:
        yield opposite, mult


def _auto_sequence():
    """Yield (direction_index, distance_multiplier) tuples for auto
    mode: all 8 directions at 1.0x, then all 8 at 1.5x.
    """
    n = len(_OFFSETS_8)
    order = [(_AUTO_START_INDEX + i) % n for i in range(n)]
    for mult in _AUTO_DISTANCE_MULTIPLIERS:
        for idx in order:
            yield idx, mult


class CardinalOffsetStrategy(PlacementStrategy):

    key = "cardinal_offset"
    label = "Cardinal offset"

    def propose_positions(self, view, element, profile):
        origin = geometry_utils.element_origin(element)
        if origin is None:
            return

        right_v = view.RightDirection
        up_v    = view.UpDirection
        offset_ft = geometry_utils.mm_to_internal(profile.offset_mm)

        # Explicit side -> tiered escape from chosen direction. Anything
        # not in _SIDE_TO_INDEX (PLACEMENT_SIDE_AUTO, or any future value
        # we have not mapped) falls through to the uniform auto sweep.
        start = _SIDE_TO_INDEX.get(profile.preferred_side)
        if start is None:
            sequence = _auto_sequence()
        else:
            sequence = _tiered_sequence(start)

        for idx, mult in sequence:
            rx, uy = _OFFSETS_8[idx]
            direction = right_v.Multiply(rx) + up_v.Multiply(uy)
            yield origin + direction.Multiply(offset_ft * mult)
