# -*- coding: utf-8 -*-
"""Per-category size parameter access.

Each linear MEP category exposes its own "size" BuiltInParameter set:
cable tray width, conduit diameter, duct width + height, pipe diameter.
This module centralises that mapping so rule code and UI labels never
have to remember which parameter applies to which category.

To support a new dimension for an existing category, or a new category
entirely:
    1. Add an entry to _SIZE_PARAM_MAP.
    2. Add the dimension key to CATEGORY_DIMENSIONS.
    3. Add a human label to DIMENSION_LABELS (used by the UI).
SizeRule + the UI panel pick it up automatically.
"""

from Autodesk.Revit.DB import BuiltInParameter

from bim_core.core import category_config, geometry_utils


# (category_key, dimension) -> BuiltInParameter. Only categories that
# expose a size dimension need an entry here. Point-based categories
# (equipment, fixtures, accessories, fittings, sprinklers, devices)
# have empty size_dimensions in their CategoryConfig, so they never
# look anything up here.
_SIZE_PARAM_MAP = {
    ("cable_tray", "width"):    BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM,
    ("conduit",    "diameter"): BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM,
    ("duct",       "width"):    BuiltInParameter.RBS_CURVE_WIDTH_PARAM,
    ("duct",       "height"):   BuiltInParameter.RBS_CURVE_HEIGHT_PARAM,
    # Flex ducts are virtually always round in this practice's models;
    # round flex ducts carry RBS_CURVE_DIAMETER_PARAM. Rectangular flex
    # would need a follow-up (separate dimension keys).
    ("flex_duct",  "diameter"): BuiltInParameter.RBS_CURVE_DIAMETER_PARAM,
    ("pipe",       "diameter"): BuiltInParameter.RBS_PIPE_DIAMETER_PARAM,
}


# Which dimensions a category exposes - sourced from the category
# registry so adding a category there flows through to the size rule +
# UI automatically. Categories with no size dimensions appear here with
# an empty tuple.
CATEGORY_DIMENSIONS = {
    k: cfg.size_dimensions for k, cfg in category_config.REGISTRY.items()
}


# Pretty label for each dimension key. SizeRule uses it for skip reasons;
# the UI uses it for input labels.
DIMENSION_LABELS = {
    "width":    "Width",
    "height":   "Height",
    "diameter": "Diameter",
}


def get_size_mm(element, category_key, dimension):
    """Read the named size parameter in mm. None if unknown or unset.

    Returns None (not 0) when a parameter is missing rather than raising,
    so SizeRule can choose to skip rather than false-reject the element.
    """
    bip = _SIZE_PARAM_MAP.get((category_key, dimension))
    if bip is None:
        return None
    p = element.get_Parameter(bip)
    if p is None:
        return None
    try:
        ft = p.AsDouble()
    except Exception:
        return None
    return geometry_utils.internal_to_mm(ft)
