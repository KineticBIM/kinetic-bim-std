# -*- coding: utf-8 -*-
"""Reusable helpers for the Auto Tag tool.

geometry_utils  - unit conversion + curve geometry (length, endpoints,
                  midpoint, elevation delta, orientation tests).
parameter_utils - per-category size parameter access (cable tray width,
                  conduit diameter, duct width/height, pipe diameter).

Nothing in this package imports from rules_engine, element_filters,
tagging_engine, or qa_engine. Keep it leaf so the rule classes and the
QA engine can both depend on it without import cycles.
"""
