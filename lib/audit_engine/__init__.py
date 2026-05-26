# -*- coding: utf-8 -*-
"""
audit_engine
============

Shared scanning and reporting engine for the Health Audit and QA Check buttons.

Layout:
    scanners.py   - Reads raw facts from the Revit model (warnings, worksets,
                    views, links, parameters, etc.). No judgement, just data.
    rules.py      - Rule classes that take scan results and produce findings.
                    Health rules are hardcoded; QA rules are loaded from JSON.
    reporters.py  - Turn findings into HTML / Excel / console output.
    runner.py     - Orchestrates: run scanners -> apply rules -> render report.
"""

__version__ = "0.1.0"
