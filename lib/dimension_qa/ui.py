# -*- coding: utf-8 -*-
"""WPF dialog for Auto Dimension (v1).

Per-profile architecture mirroring annotation_qa.ui:
    1. User picks a discipline + ticks subcategories.
    2. Each ticked subcategory becomes a row in the central DataGrid.
       Filters, measurement reference, reference target, dimension
       style, and offset are edited per row.
    3. Scan / Place Dimensions / Save Report / Save Excel read the
       live profiles off the rows.

v1 filters the discipline subcategory list to linear MEP categories
only (cable_tray, conduit, duct, pipe). Other bindings are present
in the registry (Mechanical Equipment, Pipe Accessories etc.) but
won't show up here until later versions implement strategies for
non-linear categories.
"""

import os

from Autodesk.Revit.DB import (
    Element, FilteredElementCollector, DimensionType,
)
from System.Collections.ObjectModel import ObservableCollection
from System.ComponentModel import (
    INotifyPropertyChanged,
    PropertyChangedEventArgs,
)

from pyrevit import forms

from bim_core import errors, log as log_module
from bim_core.core import discipline_config

from dimension_qa import (
    config_io,
    profiles as profile_module,
    dimensioning_engine,
    measurement_strategies,
    reporting,
    target_strategies,
)


XAML_FILE = os.path.join(os.path.dirname(__file__), "ui.xaml")


# v1 only handles these four categories. Drives the subcategory list
# filter so users don't get rows they can't actually dimension.
_V1_CATEGORIES = ("cable_tray", "conduit", "duct", "pipe")


# ============================================================================
# Combo option wrappers
# ============================================================================

class _ComboOption(object):
    """Generic ComboBox item: a Display string + a payload value.

    WPF compares SelectedItem by reference, so the row caches its
    selected option object instead of re-resolving each access.
    """

    def __init__(self, key, display, payload=None):
        self.key = key
        self.Display = display
        self.payload = payload

    def __repr__(self):
        return "<_ComboOption {0}>".format(self.Display)


# ============================================================================
# ProfileRow - WPF-bindable wrapper around a DimensioningProfile.
# ============================================================================

