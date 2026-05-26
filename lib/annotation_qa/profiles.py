# -*- coding: utf-8 -*-
"""Per-subcategory tagging profile.

A TaggingProfile owns every value the rule pipeline + tag placement
need for one ticked binding: its filters, its size constraints, its
tag family, its leader/skip preferences. There is no shared options
dict in v5 - the engine iterates a list of profiles, builds one
pipeline per profile, and picks tag symbols per profile.

The data shape stays JSON-friendly so projects can persist a per-
profile auto_tag.json. See `to_dict` / `from_dict` for the on-disk
schema.

This module imports only sibling Python modules (no Revit API), so it
loads under both IronPython 2.7 (the pyRevit pushbutton runtime) and
CPython 3.11+ (the analysis venv / future MCP exposure).
"""

from bim_core.core import category_config, discipline_config


# ---------------------------------------------------------------------------
# Placement mode constants.
# ---------------------------------------------------------------------------
#
# The strategy factory (annotation_qa.placement_strategies) and the UI grid
# import these so allowed values live in one place. Adding a new mode is a
# matter of adding it here, teaching the factory to map it to a Strategy,
# and adding a matching dropdown entry in the UI.

PLACEMENT_MODE_ON_ELEMENT = "on_element"
PLACEMENT_MODE_ADJACENT   = "adjacent"
PLACEMENT_MODES = (PLACEMENT_MODE_ON_ELEMENT, PLACEMENT_MODE_ADJACENT)

PLACEMENT_SIDE_AUTO  = "auto"
PLACEMENT_SIDE_ABOVE = "above"
PLACEMENT_SIDE_BELOW = "below"
PLACEMENT_SIDE_LEFT  = "left"
PLACEMENT_SIDE_RIGHT = "right"
PLACEMENT_SIDES = (PLACEMENT_SIDE_AUTO, PLACEMENT_SIDE_ABOVE,
                   PLACEMENT_SIDE_BELOW, PLACEMENT_SIDE_LEFT,
                   PLACEMENT_SIDE_RIGHT)

# Default "adjacent" delivers the v6 feature request out of the box:
# unmigrated project configs (no placement_mode key) automatically pick
# up adjacent placement at the next scan. Teams that want a profile
# back on the pre-v6 curve-midpoint behaviour set placement_mode
# explicitly to "on_element" in their project's auto_tag.json (or via
# the UI grid once phase 6 lands).
DEFAULT_PLACEMENT_MODE  = PLACEMENT_MODE_ADJACENT
DEFAULT_OFFSET_MM       = 300.0
DEFAULT_PREFERRED_SIDE  = PLACEMENT_SIDE_AUTO


# ---------------------------------------------------------------------------
# Defaults the UI uses when conjuring a new row.
# ---------------------------------------------------------------------------

# Linear MEP starting point; tuned to match the v4 defaults so users
# don't notice a behaviour shift on first launch.
_LINEAR_DEFAULTS = {
    "min_length_mm":       1000.0,
    "max_length_mm":       None,
    "horizontal_only":     True,
    "vertical_only":       False,
    # Angle-from-horizontal tolerance for the horizontal_only /
    # vertical_only rules. 15deg matches "looks horizontal in plan"
    # for cable trays/ducts/pipes that drift a few mm/m without
    # being deliberately sloped. Pre-2026-05-22 default was 50mm
    # absolute, which mis-rejected long-but-slightly-drifting runs.
    "orientation_tol_deg": 15.0,
}

# Point categories: no length / orientation filters apply, so we only
# carry the universal toggles. Defaults to "skip already tagged" so
# rerunning the tool doesn't double-tag.
_POINT_DEFAULTS = {
    "min_length_mm":       None,
    "max_length_mm":       None,
    "horizontal_only":     False,
    "vertical_only":       False,
    "orientation_tol_deg": 15.0,  # carried for forward-compat; unused
}


