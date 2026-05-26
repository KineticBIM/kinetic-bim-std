# -*- coding: utf-8 -*-
"""Auto Dimension - rule-based MEP dimensioning.

Per-subcategory profile architecture mirroring annotation_qa: each
ticked subcategory becomes its own DimensioningProfile carrying its
own filter values, measurement reference (where on the element the
dimension is taken from), reference target (what the dimension
measures to), dimension style, and offset distance.

v1 scope: linear MEP only (Cable Trays, Conduits, Ducts, Pipes),
active view only, nearest grid target, aligned dimensions only.
"""
