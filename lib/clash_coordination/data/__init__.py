# -*- coding: utf-8 -*-
"""Plain-Python dataclasses describing a coordination run.

No Navisworks or Revit imports - these objects are produced by the
parsing layer from Navisworks XML exports and consumed by the
reporting, history, and UI layers. They cross the COM/non-COM
boundary, and they're the unit-test surface for everything except
the COM layer itself.
"""
