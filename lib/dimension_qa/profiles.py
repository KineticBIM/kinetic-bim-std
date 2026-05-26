# -*- coding: utf-8 -*-
"""DimensioningProfile - per-subcategory configuration for Auto
Dimension.

Mirrors annotation_qa.profiles.TaggingProfile in shape and discipline-
binding semantics. Each ticked subcategory becomes one
DimensioningProfile carrying its own filters, measurement reference,
reference target, dimension style, and offset distance.

This module imports only sibling Python (no Revit API), so it loads
under both IronPython 2.7 and CPython 3.11+.
"""

from bim_core.core import category_config, discipline_config

from dimension_qa import measurement_strategies, target_strategies


# ---------------------------------------------------------------------------
# Defaults the UI uses when conjuring a new row.
# ---------------------------------------------------------------------------

# Linear MEP starting point: 1m minimum, horizontal-only, centreline-to-
# nearest-grid with 200mm offset. Tuned to match real BIM documentation
# defaults at the practice (most floor plans use ~200mm dim string offsets).
_LINEAR_DEFAULTS = {
    "min_length_mm":            1000.0,
    "max_length_mm":            None,
    "horizontal_only":          True,
    "vertical_only":            False,
    # Degree-based slope tolerance (was absolute 50mm pre-2026-05-22).
    # 15deg covers real MEP coordination drift on long runs while still
    # excluding obvious transitions and risers.
    "orientation_tol_deg":      15.0,
    "current_view_only":        True,
    "skip_already_dimensioned": True,
    "offset_distance_mm":       200.0,
}


# ---------------------------------------------------------------------------
# DimensioningProfile
# ---------------------------------------------------------------------------

