# -*- coding: utf-8 -*-
"""
rules.py
========

A rule takes the scan results dict from `scanners.run_all()` and emits a list
of Finding objects. Health rules and QA rules share the same Finding shape so
the reporter does not need to care which one produced them.

Severity:
    INFO  - Just an FYI; never fails an issuance.
    WARN  - Should fix; trends up if ignored.
    FAIL  - Must fix before issuance / blocks the QA gate.
"""

INFO, WARN, FAIL = "INFO", "WARN", "FAIL"


class Finding(object):
    __slots__ = ("category", "severity", "message", "count", "details")

    def __init__(self, category, severity, message, count=0, details=None):
        self.category = category
        self.severity = severity
        self.message = message
        self.count = count
        self.details = details or []

    def to_dict(self):
        return {
            "category": self.category,
            "severity": self.severity,
            "message": self.message,
            "count": self.count,
            "details": self.details,
        }


# ---------------------------------------------------------------------------
# Health rules (office-wide, hardcoded thresholds)
# ---------------------------------------------------------------------------

HEALTH_THRESHOLDS = {
    "warnings_warn": 100,
    "warnings_fail": 1000,
    "views_without_template_warn": 20,
    "views_not_on_sheet_warn": 50,
    "cad_imports_fail": 1,           # any import is a fail
    "inactive_types_warn": 100,
    "largest_group_member_warn": 200,
}


def health_rules(scan):
    findings = []
    t = HEALTH_THRESHOLDS

    # Warnings
    w = scan.get("warnings", {})
    total = w.get("total", 0)
    if total >= t["warnings_fail"]:
        sev = FAIL
    elif total >= t["warnings_warn"]:
        sev = WARN
    else:
        sev = INFO
    findings.append(Finding(
        "Warnings", sev,
        "Model has {0} warnings.".format(total),
        count=total,
        details=w.get("top", []),
    ))

    # Views without templates
    v = scan.get("views", {})
    nwt = v.get("views_without_template", [])
    if len(nwt) >= t["views_without_template_warn"]:
        findings.append(Finding(
            "Views", WARN,
            "{0} views have no view template assigned.".format(len(nwt)),
            count=len(nwt), details=nwt[:25],
        ))

    # Views not on sheet
    nos = v.get("views_not_on_sheet", [])
    if len(nos) >= t["views_not_on_sheet_warn"]:
        findings.append(Finding(
            "Views", WARN,
            "{0} views are not placed on any sheet.".format(len(nos)),
            count=len(nos), details=nos[:25],
        ))

    # CAD imports
    cad = scan.get("cad", {})
    imports = cad.get("imported", [])
    if len(imports) >= t["cad_imports_fail"]:
        findings.append(Finding(
            "CAD", FAIL,
            "{0} imported CAD instance(s) found. Use links instead.".format(
                len(imports)),
            count=len(imports), details=imports,
        ))

    # Inactive (unused) family types
    fam = scan.get("families", {})
    inactive = fam.get("inactive_types", [])
    if len(inactive) >= t["inactive_types_warn"]:
        findings.append(Finding(
            "Families", WARN,
            "{0} family types are inactive (likely unused).".format(
                len(inactive)),
            count=len(inactive), details=inactive[:25],
        ))

    # Oversized groups
    groups = scan.get("groups", {})
    largest = groups.get("largest_groups", [])
    big = [g for g in largest
           if g.get("member_count", 0) >= t["largest_group_member_warn"]]
    if big:
        findings.append(Finding(
            "Groups", WARN,
            "{0} group(s) exceed {1} members.".format(
                len(big), t["largest_group_member_warn"]),
            count=len(big), details=big,
        ))

    # Links not pinned
    links = scan.get("links", {}).get("links", []) or []
    unpinned = [l for l in links if not l.get("is_pinned")]
    if unpinned:
        findings.append(Finding(
            "Links", WARN,
            "{0} Revit link(s) are not pinned.".format(len(unpinned)),
            count=len(unpinned), details=unpinned,
        ))

    return findings


# ---------------------------------------------------------------------------
# QA rules (driven by project config)
# ---------------------------------------------------------------------------

def qa_rules(scan, config):
    """
    config is a dict loaded from a project JSON file. Every key is optional;
    missing keys mean 'this project doesn't check that requirement'.
    """
    findings = []
    config = config or {}

    # Warning cap from BEP
    cap = config.get("max_warnings")
    if cap is not None:
        total = scan.get("warnings", {}).get("total", 0)
        sev = FAIL if total > cap else INFO
        findings.append(Finding(
            "Warnings (BEP cap)", sev,
            "Model has {0} warnings; BEP cap is {1}.".format(total, cap),
            count=total,
            details=scan.get("warnings", {}).get("top", []),
        ))

    # Required worksets
    required = config.get("required_worksets") or []
    if required:
        ws_data = scan.get("worksets", {})
        present = {ws["name"] for ws in ws_data.get("worksets", [])}
        missing = [name for name in required if name not in present]
        if missing:
            findings.append(Finding(
                "Worksets", FAIL,
                "Missing required worksets: {0}".format(", ".join(missing)),
                count=len(missing), details=[{"name": m} for m in missing],
            ))

    # View naming
    bad_names = scan.get("view_naming", {}).get("non_compliant", [])
    pattern   = scan.get("view_naming", {}).get("pattern")
    if pattern and bad_names:
        findings.append(Finding(
            "View naming", FAIL,
            "{0} view(s) do not match the BEP naming pattern.".format(
                len(bad_names)),
            count=len(bad_names), details=bad_names[:50],
        ))

    # Project info completeness
    required_pi = config.get("required_project_info") or []
    if required_pi:
        pi = scan.get("project", {})
        missing = [k for k in required_pi if not pi.get(k)]
        if missing:
            findings.append(Finding(
                "Project Info", FAIL,
                "Missing project info fields: {0}".format(", ".join(missing)),
                count=len(missing),
            ))

    # CAD imports forbidden by BEP
    if config.get("forbid_cad_imports", True):
        imports = scan.get("cad", {}).get("imported", [])
        if imports:
            findings.append(Finding(
                "CAD", FAIL,
                "{0} imported CAD instance(s) present (BEP forbids imports).".format(
                    len(imports)),
                count=len(imports), details=imports,
            ))

    # Links must be pinned
    if config.get("require_links_pinned", True):
        links = scan.get("links", {}).get("links", []) or []
        unpinned = [l for l in links if not l.get("is_pinned")]
        if unpinned:
            findings.append(Finding(
                "Links", FAIL,
                "{0} link(s) are not pinned.".format(len(unpinned)),
                count=len(unpinned), details=unpinned,
            ))

    return findings
