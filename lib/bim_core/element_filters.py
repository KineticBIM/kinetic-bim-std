# -*- coding: utf-8 -*-
"""Element collection.

The category metadata that used to live here (SUPPORTED_CATEGORIES /
CATEGORY_LABELS / CATEGORY_ORDER) is now sourced from
core.category_config.REGISTRY - this module re-exports the lookups so
the UI and engine modules don't have to know where they live.
"""

from Autodesk.Revit.DB import FilteredElementCollector

from bim_core.core import category_config


# Re-exports - keep the same names UI / engine modules already import.
# These are evaluated at import time; if you add a category to the
# registry after import you must reload the package (pyRevit Reload).

def _supported_categories():
    return {k: cfg.bic for k, cfg in category_config.REGISTRY.items()}

def _category_labels():
    return category_config.labels()

SUPPORTED_CATEGORIES = _supported_categories()
CATEGORY_LABELS = _category_labels()
CATEGORY_ORDER = category_config.CATEGORY_ORDER


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

def collect_elements(doc, view, category_key="cable_tray", whole_model=False):
    """Collect elements of the given category.

    whole_model=False: visible in the supplied view (IsHidden filter
    applied). Linked models are not traversed.

    whole_model=True: every host-doc instance of the category. View is
    unused for collection; the qa_engine still uses it for the
    'visible in active view' marker that gates placement.
    """
    cfg = category_config.get_safe(category_key)
    if cfg is None:
        raise ValueError("Unsupported category: {0}".format(category_key))

    if whole_model:
        collector = (FilteredElementCollector(doc)
                     .OfCategory(cfg.bic)
                     .WhereElementIsNotElementType())
    else:
        collector = (FilteredElementCollector(doc, view.Id)
                     .OfCategory(cfg.bic)
                     .WhereElementIsNotElementType())

    elements = []
    for el in collector:
        if not whole_model:
            try:
                if el.IsHidden(view):
                    continue
            except Exception:
                pass
        elements.append(el)
    return elements


def collect_elements_for_categories(doc, view, category_keys, whole_model=False):
    """Collect elements for several categories at once.

    Returns: dict of {category_key: [element, ...]}. Each entry is the
    same list collect_elements() would return for that category. The
    helper exists so qa_engine can scan a multi-subcategory selection
    without re-implementing the per-category loop.

    Unknown category keys are skipped silently (the caller has already
    chosen them from the registry so this is defensive).
    """
    out = {}
    seen = set()
    for key in category_keys:
        if key in seen:
            continue
        seen.add(key)
        if category_config.get_safe(key) is None:
            continue
        out[key] = collect_elements(doc, view, key, whole_model=whole_model)
    return out


def view_visible_element_ids(doc, view, category_key):
    """Set of integer ElementIds of the category currently visible in view."""
    cfg = category_config.get_safe(category_key)
    if cfg is None:
        raise ValueError("Unsupported category: {0}".format(category_key))
    collector = (FilteredElementCollector(doc, view.Id)
                 .OfCategory(cfg.bic)
                 .WhereElementIsNotElementType())
    ids = set()
    for el in collector:
        try:
            if el.IsHidden(view):
                continue
        except Exception:
            pass
        ids.add(el.Id.IntegerValue)
    return ids
