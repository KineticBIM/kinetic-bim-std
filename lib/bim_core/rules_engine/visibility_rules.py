# -*- coding: utf-8 -*-
"""View-visibility filter rule.

The view-scoped FilteredElementCollector already drops most invisible
elements, but it can miss the category-hidden case. This rule is added
to the pipeline in active-view scope only; in whole-model scope the
qa_engine handles "is this in the active view?" via a precomputed
visible-id set.
"""

from bim_core.rules_engine.base import Rule


class VisibilityRule(Rule):
    name = "visibility"

    def passes(self, element, context):
        view = context.get("view")
        if view is None:
            return True, None
        try:
            cat = element.Category
            if cat is not None and view.GetCategoryHidden(cat.Id):
                return False, "category hidden in view"
        except Exception:
            pass
        try:
            if element.IsHidden(view):
                return False, "hidden in view"
        except Exception:
            pass
        return True, None