# ---------------------------------------------------------------------------
# TaggingProfile
# ---------------------------------------------------------------------------

class TaggingProfile(object):
    """Configuration for one ticked subcategory binding.

    Mutable: the UI grid edits these fields in place and the engine
    reads them at scan time. The UI is expected to call .validate()
    before dispatching a scan.

    size_filters is a flat dict keyed by '{dim}_mm_min' / '{dim}_mm_max'
    where {dim} is one of the binding category's size_dimensions
    (cf. core.category_config.REGISTRY). Unset values are None.
    """

    def __init__(self, discipline_key, binding,
                 enabled=True,
                 min_length_mm=None, max_length_mm=None,
                 horizontal_only=False, vertical_only=False,
                 orientation_tol_deg=15.0,
                 size_filters=None,
                 skip_already_tagged=True,
                 add_leader=False,
                 tag_symbol_id=None,
                 placement_mode=None,
                 offset_mm=None,
                 preferred_side=None):
        self.discipline_key = discipline_key
        self.binding = binding
        self.enabled = bool(enabled)
        self.min_length_mm = min_length_mm
        self.max_length_mm = max_length_mm
        self.horizontal_only = bool(horizontal_only)
        self.vertical_only = bool(vertical_only)
        self.orientation_tol_deg = (
            15.0 if orientation_tol_deg is None else orientation_tol_deg)
        self.size_filters = self._normalize_size_filters(size_filters)
        self.skip_already_tagged = bool(skip_already_tagged)
        self.add_leader = bool(add_leader)
        self.tag_symbol_id = tag_symbol_id
        self.placement_mode = (
            DEFAULT_PLACEMENT_MODE if placement_mode is None
            else placement_mode)
        self.offset_mm = (
            DEFAULT_OFFSET_MM if offset_mm is None else offset_mm)
        self.preferred_side = (
            DEFAULT_PREFERRED_SIDE if preferred_side is None
            else preferred_side)

    # ----- identity / capability shortcuts ----------------------------------

    @property
    def category_key(self):
        return self.binding.category_key

    @property
    def cfg(self):
        return category_config.get(self.category_key)

    @property
    def key(self):
        """Stable identifier for this profile across a session.

        '<discipline>/<binding>' is unique because every binding key is
        unique within its discipline (see discipline_config registry).
        """
        return "{0}/{1}".format(self.discipline_key, self.binding.key)

    @property
    def label(self):
        """User-facing label - used in reports and the results panel."""
        try:
            disc_label = discipline_config.get(self.discipline_key).label
        except KeyError:
            disc_label = self.discipline_key
        return "{0} / {1}".format(disc_label, self.binding.label)

    def supports(self, rule_key):
        return self.cfg.supports(rule_key)

    @property
    def effective_add_leader(self):
        """The leader flag the engine actually uses.

        Adjacent placement offsets the tag away from its host, so a
        leader is required for the tag to read as belonging to the
        element. We force it on rather than mutating the stored
        add_leader value, which preserves the user's intent if they
        later switch the profile back to on_element placement.

        The UI is expected to grey out the add_leader checkbox while
        placement_mode is adjacent so users see why their preference
        is being overridden.
        """
        if self.placement_mode == PLACEMENT_MODE_ADJACENT:
            return True
        return self.add_leader

    def has_size_dimensions(self):
        return bool(self.cfg.size_dimensions)

    # ----- normalisation ----------------------------------------------------

    def _normalize_size_filters(self, supplied):
        """Return a dict with min+max slots for every dimension this
        profile's category supports, copying user values where present.

        Storing all the slots up front means UI/grid code can read/write
        a fixed set of keys per profile without checking 'is this set'
        each time.
        """
        out = {}
        for dim in self.cfg.size_dimensions:
            out["{0}_mm_min".format(dim)] = None
            out["{0}_mm_max".format(dim)] = None
        if not supplied:
            return out
        for k, v in supplied.items():
            if k in out:
                out[k] = v
        return out

    # ----- validation -------------------------------------------------------

    def validate(self):
        """Return the first user-fixable problem on this profile, or None.

        Engine invariants (e.g. tag symbol not loaded) are checked at
        scan / place time; this is for grid input.
        """
        # Length - allow blank (None) but reject negatives and bad ordering.
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

        # Orientation.
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

        # Size filters - per dimension, max >= min when both set.
        for dim in self.cfg.size_dimensions:
            mn = self.size_filters.get("{0}_mm_min".format(dim))
            mx = self.size_filters.get("{0}_mm_max".format(dim))
            err = _validate_non_negative(mn, "{0} min".format(dim.title()))
            if err:
                return err
            err = _validate_non_negative(mx, "{0} max".format(dim.title()))
            if err:
                return err
            if mn is not None and mx is not None and mx < mn:
                return ("{0} max ({1:.0f}mm) must be >= min "
                        "({2:.0f}mm).".format(dim.title(), mx, mn))

        # Placement.
        if self.placement_mode not in PLACEMENT_MODES:
            return ("Placement mode '{0}' is not recognised. Expected one "
                    "of: {1}.".format(
                        self.placement_mode, ", ".join(PLACEMENT_MODES)))
        if self.preferred_side not in PLACEMENT_SIDES:
            return ("Preferred side '{0}' is not recognised. Expected one "
                    "of: {1}.".format(
                        self.preferred_side, ", ".join(PLACEMENT_SIDES)))
        err = _validate_non_negative(self.offset_mm, "Offset")
        if err:
            return err

        return None

    # ----- summary (for HTML report) ----------------------------------------

    def active_rule_summary(self):
        """Short, human-readable summary of the filters in force.

        Composed for the per-profile section of the HTML report so a
        reader can see what the run actually filtered on without
        clicking through to the rule table.
        """
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
        size_bits = []
        for dim in self.cfg.size_dimensions:
            mn = self.size_filters.get("{0}_mm_min".format(dim))
            mx = self.size_filters.get("{0}_mm_max".format(dim))
            if mn is not None:
                size_bits.append("{0}>={1:.0f}".format(dim, mn))
            if mx is not None:
                size_bits.append("{0}<={1:.0f}".format(dim, mx))
        if size_bits:
            parts.append("size: " + ", ".join(size_bits))
        if self.binding.has_system_filter():
            parts.append("system in ({0})".format(", ".join(
                sorted(self.binding.system_classifications))))
        if self.binding.has_family_filter():
            parts.append("family ~ ({0})".format(", ".join(
                self.binding.family_name_patterns)))
        if self.skip_already_tagged:
            parts.append("skip already tagged")
        if self.effective_add_leader:
            parts.append("with leader")
        if self.placement_mode == PLACEMENT_MODE_ADJACENT:
            if self.preferred_side == PLACEMENT_SIDE_AUTO:
                parts.append("adjacent ({0:.0f}mm)".format(self.offset_mm))
            else:
                parts.append("adjacent ({0:.0f}mm, side={1})".format(
                    self.offset_mm, self.preferred_side))
        return "; ".join(parts) if parts else "(no filters)"

    # ----- serialisation ----------------------------------------------------

    def to_dict(self):
        """JSON-friendly dict for project / standards persistence."""
        return {
            "discipline":           self.discipline_key,
            "binding":              self.binding.key,
            "enabled":              self.enabled,
            "min_length_mm":        self.min_length_mm,
            "max_length_mm":        self.max_length_mm,
            "horizontal_only":      self.horizontal_only,
            "vertical_only":        self.vertical_only,
            "orientation_tol_deg":  self.orientation_tol_deg,
            "size_filters":         dict(self.size_filters),
            "skip_already_tagged":  self.skip_already_tagged,
            "add_leader":           self.add_leader,
            "tag_symbol_id":        self.tag_symbol_id,
            "placement_mode":       self.placement_mode,
            "offset_mm":            self.offset_mm,
            "preferred_side":       self.preferred_side,
        }

    @classmethod
    def from_dict(cls, data):
        """Hydrate a TaggingProfile from a to_dict payload.

        Returns None if the discipline/binding pair is unknown - callers
        should treat that as a config that targets a binding the
        registry no longer carries (e.g. renamed in a later release).
        """
        if not isinstance(data, dict):
            return None
        disc_key = data.get("discipline")
        binding_key = data.get("binding")
        binding = discipline_config.find_binding(disc_key, binding_key)
        if binding is None:
            return None
        # Legacy configs persisted "orientation_tol_mm" (absolute Z
        # delta). We dropped that field in favour of degree-based
        # "orientation_tol_deg". If only the legacy key is present,
        # ignore the value and use the new default - converting mm to
        # degrees would need a length we don't have, and the old 50mm
        # default produced the false-rejection problem we're fixing.
        return cls(
            discipline_key=disc_key,
            binding=binding,
            enabled=data.get("enabled", True),
            min_length_mm=data.get("min_length_mm"),
            max_length_mm=data.get("max_length_mm"),
            horizontal_only=data.get("horizontal_only", False),
            vertical_only=data.get("vertical_only", False),
            orientation_tol_deg=data.get("orientation_tol_deg", 15.0),
            size_filters=data.get("size_filters"),
            skip_already_tagged=data.get("skip_already_tagged", True),
            add_leader=data.get("add_leader", False),
            tag_symbol_id=data.get("tag_symbol_id"),
            placement_mode=data.get("placement_mode"),
            offset_mm=data.get("offset_mm"),
            preferred_side=data.get("preferred_side"),
        )

    def __repr__(self):
        return "<TaggingProfile {0} enabled={1}>".format(
            self.key, self.enabled)


