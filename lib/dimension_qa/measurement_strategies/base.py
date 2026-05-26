# -*- coding: utf-8 -*-
"""MeasurementReferenceStrategy - decides WHERE on an MEP element the
dimension is taken from.

A strategy returns a (Reference, anchor_xyz) pair the dimensioning
engine pins one end of the dimension to. anchor_xyz is the geometric
representative point on the reference; the engine uses it to compute
the dim-line geometry but Revit measures from the Reference itself, so
the dimension VALUE is exact.

Strategies are stateless singletons - one instance per concrete class,
registered with `__init__.REGISTRY` keyed on (category_key,
strategy_key).

When a strategy can't produce a reference (e.g. user picked "Top of
Pipe" but the pipe is round and Revit does not expose a flat top
face), it returns (None, "human-readable reason"). The engine logs
the reason and skips the element rather than placing a wrong dim.
"""


class MeasurementReferenceStrategy(object):
    """Base class for measurement reference strategies.

    Subclasses set `key` (JSON identifier) and `label` (UI text), and
    override `applies_to` + `get_reference`.
    """

    key = "base"
    label = "Base"

    @classmethod
    def applies_to(cls, category_key):
        """True when this strategy is valid for the category. Drives
        the per-row dropdown in the UI."""
        return False

    def get_reference(self, doc, view, element, target_anchor=None):
        """Return (Reference, anchor_xyz) or (None, error_string).

        Reference: a Revit DB.Reference suitable for the dim-end.
        anchor_xyz: representative point on that reference, used to
                    seed the dimension line geometry.
        target_anchor: where the OTHER end of the dim is going. The
                    engine resolves the target reference first and
                    passes its anchor here so direction-aware
                    strategies (CentrelineStrategy picking the closer
                    end cap, future "edge facing target" strategies)
                    can choose intelligently. None when called outside
                    the engine.
        Error path: return (None, "reason") when the strategy can't
                    extract a suitable reference. The engine attributes
                    the skip to this strategy in the report.
        """
        raise NotImplementedError