class ProfileRow(INotifyPropertyChanged):
    """One DataGrid row backed by a DimensioningProfile.

    Editable properties two-way-bind to grid cells; setters mutate
    the profile and raise PropertyChanged so WPF re-reads the value.
    Strategy options + dimension style options are per-row collections
    populated at construction.
    """

    def __init__(self, profile, dimension_style_options):
        self._profile = profile
        self._handlers = []

        # Build the per-row strategy + style option collections.
        self._measurement_options = self._build_measurement_options()
        self._target_options = self._build_target_options()
        self._style_options = list(dimension_style_options)

        self._selected_measurement = self._initial_measurement_option()
        self._selected_target = self._initial_target_option()
        self._selected_style = self._initial_style_option()

    # ---- INotifyPropertyChanged plumbing -----------------------------------

    def add_PropertyChanged(self, handler):
        self._handlers.append(handler)

    def remove_PropertyChanged(self, handler):
        try:
            self._handlers.remove(handler)
        except ValueError:
            pass

    def _notify(self, prop_name):
        args = PropertyChangedEventArgs(prop_name)
        for h in list(self._handlers):
            try:
                h(self, args)
            except Exception:
                pass

    # ---- Backing access ----------------------------------------------------

    @property
    def profile(self):
        return self._profile

    # ---- Read-only display -------------------------------------------------

    @property
    def DisciplineLabel(self):
        try:
            return discipline_config.get(self._profile.discipline_key).label
        except KeyError:
            return self._profile.discipline_key or ""

    @property
    def SubcategoryLabel(self):
        return self._profile.binding.label

    # ---- Common editable ---------------------------------------------------

    @property
    def Enabled(self):
        return self._profile.enabled
    @Enabled.setter
    def Enabled(self, value):
        v = bool(value)
        if self._profile.enabled != v:
            self._profile.enabled = v
            self._notify("Enabled")

    @property
    def MinLengthText(self):
        return _format_optional(self._profile.min_length_mm)
    @MinLengthText.setter
    def MinLengthText(self, value):
        self._profile.min_length_mm = _parse_optional(value)
        self._notify("MinLengthText")

    @property
    def MaxLengthText(self):
        return _format_optional(self._profile.max_length_mm)
    @MaxLengthText.setter
    def MaxLengthText(self, value):
        self._profile.max_length_mm = _parse_optional(value)
        self._notify("MaxLengthText")

    @property
    def HorizontalOnly(self):
        return self._profile.horizontal_only
    @HorizontalOnly.setter
    def HorizontalOnly(self, value):
        v = bool(value)
        if self._profile.horizontal_only != v:
            self._profile.horizontal_only = v
            if v and self._profile.vertical_only:
                self._profile.vertical_only = False
                self._notify("VerticalOnly")
            self._notify("HorizontalOnly")

    @property
    def VerticalOnly(self):
        return self._profile.vertical_only
    @VerticalOnly.setter
    def VerticalOnly(self, value):
        v = bool(value)
        if self._profile.vertical_only != v:
            self._profile.vertical_only = v
            if v and self._profile.horizontal_only:
                self._profile.horizontal_only = False
                self._notify("HorizontalOnly")
            self._notify("VerticalOnly")

    @property
    def OrientationTolText(self):
        return _format_optional(self._profile.orientation_tol_deg)
    @OrientationTolText.setter
    def OrientationTolText(self, value):
        v = _parse_optional(value)
        self._profile.orientation_tol_deg = v if v is not None else 15.0
        self._notify("OrientationTolText")

    @property
    def CurrentViewOnly(self):
        # v1 hard-locked: validation rejects unchecked. The grid
        # column is also styled disabled (LockedCell).
        return self._profile.current_view_only
    @CurrentViewOnly.setter
    def CurrentViewOnly(self, value):
        v = bool(value)
        if self._profile.current_view_only != v:
            self._profile.current_view_only = v
            self._notify("CurrentViewOnly")

    @property
    def SkipAlreadyDimensioned(self):
        return self._profile.skip_already_dimensioned
    @SkipAlreadyDimensioned.setter
    def SkipAlreadyDimensioned(self, value):
        v = bool(value)
        if self._profile.skip_already_dimensioned != v:
            self._profile.skip_already_dimensioned = v
            self._notify("SkipAlreadyDimensioned")

    @property
    def OffsetDistanceText(self):
        return _format_optional(self._profile.offset_distance_mm)
    @OffsetDistanceText.setter
    def OffsetDistanceText(self, value):
        v = _parse_optional(value)
        self._profile.offset_distance_mm = v if v is not None else 200.0
        self._notify("OffsetDistanceText")

    # ---- Measurement reference dropdown -----------------------------------

    @property
    def MeasurementOptions(self):
        return self._measurement_options

    @property
    def SelectedMeasurementOption(self):
        return self._selected_measurement
    @SelectedMeasurementOption.setter
    def SelectedMeasurementOption(self, value):
        self._selected_measurement = value
        if value is not None:
            self._profile.measurement_reference = value.key
        self._notify("SelectedMeasurementOption")

    def _build_measurement_options(self):
        out = []
        for key, label in measurement_strategies.applicable_for(
                self._profile.category_key):
            out.append(_ComboOption(key, label))
        return out

    def _initial_measurement_option(self):
        target = self._profile.measurement_reference
        for o in self._measurement_options:
            if o.key == target:
                return o
        return self._measurement_options[0] if self._measurement_options else None

    # ---- Reference target dropdown -----------------------------------------

    @property
    def TargetOptions(self):
        return self._target_options

    @property
    def SelectedTargetOption(self):
        return self._selected_target
    @SelectedTargetOption.setter
    def SelectedTargetOption(self, value):
        self._selected_target = value
        if value is not None:
            self._profile.reference_target = value.key
        self._notify("SelectedTargetOption")

    def _build_target_options(self):
        out = []
        for key, label in target_strategies.applicable_for(
                self._profile.category_key):
            out.append(_ComboOption(key, label))
        return out

    def _initial_target_option(self):
        target = self._profile.reference_target
        for o in self._target_options:
            if o.key == target:
                return o
        return self._target_options[0] if self._target_options else None

    # ---- Dimension style dropdown -----------------------------------------

    @property
    def DimensionStyleOptions(self):
        return self._style_options

    @property
    def SelectedDimensionStyleOption(self):
        return self._selected_style
    @SelectedDimensionStyleOption.setter
    def SelectedDimensionStyleOption(self, value):
        self._selected_style = value
        if value is None:
            self._profile.dimension_style_id = None
        else:
            self._profile.dimension_style_id = value.payload
        self._notify("SelectedDimensionStyleOption")

    def _initial_style_option(self):
        if not self._style_options:
            return None
        target = self._profile.dimension_style_id
        if target is None:
            return self._style_options[0]
        for o in self._style_options:
            if o.payload == target:
                return o
        return self._style_options[0]

    # ---- Capability flags --------------------------------------------------

    @property
    def SupportsHorizontal(self):
        return self._profile.supports("horizontal_only")
    @property
    def SupportsVertical(self):
        return self._profile.supports("vertical_only")


