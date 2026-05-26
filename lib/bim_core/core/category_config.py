# -*- coding: utf-8 -*-
"""Category capability registry.

Every Revit category Auto Tag knows about is described by one
CategoryConfig. The config carries:

    key               stable string used in option dicts + JSON configs
    label             human-readable name shown in the UI
    bic               BuiltInCategory for the host elements
    tag_bic           BuiltInCategory for the matching IndependentTag
    geometry_kind     "linear" (LocationCurve, supports length /
                      orientation / midpoint placement) or "point"
                      (LocationPoint, no length, tag placed at origin)
    supported_rules   frozenset of rule keys that apply to this
                      category. The rule pipeline skips inapplicable
                      rules; the UI hides controls that drive them.
    size_dimensions   tuple of dimension keys ("width", "diameter", ...)
                      this category exposes - drives the size sub-panel
                      and SizeRule. Empty tuple = no size filters.

Adding a new category is a one-stop edit: register it here, supply
matching BuiltInParameter entries in parameter_utils._SIZE_PARAM_MAP if
it has size dimensions, and (if you want a custom rule that doesn't
exist yet) write a Rule subclass and reference it from supported_rules.
"""

from Autodesk.Revit.DB import BuiltInCategory


# ---------------------------------------------------------------------------
# CategoryConfig
# ---------------------------------------------------------------------------

class CategoryConfig(object):

    def __init__(self, key, label, bic, tag_bic, geometry_kind,
                 supported_rules, size_dimensions=()):
        if geometry_kind not in ("linear", "point"):
            raise ValueError(
                "geometry_kind must be 'linear' or 'point', got {0!r}".format(
                    geometry_kind))
        self.key = key
        self.label = label
        self.bic = bic
        self.tag_bic = tag_bic
        self.geometry_kind = geometry_kind
        self.supported_rules = frozenset(supported_rules)
        self.size_dimensions = tuple(size_dimensions)

    def supports(self, rule_key):
        """True when the named rule applies to this category."""
        return rule_key in self.supported_rules

    def __repr__(self):
        return "<CategoryConfig {0} ({1})>".format(self.key, self.geometry_kind)


# ---------------------------------------------------------------------------
# Shared rule sets
# ---------------------------------------------------------------------------

# Always-available rules (run regardless of geometry).
_UNIVERSAL_RULES = frozenset({
    "visibility",            # active-view scope only; engine handles whole-model
    "skip_already_tagged",
})

# Linear MEP family: length, orientation, size, plus universal rules.
_LINEAR_RULES = _UNIVERSAL_RULES | frozenset({
    "min_length",
    "max_length",
    "horizontal_only",
    "vertical_only",
    "size",
})

# Point-based equipment / fixtures / devices / fittings: only universal
# rules apply in v3. Family-type and system-classification rules slot
# in here when they ship.
_POINT_RULES = _UNIVERSAL_RULES


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

# Helper to keep entries short and copy-paste-safe.
def _C(key, label, bic_name, tag_bic_name, kind, rules, dims=()):
    bic = getattr(BuiltInCategory, bic_name)
    tag_bic = getattr(BuiltInCategory, tag_bic_name)
    return CategoryConfig(key, label, bic, tag_bic, kind, rules, dims)


