# -*- coding: utf-8 -*-
"""
scanners.py
===========

Reads raw facts from the active Revit model. Each scanner returns a plain
dict / list of dicts so downstream rules and reporters never need to touch
the Revit API directly. This makes the rules unit-testable with mock data
and keeps the API surface small.

Conventions:
- Every public function takes `doc` (Autodesk.Revit.DB.Document) as first arg.
- Every public function returns JSON-serialisable data only.
- Heavy collectors are wrapped to fail soft: on error, return an empty result
  and log a warning, so one broken scanner does not kill the whole report.
"""

from collections import Counter, defaultdict

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInCategory,
    BuiltInParameter,
    ViewType,
    View,
    ViewSheet,
    Workset,
    WorksetKind,
    FilteredWorksetCollector,
    ImportInstance,
    RevitLinkInstance,
    RevitLinkType,
    Family,
    FamilySymbol,
    ElementId,
    Group,
    GroupType,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe(scanner_fn):
    """Decorator: return {'error': str(e)} instead of raising."""
    def wrapper(*args, **kwargs):
        try:
            return scanner_fn(*args, **kwargs)
        except Exception as exc:
            return {"error": "{0}: {1}".format(scanner_fn.__name__, exc)}
    wrapper.__name__ = scanner_fn.__name__
    return wrapper


def _param_value(elem, bip):
    """Read a built-in parameter as string, or None."""
    p = elem.get_Parameter(bip) if elem else None
    if p is None:
        return None
    try:
        return p.AsString() or p.AsValueString()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# File / project basics
# ---------------------------------------------------------------------------

@_safe
def scan_project_info(doc):
    """High-level facts about the file."""
    pi = doc.ProjectInformation
    return {
        "title": doc.Title,
        "path": doc.PathName or "(unsaved)",
        "is_workshared": doc.IsWorkshared,
        "is_detached": doc.IsDetached,
        "project_number": _param_value(pi, BuiltInParameter.PROJECT_NUMBER),
        "project_name":   _param_value(pi, BuiltInParameter.PROJECT_NAME),
        "client_name":    _param_value(pi, BuiltInParameter.CLIENT_NAME),
        "revit_version":  doc.Application.VersionNumber,
        "build":          doc.Application.VersionBuild,
    }


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------

@_safe
def scan_warnings(doc):
    """
    Returns total count plus a breakdown by description.
    Useful for both health (trend) and QA (cap per BEP).
    """
    warnings = list(doc.GetWarnings())
    by_description = Counter(w.GetDescriptionText() for w in warnings)
    top = by_description.most_common(10)
    return {
        "total": len(warnings),
        "unique_types": len(by_description),
        "top": [{"description": d, "count": c} for d, c in top],
    }


# ---------------------------------------------------------------------------
# Worksets
# ---------------------------------------------------------------------------

@_safe
def scan_worksets(doc):
    """List user worksets with name and visibility-by-default."""
    if not doc.IsWorkshared:
        return {"is_workshared": False, "worksets": []}

    collector = FilteredWorksetCollector(doc).OfKind(WorksetKind.UserWorkset)
    worksets = []
    for ws in collector:
        worksets.append({
            "id": ws.Id.IntegerValue,
            "name": ws.Name,
            "is_default_visible": ws.IsVisibleByDefault,
            "is_open": ws.IsOpen,
            "owner": ws.Owner,
        })
    return {"is_workshared": True, "worksets": worksets}


# ---------------------------------------------------------------------------
# Views and sheets
# ---------------------------------------------------------------------------

