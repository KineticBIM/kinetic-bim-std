# -*- coding: utf-8 -*-
"""Discipline + subcategory binding registry.

Sits above core.category_config: each discipline (Mechanical, Electrical,
Hydraulic, Fire) declares an ordered tuple of SubcategoryBinding entries
that the UI presents as a multi-select checklist. A binding points at
exactly one Revit category (CategoryConfig key) plus optional filters:

    system_classifications  - set of MEP system classification strings
                              the element must match. Used to split
                              OST_PipeCurves between Mechanical pipework,
                              Hydraulic pipes, and Fire pipework based
                              on the system the pipe is on.

    family_name_patterns    - tuple of lowercase substrings matched
                              against the element's family name. Used
                              for Fire Dampers, which live inside
                              OST_DuctAccessory but are a discipline-
                              specific subset.

Several disciplines may bind the same CategoryConfig with different
filters (e.g. Mechanical "pipework" and Hydraulic "pipes" both bind
"pipe" with disjoint system classification sets). An element belongs to
the FIRST binding (in user selection order) whose filters pass - this
keeps the report unambiguous.

The registry is pure data; no Revit API imports, so it loads outside
Revit too.
"""


# ---------------------------------------------------------------------------
# Canonical MEP system classification strings.
#
# These match Autodesk.Revit.DB.MEPSystemClassification enum names. The
# system_classification reader returns them as strings so this module
# can stay Revit-API-free for testability.
# ---------------------------------------------------------------------------

MECH_PIPE_CLASSES = frozenset([
    "SupplyHydronic",
    "ReturnHydronic",
    "Refrigerant",
    "OtherPipe",
])

HYDRAULIC_PIPE_CLASSES = frozenset([
    "DomesticHotWater",
    "DomesticColdWater",
    "Sanitary",
    "Vent",
    "Storm",
    "OtherPipe",
])

FIRE_PIPE_CLASSES = frozenset([
    "FireProtectWet",
    "FireProtectDry",
    "FireProtectOther",
    "FireProtectPreaction",
])


# ---------------------------------------------------------------------------
# SubcategoryBinding + DisciplineConfig
# ---------------------------------------------------------------------------

class SubcategoryBinding(object):
    """A single tickable row in a discipline's subcategory list.

    key                      stable string used in option dicts + JSON
                             (unique across the registry; the same
                             category_key may appear in several
                             bindings with different keys).
    label                    user-facing text in the checklist.
    category_key             CategoryConfig key this binding scans.
    system_classifications   frozenset of allowed MEP system
                             classifications. Empty/None = no filter.
    family_name_patterns     tuple of lowercase substrings matched
                             against family / type / instance name.
                             Empty = no filter.
    """

    def __init__(self, key, label, category_key,
                 system_classifications=None, family_name_patterns=()):
        self.key = key
        self.label = label
        self.category_key = category_key
        self.system_classifications = (
            frozenset(system_classifications)
            if system_classifications else frozenset())
        self.family_name_patterns = tuple(
            p.lower() for p in (family_name_patterns or ()))

    def has_system_filter(self):
        return bool(self.system_classifications)

    def has_family_filter(self):
        return bool(self.family_name_patterns)

    def __repr__(self):
        return "<SubcategoryBinding {0} -> {1}>".format(
            self.key, self.category_key)


class DisciplineConfig(object):

    def __init__(self, key, label, subcategories):
        self.key = key
        self.label = label
        self.subcategories = tuple(subcategories)
        self._by_key = {b.key: b for b in self.subcategories}

    def subcategory(self, sub_key):
        return self._by_key[sub_key]

    def subcategory_safe(self, sub_key, default=None):
        return self._by_key.get(sub_key, default)

    def subcategory_keys(self):
        return tuple(b.key for b in self.subcategories)

    def __repr__(self):
        return "<DisciplineConfig {0} ({1} subs)>".format(
            self.key, len(self.subcategories))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def _S(key, label, category_key, system_classifications=None,
       family_name_patterns=()):
    return SubcategoryBinding(
        key, label, category_key,
        system_classifications=system_classifications,
        family_name_patterns=family_name_patterns,
    )


