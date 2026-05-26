# -*- coding: utf-8 -*-
"""OnElementStrategy - tag head sits on the host element.

The pre-v6 behaviour: a single candidate at the element's origin.
This is exposed as a strategy so the engine has one code path for
every placement_mode - "on_element" returns a one-candidate generator
and the clash loop terminates immediately.

Selected when profile.placement_mode == "on_element". Also acts as
the engine's terminal fallback when an adjacent strategy yields
nothing (e.g. linear host with no direction vector).
"""

from bim_core.core import geometry_utils

from annotation_qa.placement_strategies.base import PlacementStrategy


class OnElementStrategy(PlacementStrategy):

    key = "on_element"
    label = "On element"

    def propose_positions(self, view, element, profile):
        origin = geometry_utils.element_origin(element)
        if origin is None:
            return
        yield origin
