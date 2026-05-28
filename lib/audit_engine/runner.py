# -*- coding: utf-8 -*-
"""
runner.py
=========

Orchestration layer. The pushbutton scripts call into here so they stay tiny.
"""

import os
import json
import datetime

from audit_engine import scanners, rules, reporters


# ---------------------------------------------------------------------------
# QA config loading
# ---------------------------------------------------------------------------

def _candidate_config_paths(doc):
    """
    Look for a project QA config in this order:
      1. <project folder>/.bim/qa_config.json   (per-project, version controlled)
      2. <extension>/lib/audit_engine/configs/<project_number>.json
      3. <extension>/lib/audit_engine/configs/default.json
    """
    paths = []
    pn = doc.PathName
    if pn:
        proj_dir = os.path.dirname(pn)
        paths.append(os.path.join(proj_dir, ".bim", "qa_config.json"))

    here = os.path.dirname(os.path.abspath(__file__))
    cfg_dir = os.path.join(here, "configs")

    pi = doc.ProjectInformation
    proj_num = None
    try:
        from Autodesk.Revit.DB import BuiltInParameter
        p = pi.get_Parameter(BuiltInParameter.PROJECT_NUMBER)
        proj_num = p.AsString() if p else None
    except Exception:
        pass

    if proj_num:
        paths.append(os.path.join(cfg_dir, "{0}.json".format(proj_num)))
    paths.append(os.path.join(cfg_dir, "default.json"))
    return paths


def load_qa_config(doc):
    for path in _candidate_config_paths(doc):
        if os.path.isfile(path):
            with open(path, "r") as fh:
                return json.load(fh), path
    return {}, None


# ---------------------------------------------------------------------------
# Output paths
# ---------------------------------------------------------------------------

def _report_path(doc, kind):
    """e.g. <project folder>/.bim/reports/health_2026-05-04_1430.html"""
    pn = doc.PathName
    base = os.path.dirname(pn) if pn else os.path.expanduser("~")
    folder = os.path.join(base, ".bim", "reports")
    if not os.path.isdir(folder):
        os.makedirs(folder)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    return os.path.join(folder, "{0}_{1}.html".format(kind, stamp))


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def run_health_audit(doc, output=None, progress=None):
    """Returns (report_path, findings), or None when the user cancels
    the scan via the progress callback."""
    scan = scanners.run_all(doc, progress=progress)
    if scan is None:
        return None
    findings = rules.health_rules(scan)

    project = scan.get("project", {})
    label = "{0} ({1})".format(project.get("title", "?"),
                                project.get("project_number") or "no #")

    out_path = _report_path(doc, "health")
    reporters.render_html("Model Health Audit", label, findings, out_path)
    reporters.print_console("Model Health Audit", findings, output)
    return out_path, findings


def run_qa_check(doc, output=None, progress=None):
    """Returns (report_path, findings), or None when the user cancels
    the scan via the progress callback."""
    config, config_path = load_qa_config(doc)
    scan = scanners.run_all(doc, qa_config=config, progress=progress)
    if scan is None:
        return None
    findings = rules.qa_rules(scan, config)

    project = scan.get("project", {})
    label = "{0} ({1})  -  config: {2}".format(
        project.get("title", "?"),
        project.get("project_number") or "no #",
        config_path or "DEFAULT (no project config found)",
    )

    out_path = _report_path(doc, "qa")
    reporters.render_html("QA Compliance Check", label, findings, out_path)
    reporters.print_console("QA Compliance Check", findings, output)
    return out_path, findings