@_safe
def scan_views(doc):
    """
    Inventory of views: count, templates, on-sheet status, and a list of views
    that have no template assigned (a common QA failure).
    """
    views = [v for v in FilteredElementCollector(doc).OfClass(View)
             if not v.IsTemplate]

    sheets = list(FilteredElementCollector(doc).OfClass(ViewSheet))

    # Build set of view ids placed on any sheet
    placed_ids = set()
    for sh in sheets:
        for vp_id in sh.GetAllPlacedViews():
            placed_ids.add(vp_id.IntegerValue)

    no_template = []
    not_on_sheet = []
    for v in views:
        # Skip view types that legitimately don't need templates / sheets
        if v.ViewType in (ViewType.ProjectBrowser,
                          ViewType.SystemBrowser,
                          ViewType.Internal,
                          ViewType.Undefined):
            continue
        if v.ViewTemplateId == ElementId.InvalidElementId:
            no_template.append({"id": v.Id.IntegerValue, "name": v.Name,
                                "type": str(v.ViewType)})
        if v.Id.IntegerValue not in placed_ids and v.ViewType not in (
                ViewType.Schedule, ViewType.Legend):
            not_on_sheet.append({"id": v.Id.IntegerValue, "name": v.Name,
                                 "type": str(v.ViewType)})

    templates = [v for v in FilteredElementCollector(doc).OfClass(View)
                 if v.IsTemplate]

    return {
        "view_count": len(views),
        "sheet_count": len(sheets),
        "template_count": len(templates),
        "views_without_template": no_template,
        "views_not_on_sheet": not_on_sheet,
    }


@_safe
def scan_view_naming(doc, pattern=None):
    """
    Returns a list of views whose names do not match a regex pattern.
    Pattern is supplied by the QA config; for health audits, pass None and
    the rule layer will skip naming checks.
    """
    import re
    if not pattern:
        return {"pattern": None, "non_compliant": []}

    rx = re.compile(pattern)
    skip_types = (
        ViewType.ProjectBrowser,
        ViewType.SystemBrowser,
        ViewType.Internal,
        ViewType.Undefined,
        ViewType.DrawingSheet,
    )
    bad = []
    for v in FilteredElementCollector(doc).OfClass(View):
        if v.IsTemplate:
            continue
        if v.ViewType in skip_types:
            continue
        name = v.Name
        if name == "Project View" or name.startswith("Startup View"):
            continue
        if not rx.match(name):
            bad.append({"id": v.Id.IntegerValue, "name": name})
    return {"pattern": pattern, "non_compliant": bad}


# ---------------------------------------------------------------------------
# CAD imports vs links
# ---------------------------------------------------------------------------

@_safe
def scan_cad_imports(doc):
    """
    Imported CAD is almost always a mistake; linked CAD is usually fine.
    We separate them so the rule layer can fail one and pass the other.
    """
    imports = []
    links = []
    for inst in FilteredElementCollector(doc).OfClass(ImportInstance):
        type_id = inst.GetTypeId()
        type_elem = doc.GetElement(type_id) if type_id else None
        name = type_elem.Category.Name if type_elem and type_elem.Category else "?"
        record = {
            "id": inst.Id.IntegerValue,
            "name": _param_value(type_elem, BuiltInParameter.ALL_MODEL_TYPE_NAME) or name,
            "view_specific": inst.ViewSpecific,
            "owner_view_id": inst.OwnerViewId.IntegerValue if inst.OwnerViewId else None,
        }
        if inst.IsLinked:
            links.append(record)
        else:
            imports.append(record)
    return {"imported": imports, "linked": links}


# ---------------------------------------------------------------------------
# Revit links
# ---------------------------------------------------------------------------

@_safe
def scan_revit_links(doc):
    """Linked Revit files: pathing, load state, pinned status."""
    out = []
    link_types = list(FilteredElementCollector(doc).OfClass(RevitLinkType))
    type_by_id = {lt.Id.IntegerValue: lt for lt in link_types}

    for inst in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        type_id = inst.GetTypeId().IntegerValue
        link_type = type_by_id.get(type_id)
        ext = link_type.GetExternalFileReference() if link_type else None

        out.append({
            "id": inst.Id.IntegerValue,
            "name": inst.Name,
            "is_pinned": inst.Pinned,
            "workset_id": inst.WorksetId.IntegerValue,
            "load_state": str(ext.GetLinkedFileStatus()) if ext else "unknown",
            "path_type": str(ext.PathType) if ext else "unknown",
            "path": ext.GetAbsolutePath().ToString() if ext else "",
        })
    return {"links": out}


