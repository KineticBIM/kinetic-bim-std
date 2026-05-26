# -*- coding: utf-8 -*-
"""
annotation_qa
=============

Annotation QA & intelligent tagging engine for the Kinetic pyRevit extension.

Layout:
    element_filters.py  - Revit element collection + length / orientation logic.
    tagging_engine.py   - Tag detection (which elements already have tags) and
                          tag placement.
    qa_engine.py        - Orchestrates scan -> filter -> place -> report.
    rules.py            - Rule options + JSON config merge.
    ui.py / ui.xaml     - WPF dialog (pyRevit forms.WPFWindow).
    log.py              - Centralised file logger under <project>/.bim/logs/.
    configs/            - Default + project-specific JSON config templates.

Version 1 supports a single rule: untagged cable trays over a minimum length
in the active view. New categories / rules slot in via the same engine without
UI surgery.
"""

__version__ = "0.1.0"
