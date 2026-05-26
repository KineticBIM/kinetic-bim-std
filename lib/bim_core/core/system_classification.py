# -*- coding: utf-8 -*-
"""Defensive MEP system classification reader.

Returns the Autodesk.Revit.DB.MEPSystemClassification enum name as a
plain string ("SupplyHydronic", "DomesticColdWater", "FireProtectWet",
...) or None when the element either has no system, has an unparseable
system, or isn't an MEP element at all. Never raises.

Lookup order:
    1. element.MEPSystem (pipes, ducts, conduits, cable trays)
    2. element.System    (some accessory / fitting families)
    3. Walk element.ConnectorManager.Connectors and use the first
       connector that has an MEPSystem (fittings + accessories whose
       parent system is only reachable through a connector)

The Revit API exposes the classification at slightly different paths on
different element types; this helper papers over that without leaking
the API back to the rule. Classification IS the string name of the enum
value, which is what discipline_config.*_PIPE_CLASSES is built around.
"""


def read_classification(element):
    """Return the MEP system classification string, or None.

    Wraps every API call in try/except - elements without an MEP system
    (lighting fixtures, plumbing fixtures with no piping, generic
    models, ...) just return None.
    """
    if element is None:
        return None

    # Pipes, ducts, conduits, cable trays expose MEPSystem directly.
    cls = _from_attribute(element, "MEPSystem")
    if cls is not None:
        return cls

    # Some accessories / fittings expose .System (older API path).
    cls = _from_attribute(element, "System")
    if cls is not None:
        return cls

    # Fall back to the first connector that knows its MEP system.
    return _from_connectors(element)


def _from_attribute(element, attr_name):
    try:
        sys = getattr(element, attr_name, None)
    except Exception:
        return None
    if sys is None:
        return None
    return _classification_string(sys)


def _from_connectors(element):
    try:
        cm = getattr(element, "ConnectorManager", None)
        if cm is None:
            return None
        connectors = cm.Connectors
    except Exception:
        return None
    if connectors is None:
        return None
    try:
        for c in connectors:
            try:
                sys = c.MEPSystem
            except Exception:
                sys = None
            if sys is None:
                continue
            cls = _classification_string(sys)
            if cls is not None:
                return cls
    except Exception:
        return None
    return None


def _classification_string(system):
    """Pull the SystemClassification name off an MEPSystem instance."""
    # Pipes / ducts: element.MEPSystem is an MEPSystem instance whose
    # GetSystemType() (Revit 2017+) returns a MEPSystemType with a
    # .SystemClassification (MEPSystemClassification enum). Older paths
    # exposed SystemClassification directly on the system instance.
    if system is None:
        return None

    # Try MEPSystemType -> SystemClassification.
    try:
        st = system.GetSystemType()
        if st is not None:
            cls = getattr(st, "SystemClassification", None)
            if cls is not None:
                return _enum_name(cls)
    except Exception:
        pass

    # Try direct SystemClassification on the system instance.
    try:
        cls = getattr(system, "SystemClassification", None)
        if cls is not None:
            return _enum_name(cls)
    except Exception:
        pass

    return None


def _enum_name(value):
    """Return the enum member name as a plain string."""
    try:
        return str(value).rsplit(".", 1)[-1]
    except Exception:
        return None