# ============================================================================
# DimensionWindow
# ============================================================================

class DimensionWindow(forms.WPFWindow):

    def __init__(self, doc, view):
        forms.WPFWindow.__init__(self, XAML_FILE)
        self.doc = doc
        self.view = view
        self._logger = log_module.get_logger(doc, tool_name="auto_dimension")
        # Load scan_options + starting profiles from disk - project
        # config wins, then extension default, then in-code defaults.
        # config_io.load_for_doc never raises; on any failure it falls
        # through to the in-code defaults so the dialog always opens
        # in a usable state.
        self.scan_options, self._initial_profiles = config_io.load_for_doc(
            doc, logger=self._logger)
        self.rows = ObservableCollection[object]()
        self._row_cache = {}
        self.records = []
        self._dimension_style_options = self._collect_dimension_styles()
        self._suspend_handlers = True
        try:
            self._populate_disciplines()
            self._select_default_discipline()
            self._populate_subcategories()
            self._select_default_bindings()
            self._sync_rows_to_selection()
        finally:
            self._suspend_handlers = False

        self.profile_grid.ItemsSource = self.rows
        self._render_results("(not scanned yet)")

    # ====================================================================
    # Dimension style collection
    # ====================================================================

    def _collect_dimension_styles(self):
        """Build the per-row dropdown options for Dimension Style.

        Always starts with a 'Use view default' sentinel
        (payload=None) so users can opt out of explicit selection.
        Dimension styles are project-wide so we collect once.
        """
        opts = [_ComboOption(None, "<use view default>", None)]
        try:
            collector = (FilteredElementCollector(self.doc)
                         .OfClass(DimensionType))
            for dt in collector:
                try:
                    name = Element.Name.__get__(dt)
                except Exception:
                    name = "(unnamed)"
                try:
                    dt_id = dt.Id.IntegerValue
                except Exception:
                    continue
                opts.append(_ComboOption(dt_id, name, dt_id))
        except Exception:
            pass
        return opts

    # ====================================================================
    # Discipline + subcategory lists
    # ====================================================================

    def _populate_disciplines(self):
        self.discipline_combo.Items.Clear()
        for key in discipline_config.DISCIPLINE_ORDER:
            self.discipline_combo.Items.Add(
                discipline_config.DISCIPLINE_REGISTRY[key].label)

    def _select_default_discipline(self):
        target = self.scan_options.get("default_discipline_key", "mechanical")
        try:
            idx = discipline_config.DISCIPLINE_ORDER.index(target)
        except ValueError:
            idx = 0
        self.discipline_combo.SelectedIndex = idx

    def _populate_subcategories(self):
        was_suspended = self._suspend_handlers
        self._suspend_handlers = True
        try:
            self.subcategory_list.Items.Clear()
            for binding in self._current_bindings():
                self.subcategory_list.Items.Add(binding.label)
        finally:
            self._suspend_handlers = was_suspended

    def _current_discipline_key(self):
        idx = self.discipline_combo.SelectedIndex
        if idx < 0 or idx >= len(discipline_config.DISCIPLINE_ORDER):
            return None
        return discipline_config.DISCIPLINE_ORDER[idx]

    def _current_discipline(self):
        key = self._current_discipline_key()
        return discipline_config.get_safe(key) if key else None

    def _current_bindings(self):
        """Return only the v1-supported bindings for the current
        discipline (linear MEP categories)."""
        disc = self._current_discipline()
        if disc is None:
            return []
        return [b for b in disc.subcategories
                if b.category_key in _V1_CATEGORIES]

    def _selected_bindings(self):
        bindings = self._current_bindings()
        if not bindings:
            return []
        labels = set()
        try:
            for item in self.subcategory_list.SelectedItems:
                labels.add(item)
        except Exception:
            return []
        return [b for b in bindings if b.label in labels]

    def _select_default_bindings(self):
        """Tick the bindings the loaded profiles target, when they're
        in the v1-supported set.

        self._initial_profiles is whatever config_io.load_for_doc
        returned - project config if present, extension default
        otherwise, in-code default as last resort. Profiles for
        non-current disciplines are still seeded into _row_cache so
        a later discipline switch + re-tick restores their persisted
        values verbatim.
        """
        starting = self._initial_profiles

        # Seed row cache for ALL loaded profiles in v1-supported
        # categories, regardless of discipline. Cross-discipline
        # persistence relies on this. Non-linear bindings are skipped
        # because v1 has no working measurement strategy for them.
        for p in starting:
            if p.binding.category_key not in _V1_CATEGORIES:
                continue
            if p.key not in self._row_cache:
                self._row_cache[p.key] = ProfileRow(
                    p, self._dimension_style_options)

        target_keys = {p.binding.key for p in starting
                       if p.discipline_key == self._current_discipline_key()
                       and p.binding.category_key in _V1_CATEGORIES}
        if not target_keys:
            if self._current_bindings():
                self.subcategory_list.SelectedIndex = 0
            return

        for binding in self._current_bindings():
            if binding.key in target_keys:
                self.subcategory_list.SelectedItems.Add(binding.label)

    # ====================================================================
    # Row sync
    # ====================================================================

    def _sync_rows_to_selection(self):
        disc_key = self._current_discipline_key()
        if disc_key is None:
            self.rows.Clear()
            return

        wanted_bindings = self._selected_bindings()
        wanted_keys = ["{0}/{1}".format(disc_key, b.key)
                       for b in wanted_bindings]

        i = self.rows.Count - 1
        while i >= 0:
            row = self.rows[i]
            if row.profile.key not in wanted_keys:
                self.rows.RemoveAt(i)
            i -= 1

        present_keys = {self.rows[i].profile.key
                        for i in range(self.rows.Count)}
        for binding in wanted_bindings:
            key = "{0}/{1}".format(disc_key, binding.key)
            if key in present_keys:
                continue
            row = self._row_cache.get(key)
            if row is None:
                profile = profile_module.default_profile_for(disc_key, binding)
                row = ProfileRow(profile, self._dimension_style_options)
                self._row_cache[key] = row
            self.rows.Add(row)

    # ====================================================================
    # Event handlers
    # ====================================================================

    def discipline_changed(self, sender, args):  # noqa: ARG002
        if self._suspend_handlers:
            return
        self._suspend_handlers = True
        try:
            self._populate_subcategories()
            if self._current_bindings():
                self.subcategory_list.SelectedItems.Clear()
                self.subcategory_list.SelectedItems.Add(
                    self._current_bindings()[0].label)
        finally:
            self._suspend_handlers = False
        self._sync_rows_to_selection()
        self._invalidate_scan_if_any("discipline changed")

    def subcategories_changed(self, sender, args):  # noqa: ARG002
        if self._suspend_handlers:
            return
        self._sync_rows_to_selection()
        self._invalidate_scan_if_any("selection changed")

    def grid_cell_edited(self, sender, args):  # noqa: ARG002
        if self._suspend_handlers:
            return
        self._invalidate_scan_if_any("profile edited")

    def _invalidate_scan_if_any(self, reason):
        if self.records:
            self.records = []
            self._render_results("({0} - re-scan)".format(reason))

    # ====================================================================
    # Main actions
    # ====================================================================

    def scan_clicked(self, sender, args):  # noqa: ARG002
        profiles = self._current_profiles()
        if not self._validate_or_alert(profiles):
            return
        try:
            with forms.ProgressBar(
                    title="Auto Dimension - scanning active view...",
                    cancellable=True) as pb:
                def _progress(processed, total):
                    if pb.cancelled:
                        return False
                    pb.update_progress(processed, total)
                    return True
                self.records = dimensioning_engine.scan(
                    self.doc, self.view, profiles, progress=_progress)
        except Exception as exc:
            errors.show_error("auto_dimension",
                              "Couldn't scan the model for dimension candidates.",
                              exc=exc, logger=self._logger)
            return

        if self.records is None:
            # scan() returns None when the user clicked Cancel. Reset
            # to [] so place_clicked / report_clicked see no partial
            # data, and surface the cancel in the results pane.
            self.records = []
            self._render_results("(scan cancelled)")
            return

        self._render_results(self._summary_text(profiles))

    def place_clicked(self, sender, args):  # noqa: ARG002
        if not self.records:
            forms.alert("Scan the model first.", exitscript=False)
            return
        pending = sum(1 for r in self.records
                      if r["eligible"] and not r.get("placed"))
        if pending == 0:
            forms.alert("Nothing eligible to dimension.", exitscript=False)
            return
        confirm = forms.alert(
            "Place {0} dimension(s) in '{1}'?".format(pending, self.view.Name),
            ok=False, yes=True, no=True)
        if not confirm:
            return
        profiles = self._current_profiles()
        try:
            dimensioning_engine.place_dimensions(
                self.doc, self.view, self.records, profiles)
        except Exception as exc:
            errors.show_error("auto_dimension",
                              "Couldn't place dimensions in the active view.",
                              exc=exc, logger=self._logger)
            return
        self._render_results(self._summary_text(profiles))

    def report_clicked(self, sender, args):  # noqa: ARG002
        if not self.records:
            forms.alert("Scan the model first.", exitscript=False)
            return
        profiles = self._current_profiles()
        path = reporting.report_path(self.doc, ext="html")
        try:
            reporting.render_html(
                self.records, self.view.Name,
                self.scan_options, profiles, path)
        except Exception as exc:
            errors.show_error("auto_dimension",
                              "Couldn't write the HTML report.",
                              exc=exc, logger=self._logger)
            return
        try:
            os.startfile(path)
        except Exception:
            forms.alert("Report written to:\n{0}".format(path),
                        exitscript=False)

    def csv_clicked(self, sender, args):  # noqa: ARG002
        if not self.records:
            forms.alert("Scan the model first.", exitscript=False)
            return
        profiles = self._current_profiles()
        path = reporting.report_path(self.doc, ext="csv")
        try:
            reporting.render_csv(
                self.records, self.view.Name,
                self.scan_options, profiles, path)
        except Exception as exc:
            errors.show_error("auto_dimension",
                              "Couldn't write the CSV report.",
                              exc=exc, logger=self._logger)
            return
        try:
            os.startfile(path)
        except Exception:
            forms.alert("CSV written to:\n{0}".format(path),
                        exitscript=False)

    def close_clicked(self, sender, args):  # noqa: ARG002
        # Persist the current grid state to the project's
        # auto_dimension.json so the next launch (and the rest of the
        # team via the shared project config) sees the same scan
        # options, measurement references, dimension styles, offsets
        # etc. Best-effort: any failure is logged inside config_io and
        # never blocks the close.
        config_io.save_for_doc(
            self.doc,
            self.scan_options,
            self._current_profiles(),
            logger=self._logger,
        )
        self.Close()

    # ====================================================================
    # Profile / validation helpers
    # ====================================================================

    def _current_profiles(self):
        return [self.rows[i].profile for i in range(self.rows.Count)]

    def _validate_or_alert(self, profiles):
        errors, blocking = profile_module.validate_profiles(profiles)
        if not blocking:
            return True
        scan_err = errors.get("__scan__")
        if scan_err:
            forms.alert(scan_err, exitscript=False)
            return False
        for p in profiles:
            if not p.enabled:
                continue
            err = errors.get(p.key)
            if err:
                forms.alert("{0}\n\n{1}".format(p.label, err),
                            exitscript=False)
                return False
        return False

    # ====================================================================
    # Results pane rendering
    # ====================================================================

    def _render_results(self, text):
        self.results_box.Text = text

    def _summary_text(self, profiles):
        counts = reporting.summary_counts(self.records)
        lines = [
            "View:               {0}".format(self.view.Name),
            "Profiles:           {0}".format(
                ", ".join(p.key for p in profiles if p.enabled) or "(none)"),
            "Total scanned:      {0}".format(counts["total"]),
            "Already dimensioned:{0}".format(counts["already_dimensioned"]),
            "Eligible:           {0}".format(counts["eligible"]),
            "Placed:             {0}".format(counts["placed"]),
            "Failed:             {0}".format(counts["failed"]),
        ]

        grouped = reporting.group_by_profile(self.records, profiles)
        rendered = set()
        if grouped or profiles:
            lines.append("")
            lines.append("By profile:")
        for profile, recs in grouped:
            if profile is None:
                title = "(unattributed)"
            else:
                title = profile.key
                rendered.add(profile.key)
            sub_counts = reporting.summary_counts(recs)
            sub_breakdown = reporting.breakdown_by_rule(recs)
            disabled = (profile is not None and not profile.enabled)
            lines.append(
                "  {0:<32} {1:>4} scanned, {2:>4} eligible, "
                "{3:>4} placed{4}".format(
                    title + ":",
                    sub_counts["total"],
                    sub_counts["eligible"],
                    sub_counts["placed"],
                    "  (disabled)" if disabled else ""))
            for rule_name in sorted(sub_breakdown.keys()):
                lines.append("      excluded by {0:<22} {1}".format(
                    rule_name + ":", sub_breakdown[rule_name]))
        for profile in profiles:
            if profile.key in rendered:
                continue
            if not profile.enabled:
                lines.append("  {0:<32} (disabled)".format(profile.key + ":"))
            else:
                lines.append("  {0:<32} 0 scanned".format(profile.key + ":"))

        lines.append("-" * 78)
        lines.append("{0:>9}  {1:>10}  {2:<24}  {3:<20}  {4}".format(
            "ID", "LENGTH", "PROFILE", "RULE", "STATUS"))
        for r in self.records[:300]:
            if r.get("placed"):
                status = "PLACED"
            elif r.get("placed") is False:
                status = "FAILED ({0})".format(r.get("place_error") or "")
            elif r["eligible"]:
                status = "ELIGIBLE"
            else:
                status = "SKIP ({0})".format(r["skip_reason"])
            length = ("{0:.0f}mm".format(r["length_mm"])
                      if r["length_mm"] is not None else "-")
            rule = r.get("failing_rule") or "-"
            lines.append(
                "{0:>9}  {1:>10}  {2:<24}  {3:<20}  {4}".format(
                    r["id"], length,
                    (r.get("profile_key") or "-")[:24],
                    rule, status))
        if len(self.records) > 300:
            lines.append("... ({0} more rows in HTML report)".format(
                len(self.records) - 300))
        return "\n".join(lines)


# ============================================================================
# Helpers (module-level)
# ============================================================================

def _format_optional(value):
    if value is None:
        return ""
    try:
        return "{0:.0f}".format(float(value))
    except (TypeError, ValueError):
        return ""


def _parse_optional(text):
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None