REGISTRY = {
    # ============================== Linear MEP =============================
    "cable_tray": _C(
        "cable_tray", "Cable Trays",
        "OST_CableTray", "OST_CableTrayTags",
        "linear", _LINEAR_RULES, ("width",),
    ),
    "conduit": _C(
        "conduit", "Conduits",
        "OST_Conduit", "OST_ConduitTags",
        "linear", _LINEAR_RULES, ("diameter",),
    ),
    "duct": _C(
        "duct", "Ducts",
        "OST_DuctCurves", "OST_DuctTags",
        "linear", _LINEAR_RULES, ("width", "height"),
    ),
    "flex_duct": _C(
        "flex_duct", "Flex Ducts",
        "OST_FlexDuctCurves", "OST_FlexDuctTags",
        "linear", _LINEAR_RULES, ("diameter",),
    ),
    "pipe": _C(
        "pipe", "Pipes",
        "OST_PipeCurves", "OST_PipeTags",
        "linear",
        # pipe is split across Mechanical / Hydraulic / Fire disciplines
        # via system classification, so it carries the extra rule.
        _LINEAR_RULES | frozenset({"system_classification"}),
        ("diameter",),
    ),

    # ===================== Priority 1: high-value point ====================
    "pipe_accessory": _C(
        "pipe_accessory", "Pipe Accessories",
        "OST_PipeAccessory", "OST_PipeAccessoryTags",
        "point", _POINT_RULES | frozenset({"system_classification"}),
    ),
    "mechanical_equipment": _C(
        "mechanical_equipment", "Mechanical Equipment",
        "OST_MechanicalEquipment", "OST_MechanicalEquipmentTags",
        "point", _POINT_RULES,
    ),
    "air_terminal": _C(
        "air_terminal", "Air Terminals",
        "OST_DuctTerminal", "OST_DuctTerminalTags",
        "point", _POINT_RULES,
    ),
    "electrical_equipment": _C(
        "electrical_equipment", "Electrical Equipment",
        "OST_ElectricalEquipment", "OST_ElectricalEquipmentTags",
        "point", _POINT_RULES,
    ),

    # ============================ Priority 2 ===============================
    "sprinkler": _C(
        "sprinkler", "Sprinklers",
        "OST_Sprinklers", "OST_SprinklerTags",
        "point", _POINT_RULES,
    ),
    "lighting_fixture": _C(
        "lighting_fixture", "Lighting Fixtures",
        "OST_LightingFixtures", "OST_LightingFixtureTags",
        "point", _POINT_RULES,
    ),
    "plumbing_fixture": _C(
        "plumbing_fixture", "Plumbing Fixtures",
        "OST_PlumbingFixtures", "OST_PlumbingFixtureTags",
        "point", _POINT_RULES,
    ),

    # ========================== Priority 3 - fittings ======================
    "pipe_fitting": _C(
        "pipe_fitting", "Pipe Fittings",
        "OST_PipeFitting", "OST_PipeFittingTags",
        "point", _POINT_RULES | frozenset({"system_classification"}),
    ),
    "duct_fitting": _C(
        "duct_fitting", "Duct Fittings",
        "OST_DuctFitting", "OST_DuctFittingTags",
        "point", _POINT_RULES,
    ),
    "conduit_fitting": _C(
        "conduit_fitting", "Conduit Fittings",
        "OST_ConduitFitting", "OST_ConduitFittingTags",
        "point", _POINT_RULES,
    ),
    "cable_tray_fitting": _C(
        "cable_tray_fitting", "Cable Tray Fittings",
        "OST_CableTrayFitting", "OST_CableTrayFittingTags",
        "point", _POINT_RULES,
    ),

    # ===================== Priority 3 - accessories / devices ==============
    "duct_accessory": _C(
        "duct_accessory", "Duct Accessories",
        "OST_DuctAccessory", "OST_DuctAccessoryTags",
        # family_name_pattern lets Fire Dampers split off as a Fire-
        # discipline binding without a new BIC.
        "point", _POINT_RULES | frozenset({"family_name_pattern"}),
    ),
    "lighting_device": _C(
        "lighting_device", "Lighting Devices",
        "OST_LightingDevices", "OST_LightingDeviceTags",
        "point", _POINT_RULES,
    ),
    "electrical_fixture": _C(
        "electrical_fixture", "Electrical Fixtures",
        "OST_ElectricalFixtures", "OST_ElectricalFixtureTags",
        "point", _POINT_RULES,
    ),
    "fire_alarm_device": _C(
        "fire_alarm_device", "Fire Alarm Devices",
        "OST_FireAlarmDevices", "OST_FireAlarmDeviceTags",
        "point", _POINT_RULES,
    ),
    "communication_device": _C(
        "communication_device", "Communication Devices",
        "OST_CommunicationDevices", "OST_CommunicationDeviceTags",
        "point", _POINT_RULES,
    ),
    "data_device": _C(
        "data_device", "Data Devices",
        "OST_DataDevices", "OST_DataDeviceTags",
        "point", _POINT_RULES,
    ),
    "security_device": _C(
        "security_device", "Security Devices",
        "OST_SecurityDevices", "OST_SecurityDeviceTags",
        "point", _POINT_RULES,
    ),
    "nurse_call_device": _C(
        "nurse_call_device", "Nurse Call Devices",
        "OST_NurseCallDevices", "OST_NurseCallDeviceTags",
        "point", _POINT_RULES,
    ),
    "telephone_device": _C(
        "telephone_device", "Telephone Devices",
        "OST_TelephoneDevices", "OST_TelephoneDeviceTags",
        "point", _POINT_RULES,
    ),
    "specialty_equipment": _C(
        "specialty_equipment", "Specialty Equipment",
        # Revit API spelling is "Speciality"
        "OST_SpecialityEquipment", "OST_SpecialityEquipmentTags",
        "point", _POINT_RULES,
    ),

    # =========================== Priority 3 - generic ======================
    "generic_model": _C(
        "generic_model", "Generic Models",
        "OST_GenericModel", "OST_GenericModelTags",
        # family_name_pattern lets Seismic bracing split off from the
        # unfiltered Generic discipline binding.
        "point", _POINT_RULES | frozenset({"family_name_pattern"}),
    ),
}


# UI display order. Cable trays first preserves the original default;
# the rest are grouped by priority + discipline so the dropdown reads
# top-to-bottom from "most-used MEP linear" to "rare custom families".
CATEGORY_ORDER = (
    # Linear MEP
    "cable_tray", "conduit", "duct", "flex_duct", "pipe",
    # P1: high-value point
    "pipe_accessory", "mechanical_equipment", "air_terminal",
    "electrical_equipment",
    # P2
    "sprinkler", "lighting_fixture", "plumbing_fixture",
    # P3: fittings
    "pipe_fitting", "duct_fitting", "conduit_fitting", "cable_tray_fitting",
    # P3: accessories + devices
    "duct_accessory", "lighting_device", "electrical_fixture",
    "fire_alarm_device", "communication_device", "data_device",
    "security_device", "nurse_call_device", "telephone_device",
    "specialty_equipment",
    # P3: generic / custom
    "generic_model",
)


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def get(category_key):
    """Return CategoryConfig for category_key. Raises KeyError if unknown."""
    return REGISTRY[category_key]


def get_safe(category_key, default=None):
    return REGISTRY.get(category_key, default)


def order():
    """Return the ordered tuple of category keys for UI population."""
    return CATEGORY_ORDER


def labels():
    """Return {key: label} for every registered category."""
    return {k: cfg.label for k, cfg in REGISTRY.items()}


def keys():
    return tuple(REGISTRY.keys())
