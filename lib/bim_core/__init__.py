# -*- coding: utf-8 -*-
"""bim_core - shared library used by every QA / automation tool in
this pyRevit extension.

What lives here:
    core/                category + discipline registries, MEP system
                         classification reader, geometry helpers,
                         per-category size BuiltInParameter map.
    rules_engine/        Rule + RulePipeline base classes plus the
                         shape-of-an-element rules every tool reuses
                         (length, orientation, size, visibility,
                         system classification, family name pattern).
    element_filters.py   per-category element collection.
    log.py               per-project file logger.

Tool-specific code (Auto Tag's NotAlreadyTaggedRule + tagging engine,
Auto Dimension's AlreadyDimensionedRule + dimensioning engine, etc.)
stays in its own lib next to this one and imports from here.
"""