# ---------------------------------------------------------------------------
# Construction helpers
# ---------------------------------------------------------------------------

def default_profile_for(discipline_key, binding):
    """Construct a TaggingProfile with category-appropriate defaults.

    Linear MEP categories get the v4 default of min_length=1000mm +
    horizontal_only=True (matches what users were getting from
    DEFAULT_OPTIONS pre-refactor). Point categories drop those filters
    since their pipelines never run them.

    The caller usually sets tag_symbol_id later from a remembered
    project preference.
    """
    cfg = category_config.get_safe(binding.category_key)
    if cfg is None:
        # Unknown category - construct a stub profile so the UI doesn't
        # crash; validate() will likely flag it.
        defaults = _POINT_DEFAULTS
    elif cfg.geometry_kind == "linear":
        defaults = _LINEAR_DEFAULTS
    else:
        defaults = _POINT_DEFAULTS

    return TaggingProfile(
        discipline_key=discipline_key,
        binding=binding,
        enabled=True,
        min_length_mm=defaults["min_length_mm"],
        max_length_mm=defaults["max_length_mm"],
        horizontal_only=defaults["horizontal_only"],
        vertical_only=defaults["vertical_only"],
        orientation_tol_deg=defaults["orientation_tol_deg"],
        size_filters=None,
        skip_already_tagged=True,
        add_leader=False,
        tag_symbol_id=None,
        placement_mode=DEFAULT_PLACEMENT_MODE,
        offset_mm=DEFAULT_OFFSET_MM,
        preferred_side=DEFAULT_PREFERRED_SIDE,
    )


# ---------------------------------------------------------------------------
# Aggregate validation (called from the UI before dispatching a scan)
# ---------------------------------------------------------------------------

def validate_profiles(profiles):
    """Run validate() across every profile.

    Returns (errors_by_profile_key, has_blocking).
    has_blocking is True when no profile is enabled, OR any enabled
    profile fails its own validate(). Disabled profiles' errors are
    surfaced for visibility but don't block - the scan ignores them.
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
