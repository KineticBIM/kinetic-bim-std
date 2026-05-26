# -*- coding: utf-8 -*-
"""XML parsing layer.

Takes the XML files Navisworks produces (ClashDetective report XML
and viewpoints XML) and returns the plain-Python dataclasses defined
in `data/models.py`. No Navisworks dependency, fully unit-tested
against committed XML fixtures in tests/clash_coordination/fixtures/.
"""