# ---------------------------------------------------------------------------
# Families
# ---------------------------------------------------------------------------

@_safe
def scan_families(doc):
    """
    Family inventory and unused-type detection.
    Unused = FamilySymbol with no instances and (optionally) not the only
    type of its family.
    """
    families = list(FilteredElementCollector(doc).OfClass(Family))
    symbols  = list(FilteredElementCollector(doc).OfClass(FamilySymbol))

    # Count instances per symbol id
    instance_counts = defaultdict(int)
    for sym in symbols:
        # cheap-ish: collect instances of this symbol
        instances = (FilteredElementCollector(doc)
                     .WhereElementIsNotElementType()
                     .OfCategoryId(sym.Category.Id)
                     if sym.Category else None)
        # Counting all category instances is too coarse; skip exact count
        # for performance and just mark IsActive instead.
    unused = []
    for sym in symbols:
        if not sym.IsActive:
            unused.append({
                "id": sym.Id.IntegerValue,
                "family": sym.Family.Name if sym.Family else "?",
                "type":   sym.Name,
            })

    return {
        "family_count": len(families),
        "type_count": len(symbols),
        "inactive_types": unused,
    }


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------

@_safe
def scan_groups(doc):
    """Model groups can balloon a file; flag count and largest groups."""
    group_types = list(FilteredElementCollector(doc).OfClass(GroupType))
    groups = list(FilteredElementCollector(doc).OfClass(Group))

    by_type = Counter(g.GroupType.Id.IntegerValue for g in groups
                      if g.GroupType is not None)

    biggest = []
    for g in groups:
        try:
            member_count = len(list(g.GetMemberIds()))
        except Exception:
            member_count = 0
        biggest.append({
            "id": g.Id.IntegerValue,
            "name": g.Name,
            "member_count": member_count,
        })
    biggest.sort(key=lambda r: r["member_count"], reverse=True)

    return {
        "group_type_count": len(group_types),
        "group_instance_count": len(groups),
        "instances_per_type": dict(by_type),
        "largest_groups": biggest[:10],
    }


# ---------------------------------------------------------------------------
# Master scan
# ---------------------------------------------------------------------------

def run_all(doc, qa_config=None, progress=None):
    """
    Run every scanner and return a single dict.

    qa_config (optional) is a dict loaded from JSON; only used to pass
    project-specific patterns into pattern-aware scanners.

    progress (optional) is callable(done:int, total:int, current:str)
    -> bool. Invoked BEFORE each scanner runs so the UI can label the
    bar ("Scanning warnings..."). Return False to cancel; run_all then
    stops and returns None - downstream rules/reporting must not run
    on a partial scan. Step granularity is one tick per scanner (9
    total). Per-scanner timing varies a lot (warnings near-instant,
    families slow on large libraries), so progress feels uneven; this
    matches reality better than faking a uniform cadence.
    """
    qa_config = qa_config or {}
    steps = [
        ("project",      lambda: scan_project_info(doc)),
        ("warnings",     lambda: scan_warnings(doc)),
        ("worksets",     lambda: scan_worksets(doc)),
        ("views",        lambda: scan_views(doc)),
        ("view_naming",  lambda: scan_view_naming(
            doc, pattern=qa_config.get("view_name_pattern"))),
        ("cad",          lambda: scan_cad_imports(doc)),
        ("links",        lambda: scan_revit_links(doc)),
        ("families",     lambda: scan_families(doc)),
        ("groups",       lambda: scan_groups(doc)),
    ]
    total = len(steps)
    out = {}
    for i, (key, fn) in enumerate(steps):
        if progress is not None and not progress(i, total, key):
            return None
        out[key] = fn()
    if progress is not None:
        progress(total, total, None)
    return out