DISCIPLINE_REGISTRY = {
    "mechanical": DisciplineConfig(
        key="mechanical",
        label="Mechanical",
        subcategories=(
            _S("duct",                 "Ducts",                "duct"),
            _S("flex_duct",            "Flex Ducts",           "flex_duct"),
            _S("mechanical_equipment", "Mechanical Equipment", "mechanical_equipment"),
            _S("air_terminal",         "Air Terminals",        "air_terminal"),
            _S("duct_accessory",       "Duct Accessories",     "duct_accessory"),
            _S("duct_fitting",         "Duct Fittings",        "duct_fitting"),
            _S("pipework",             "Pipework",             "pipe",
               system_classifications=MECH_PIPE_CLASSES),
            _S("pipe_accessory_mech",  "Pipe Accessories",     "pipe_accessory",
               system_classifications=MECH_PIPE_CLASSES),
            _S("pipe_fitting_mech",    "Pipe Fittings",        "pipe_fitting",
               system_classifications=MECH_PIPE_CLASSES),
        ),
    ),
    "electrical": DisciplineConfig(
        key="electrical",
        label="Electrical",
        subcategories=(
            _S("conduit",              "Conduits",             "conduit"),
            _S("conduit_fitting",      "Conduit Fittings",     "conduit_fitting"),
            _S("cable_tray",           "Cable Trays",          "cable_tray"),
            _S("cable_tray_fitting",   "Cable Tray Fittings",  "cable_tray_fitting"),
            _S("electrical_equipment", "Electrical Equipment", "electrical_equipment"),
            _S("lighting_fixture",     "Lighting Fixtures",    "lighting_fixture"),
            _S("lighting_device",      "Lighting Devices",     "lighting_device"),
            _S("electrical_fixture",   "Electrical Fixtures",  "electrical_fixture"),
            _S("fire_alarm_device_el", "Fire Alarm Devices",   "fire_alarm_device"),
            _S("communication_device", "Communication Devices","communication_device"),
            _S("data_device",          "Data Devices",         "data_device"),
            _S("security_device",      "Security Devices",     "security_device"),
            _S("nurse_call_device",    "Nurse Call Devices",   "nurse_call_device"),
            _S("telephone_device",     "Telephone Devices",    "telephone_device"),
        ),
    ),
    "hydraulic": DisciplineConfig(
        key="hydraulic",
        label="Hydraulic",
        subcategories=(
            _S("pipes",                "Pipes",                "pipe",
               system_classifications=HYDRAULIC_PIPE_CLASSES),
            _S("pipe_accessory_hyd",   "Pipe Accessories",     "pipe_accessory",
               system_classifications=HYDRAULIC_PIPE_CLASSES),
            _S("pipe_fitting_hyd",     "Pipe Fittings",        "pipe_fitting",
               system_classifications=HYDRAULIC_PIPE_CLASSES),
            _S("plumbing_fixture",     "Plumbing Fixtures",    "plumbing_fixture"),
            _S("specialty_equipment",  "Specialty Equipment",  "specialty_equipment"),
        ),
    ),
    "fire": DisciplineConfig(
        key="fire",
        label="Fire",
        subcategories=(
            _S("fire_pipework",        "Fire Pipework",        "pipe",
               system_classifications=FIRE_PIPE_CLASSES),
            _S("sprinkler",            "Sprinklers",           "sprinkler"),
            _S("fire_damper",          "Fire Dampers",         "duct_accessory",
               family_name_patterns=("fire damper", "smoke damper",
                                     "fire-damper", "fsd")),
            _S("fire_alarm_device_fire", "Fire Alarm Devices", "fire_alarm_device"),
        ),
    ),
    "generic": DisciplineConfig(
        key="generic",
        label="Generic",
        subcategories=(
            _S("generic_model",        "Generic Models",       "generic_model"),
        ),
    ),
    "seismic": DisciplineConfig(
        key="seismic",
        label="Seismic",
        # Revit has no native seismic category — bracing/restraints are
        # modelled as Generic Models. Same pattern as Fire Dampers
        # splitting off from duct_accessory by family name.
        subcategories=(
            _S("seismic_brace",        "Seismic Bracing",      "generic_model",
               family_name_patterns=("seismic", "brace", "restraint",
                                     "snubber", "isolator", "anchor")),
        ),
    ),
}


DISCIPLINE_ORDER = ("mechanical", "electrical", "hydraulic", "fire",
                    "generic", "seismic")


# ---------------------------------------------------------------------------
# Lookup helpers (mirror category_config's surface)
# ---------------------------------------------------------------------------

def get(discipline_key):
    """Return DisciplineConfig. KeyError if unknown."""
    return DISCIPLINE_REGISTRY[discipline_key]


def get_safe(discipline_key, default=None):
    return DISCIPLINE_REGISTRY.get(discipline_key, default)


def order():
    return DISCIPLINE_ORDER


def labels():
    return {k: d.label for k, d in DISCIPLINE_REGISTRY.items()}


def bindings_for(discipline_key):
    """Return the ordered tuple of SubcategoryBinding for a discipline.
    Empty tuple for unknown disciplines."""
    disc = DISCIPLINE_REGISTRY.get(discipline_key)
    return disc.subcategories if disc else ()


def find_binding(discipline_key, sub_key):
    """Return the SubcategoryBinding for (discipline_key, sub_key), or
    None if either is unknown."""
    disc = DISCIPLINE_REGISTRY.get(discipline_key)
    if disc is None:
        return None
    return disc.subcategory_safe(sub_key)


def find_binding_for_category(category_key):
    """Return (discipline_key, SubcategoryBinding) for the first binding
    in DISCIPLINE_ORDER whose category_key matches. Used by the legacy
    JSON migration path to map a v3 category_key onto a default binding.

    Returns (None, None) if no binding references the category.
    """
    for disc_key in DISCIPLINE_ORDER:
        disc = DISCIPLINE_REGISTRY[disc_key]
        for binding in disc.subcategories:
            if binding.category_key == category_key:
                return disc_key, binding
    return None, None


def iter_bindings():
    """Yield (discipline_key, SubcategoryBinding) over every entry."""
    for disc_key in DISCIPLINE_ORDER:
        disc = DISCIPLINE_REGISTRY[disc_key]
        for binding in disc.subcategories:
            yield disc_key, binding
