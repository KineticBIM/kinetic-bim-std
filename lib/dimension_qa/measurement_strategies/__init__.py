# -*- coding: utf-8 -*-
"""Measurement reference strategy registry.

REGISTRY maps (category_key, strategy_key) -> singleton strategy.
applicable_for(category_key) returns the ordered (key, label) list
the per-row dropdown shows, so each subcategory exposes only the
references that make geometric sense.

Adding a strategy:
    1. Subclass MeasurementReferenceStrategy in face_strategies.py
       (or a new module).
    2. Add `("category_key", "strategy_key"): StrategyInstance()` to
       REGISTRY below for every category that exposes it.
    3. Add the strategy_key to ORDER_BY_CATEGORY for the desired
       display position.

The dispatcher in dimensioning_engine.py looks up
REGISTRY[(profile.category_key, profile.measurement_reference)]
each time it scans an element; the strategy returns either
(Reference, anchor_xyz) or (None, error_string).
"""

from dimension_qa.measurement_strategies.centreline import CentrelineStrategy
from dimension_qa.measurement_strategies.face_strategies import (
    TopFaceStrategy, BottomFaceStrategy,
    OutsideFaceStrategy, InsideFaceStrategy,
    OutsideEdgeStrategy, InsideEdgeStrategy,
    InvertLevelStrategy,
)


# Singletons - strategies are stateless.
_CENTRELINE      = CentrelineStrategy()
_TOP             = TopFaceStrategy()
_BOTTOM          = BottomFaceStrategy()
_OUTSIDE_FACE    = OutsideFaceStrategy()
_INSIDE_FACE     = InsideFaceStrategy()
_OUTSIDE_EDGE    = OutsideEdgeStrategy()
_INSIDE_EDGE     = InsideEdgeStrategy()
_INVERT          = InvertLevelStrategy()


# (category_key, strategy_key) -> strategy instance.
# The strategy_key is the JSON id stored on a profile and shown in
# the per-row dropdown via its label.
REGISTRY = {
    # Cable Trays - 5 strategies per spec.
    ("cable_tray", "centreline"):    _CENTRELINE,
    ("cable_tray", "outside_edge"):  _OUTSIDE_EDGE,
    ("cable_tray", "inside_edge"):   _INSIDE_EDGE,
    ("cable_tray", "top"):           _TOP,
    ("cable_tray", "bottom"):        _BOTTOM,

    # Conduits - 2 strategies per spec.
    ("conduit", "centreline"):       _CENTRELINE,
    ("conduit", "outside_edge"):     _OUTSIDE_EDGE,

    # Ducts - 5 strategies per spec.
    ("duct", "centreline"):          _CENTRELINE,
    ("duct", "outside_face"):        _OUTSIDE_FACE,
    ("duct", "inside_face"):         _INSIDE_FACE,
    ("duct", "top"):                 _TOP,
    ("duct", "bottom"):              _BOTTOM,

    # Pipes - 5 strategies per spec.
    ("pipe", "centreline"):          _CENTRELINE,
    ("pipe", "outside_face"):        _OUTSIDE_FACE,
    ("pipe", "invert_level"):        _INVERT,
    ("pipe", "top"):                 _TOP,
    ("pipe", "bottom"):              _BOTTOM,
}


# Display order per category - drives the dropdown ordering. Always
# Centreline first (the safe default).
ORDER_BY_CATEGORY = {
    "cable_tray": ("centreline", "outside_edge", "inside_edge",
                   "top", "bottom"),
    "conduit":    ("centreline", "outside_edge"),
    "duct":       ("centreline", "outside_face", "inside_face",
                   "top", "bottom"),
    "pipe":       ("centreline", "outside_face", "invert_level",
                   "top", "bottom"),
}


def get(category_key, strategy_key):
    """Return the strategy for (category_key, strategy_key), or None
    if the pair isn't registered. Engine treats None as 'unknown
    strategy - skip with reason'."""
    return REGISTRY.get((category_key, strategy_key))


def applicable_for(category_key):
    """Return the ordered (strategy_key, label) tuples for the per-row
    dropdown. Empty when the category isn't a v1 linear MEP type."""
    keys = ORDER_BY_CATEGORY.get(category_key, ())
    out = []
    for k in keys:
        s = REGISTRY.get((category_key, k))
        if s is not None:
            out.append((s.key, s.label))
    return out


def default_for(category_key):
    """The strategy_key the dropdown opens on for a fresh row -
    Centreline when supported, otherwise the first applicable."""
    options = applicable_for(category_key)
    if not options:
        return None
    for key, _ in options:
        if key == "centreline":
            return key
    return options[0][0]