class DimensioningProfile(object):
    """Configuration for one ticked subcategory binding.

    Mutable: the UI grid edits these fields in place and the engine
    reads them at scan time. The UI is expected to call .validate()
    before dispatching a scan.

    measurement_reference and reference_target are strategy_keys -
    look them up via measurement_strategies.get(category_key, key)
    and target_strategies.get(key) respectively. dimension_style_id
    is a Revit ElementId.IntegerValue (or None for Revit's default).
    """

    def __init__(self, discipline_key, binding,
                 enabled=True,
                 min_length_mm=None, max_length_mm=None,
                 horizontal_only=False, vertical_only=False,
                 orientation_tol_deg=15.0,
                 current_view_only=True,
                 skip_already_dimensioned=True,
                 measurement_reference=None,
                 reference_target=None,
                 dimension_style_id=None,
                 offset_distance_mm=200.0):
        self.discipline_key = discipline_key
        self.binding = binding
        self.enabled = bool(enabled)
        self.min_length_mm = min_length_mm
        self.max_length_mm = max_length_mm
        self.horizontal_only = bool(horizontal_only)
        self.vertical_only = bool(vertical_only)
        self.orientation_tol_deg = (
            15.0 if orientation_tol_deg is None else orientation_tol_deg)
        self.current_view_only = bool(current_view_only)
        self.skip_already_dimensioned = bool(skip_already_dimensioned)
        # Default measurement reference to centreline when caller
        # doesn't pick one.
        self.measurement_reference = (
            measurement_reference
            or measurement_strategies.default_for(binding.category_key))
        self.reference_target = (
            reference_target or target_strategies.default_target())
        self.dimension_style_id = dimension_style_id
        self.offset_distance_mm = (
            200.0 if offset_distance_mm is None else offset_distance_mm)

    # ----- identity / capability shortcuts ----------------------------------

    @property
    def category_key(self):
        return self.binding.category_key

    @property
    def cfg(self):
        return category_config.get(self.category_key)

    @property
    def key(self):
        """'<discipline>/<binding>' - unique within a session."""
        return "{0}/{1}".format(self.discipline_key, self.binding.key)

    @property
    def label(self):
        try:
            disc_label = discipline_config.get(self.discipline_key).label
        except KeyError:
            disc_label = self.discipline_key
        return "{0} / {1}".format(disc_label, self.binding.label)

    def supports(self, rule_key):
        return self.cfg.supports(rule_key)

    # ----- validation -------------------------------------------------------

    def validate(self):
        """Return the first user-fixable problem, or None."""
        if self.supports("min_length"):
            err = _validate_non_negative(self.min_length_mm, "Minimum length")
            if err:
                return err
        if self.supports("max_length"):
            err = _validate_non_negative(self.max_length_mm, "Maximum length")
            if err:
                return err
            if (self.min_length_mm is not None
                    and self.max_length_mm is not None
                    and self.max_length_mm < self.min_length_mm):
                return ("Maximum length ({0:.0f}mm) must be greater than or "
                        "equal to minimum length ({1:.0f}mm).".format(
                            self.max_length_mm, self.min_length_mm))

        if self.horizontal_only and self.vertical_only:
            return ("Horizontal only and Vertical only cannot both be on. "
                    "Uncheck one.")
        err = _validate_non_negative(
            self.orientation_tol_deg, "Orientation tolerance")
        if err:
            return err
        if self.orientation_tol_deg > 90.0:
            return ("Orientation tolerance ({0:.1f}deg) cannot exceed "
                    "90deg.".format(self.orientation_tol_deg))

        err = _validate_non_negative(
            self.offset_distance_mm, "Offset distance")
        if err:
            return err

        # Strategy keys must resolve in the registries.
        if measurement_strategies.get(
                self.category_key, self.measurement_reference) is None:
            return ("Measurement reference '{0}' does not apply to this "
                    "category.".format(self.measurement_reference))
        if target_strategies.get(self.reference_target) is None:
            return ("Reference target '{0}' is not registered.".format(
                self.reference_target))

        # v1: only current_view_only=True is supported. Multi-view is
        # explicitly out of scope.
        if not self.current_view_only:
            return ("Current view only must stay on in v1. Multi-view "
                    "automation is on the v2 list.")

        return None

    # ----- summary (for HTML report) ----------------------------------------

    def active_rule_summary(self):
        parts = []
        if self.supports("min_length") and self.min_length_mm is not None:
            parts.append("min length >= {0:.0f}mm".format(self.min_length_mm))
        if self.supports("max_length") and self.max_length_mm is not None:
            parts.append("max length <= {0:.0f}mm".format(self.max_length_mm))
        if self.supports("horizontal_only") and self.horizontal_only:
            parts.append("horizontal only (<={0:.1f}deg slope)".format(
                self.orientation_tol_deg))
        elif self.supports("vertical_only") and self.vertical_only:
            parts.append("vertical only (<={0:.1f}deg from vertical)".format(
                self.orientation_tol_deg))
        if self.binding.has_system_filter():
            parts.append("system in ({0})".format(", ".join(
                sorted(self.binding.system_classifications))))
        if self.skip_already_dimensioned:
            parts.append("skip already dimensioned")
        parts.append("ref: {0}".format(self.measurement_reference))
        parts.append("target: {0}".format(self.reference_target))
        parts.append("offset: {0:.0f}mm".format(self.offset_distance_mm))
        return "; ".join(parts) if parts else "(no filters)"

    # ----- serialisation ----------------------------------------------------

    def to_dict(self):
        return {
            "discipline":               self.discipline_key,
            "binding":                  self.binding.key,
            "enabled":                  self.enabled,
            "min_length_mm":            self.min_length_mm,
            "max_length_mm":            self.max_length_mm,
            "horizontal_only":          self.horizontal_only,
            "vertical_only":            self.vertical_only,
            "orientation_tol_deg":      self.orientation_tol_deg,
            "current_view_only":        self.current_view_only,
            "skip_already_dimensioned": self.skip_already_dimensioned,
            "measurement_reference":    self.measurement_reference,
            "reference_target":         self.reference_target,
            "dimension_style_id":       self.dimension_style_id,
            "offset_distance_mm":       self.offset_distance_mm,
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            return None
        disc_key = data.get("discipline")
        binding_key = data.get("binding")
        binding = discipline_config.find_binding(disc_key, binding_key)
        if binding is None:
            return None
        return cls(
            discipline_key=disc_key,
            binding=binding,
            enabled=data.get("enabled", True),
            min_length_mm=data.get("min_length_mm"),
            max_length_mm=data.get("max_length_mm"),
            horizontal_only=data.get("horizontal_only", False),
            vertical_only=data.get("vertical_only", False),
            # Legacy "orientation_tol_mm" key (absolute Z delta) is
            # dropped in favour of degrees; ignore it and use the new
            # default rather than guessing a conversion.
            orientation_tol_deg=data.get("orientation_tol_deg", 15.0),
            current_view_only=data.get("current_view_only", True),
            skip_already_dimensioned=data.get(
                "skip_already_dimensioned", True),
            measurement_reference=data.get("measurement_reference"),
            reference_target=data.get("reference_target"),
            dimension_style_id=data.get("dimension_style_id"),
            offset_distance_mm=data.get("offset_distance_mm", 200.0),
        )

    def __repr__(self):
        return "<DimensioningProfile {0} enabled={1}>".format(
            self.key, self.enabled)


# ---------------------------------------------------------------------------
# Construction helpers
# ---------------------------------------------------------------------------

def default_profile_for(discipline_key, binding):
    """Construct a DimensioningProfile with linear MEP defaults.

    v1 only supports linear MEP (cable_tray, conduit, duct, pipe);
    callers are expected to gate on category_config.get(...).geometry_kind
    == "linear" before invoking this helper.
    """
    return DimensioningProfile(
        discipline_key=discipline_key,
        binding=binding,
        enabled=True,
        min_length_mm=_LINEAR_DEFAULTS["min_length_mm"],
        max_length_mm=_LINEAR_DEFAULTS["max_length_mm"],
        horizontal_only=_LINEAR_DEFAULTS["horizontal_only"],
        vertical_only=_LINEAR_DEFAULTS["vertical_only"],
        orientation_tol_deg=_LINEAR_DEFAULTS["orientation_tol_deg"],
        current_view_only=_LINEAR_DEFAULTS["current_view_only"],
        skip_already_dimensioned=_LINEAR_DEFAULTS["skip_already_dimensioned"],
        measurement_reference=measurement_strategies.default_for(
            binding.category_key),
        reference_target=target_strategies.default_target(),
        dimension_style_id=None,
        offset_distance_mm=_LINEAR_DEFAULTS["offset_distance_mm"],
    )


# ---------------------------------------------------------------------------
# Aggregate validation
# ---------------------------------------------------------------------------

def validate_profiles(profiles):
    """Run validate() across every profile.

    Returns (errors_by_profile_key, has_blocking).
    Same contract as annotation_qa.profiles.validate_profiles.
    """
    errors = {}
    enabled_count = 0
    blocking = False
    for p in profiles:
        err = p.validate()
        if err:
            errors[p.key] = err
            if p.enabled:
                blocking = True
        if p.enabled:
            enabled_count += 1
    if enabled_count == 0:
        errors.setdefault("__scan__",
                          "No subcategory is enabled. Tick at least one row.")
        blocking = True
    return errors, blocking


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_non_negative(value, label):
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "{0} must be a number.".format(label)
    if v < 0:
        return "{0} cannot be negative.".format(label)
    return None
