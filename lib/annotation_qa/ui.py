# -*- coding: utf-8 -*-
"""WPF dialog for the Auto Tag tool (v5).

Per-profile architecture:
    1. User picks a discipline from the top dropdown and ticks one or
       more subcategories in the multi-select list.
    2. Each ticked subcategory materialises as a row in the central
       DataGrid. Filter values, size constraints, tag family, leader
       and skip preferences are edited per row.
    3. The window owns one mutable list (ObservableCollection) of
       ProfileRow objects; the grid binds to it directly.
    4. Scan / Place / Save Report read the live profiles off the rows
       and dispatch through qa_engine and reporting (no global options
       dict crosses the boundary).

Cells that do not apply to a row's category (e.g. Width on Pipes) are
visible in the grid for cross-row alignment but rendered disabled +
soft-grey via per-cell DataTriggers in ui.xaml. The Supports{X}
properties on ProfileRow drive that gating.
"""

import os

from Autodesk.Revit.DB import Element, Transaction
from System.Collections.ObjectModel import ObservableCollection
from System.ComponentModel import (
    INotifyPropertyChanged,
    PropertyChangedEventArgs,
)

from pyrevit import forms

from annotation_qa import (
    config_io,
    profiles as profile_module,
    qa_engine,
    reporting,
    rules,
    tagging_engine,
)
from bim_core import errors, log as log_module
from bim_core.core import discipline_config


XAML_FILE = os.path.join(os.path.dirname(__file__), "ui.xaml")


# ============================================================================
# TagSymbolOption - one ComboBox entry for a row's tag dropdown.
# ============================================================================

class TagSymbolOption(object):
    """Item in the per-row tag combo. Display is the visible label;
    symbol is the FamilySymbol (or None for the 'use Revit default'
    sentinel)."""

    def __init__(self, symbol, display):
        self.symbol = symbol
        self.Display = display

    @property
    def symbol_id(self):
        if self.symbol is None:
            return None
        try:
            return self.symbol.Id.IntegerValue
        except Exception:
            return None

    def __repr__(self):
        return "<TagSymbolOption {0}>".format(self.Display)


# ============================================================================
# _ChoiceOption - generic ComboBox entry for v6 enum-like fields.
# ============================================================================

class _ChoiceOption(object):
    """Pair of (raw value persisted to JSON, human-readable label).

    WPF ComboBoxes bind ItemsSource to the option list and SelectedItem
    to the picked option; ProfileRow setters extract .value back out so
    on-disk JSON stays the same set of lowercase tokens regardless of
    how the UI presents them.
    """

    def __init__(self, value, display):
        self.value = value
        self.Display = display

    def __repr__(self):
        return "<ChoiceOption {0}>".format(self.value)


# Placement mode dropdown. Order: adjacent first so the new default
# behaviour reads top-of-list.
_PLACEMENT_MODE_OPTIONS = (
    _ChoiceOption(profile_module.PLACEMENT_MODE_ADJACENT,   "Adjacent"),
    _ChoiceOption(profile_module.PLACEMENT_MODE_ON_ELEMENT, "On element"),
)

# Preferred-side dropdown. "Auto" first so users who don't care don't
# have to think about it; explicit cardinals follow in compass order.
_PLACEMENT_SIDE_OPTIONS = (
    _ChoiceOption(profile_module.PLACEMENT_SIDE_AUTO,  "Auto"),
    _ChoiceOption(profile_module.PLACEMENT_SIDE_ABOVE, "Above"),
    _ChoiceOption(profile_module.PLACEMENT_SIDE_RIGHT, "Right"),
    _ChoiceOption(profile_module.PLACEMENT_SIDE_BELOW, "Below"),
    _ChoiceOption(profile_module.PLACEMENT_SIDE_LEFT,  "Left"),
)


def _option_for(options, value, fallback_index=0):
    """Find the option in `options` whose .value matches `value`; fall
    back to options[fallback_index] when nothing matches (e.g. JSON
    carries a legacy value the registry no longer lists)."""
    for opt in options:
        if opt.value == value:
            return opt
    return options[fallback_index] if options else None


# ============================================================================
# ProfileRow - WPF-bindable wrapper around a TaggingProfile.
# ============================================================================

class ProfileRow(INotifyPropertyChanged):
    """DataGrid row backed by one TaggingProfile.

    Editable properties two-way bind to grid cells; setters mutate the
    profile and raise PropertyChanged so WPF re-reads the value.
    Capability flags (Supports{X}) drive per-cell DataTriggers that
    grey out cells whose underlying rule doesn't apply to the profile's
    category.
    """

    def __init__(self, profile, tag_symbol_options):
        self._profile = profile
        self._handlers = []
        self._tag_options = tag_symbol_options
        # Hold the selected option as a cached reference so WPF's
        # SelectedItem comparison always finds it in ItemsSource.
        self._selected_tag_option = self._initial_tag_option()

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

    # ---- Backing profile access --------------------------------------------

    @property
    def profile(self):
        return self._profile

    # ---- Identity / display ------------------------------------------------

    @property
    def DisciplineLabel(self):
        try:
            return discipline_config.get(self._profile.discipline_key).label
        except KeyError:
            return self._profile.discipline_key or ""

    @property
    def SubcategoryLabel(self):
        return self._profile.binding.label

    # ---- Always-editable common --------------------------------------------

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
    def AddLeader(self):
        # Adjacent placement forces a leader (engine reads
        # profile.effective_add_leader). Reflect that in the UI so the
        # checkbox doesn't show False while the placement actually has
        # a leader. The XAML pairs this with a GatedCell_AddLeader
        # style that greys the cell while adjacent so the user can't
        # untick it - and the underlying add_leader value is preserved
        # untouched for when they switch back to on_element.
        if self._profile.placement_mode == profile_module.PLACEMENT_MODE_ADJACENT:
            return True
        return self._profile.add_leader
    @AddLeader.setter
    def AddLeader(self, value):
        v = bool(value)
        if self._profile.add_leader != v:
            self._profile.add_leader = v
            self._notify("AddLeader")

    @property
    def SkipAlreadyTagged(self):
        return self._profile.skip_already_tagged
    @SkipAlreadyTagged.setter
    def SkipAlreadyTagged(self, value):
        v = bool(value)
        if self._profile.skip_already_tagged != v:
            self._profile.skip_already_tagged = v
            self._notify("SkipAlreadyTagged")

    # ---- Length filters ----------------------------------------------------

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

    # ---- Orientation -------------------------------------------------------

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

    # ---- Size dimensions ---------------------------------------------------

    @property
    def WidthMinText(self):
        return _format_optional(self._profile.size_filters.get("width_mm_min"))
    @WidthMinText.setter
    def WidthMinText(self, value):
        self._profile.size_filters["width_mm_min"] = _parse_optional(value)
        self._notify("WidthMinText")

    @property
    def WidthMaxText(self):
        return _format_optional(self._profile.size_filters.get("width_mm_max"))
    @WidthMaxText.setter
    def WidthMaxText(self, value):
        self._profile.size_filters["width_mm_max"] = _parse_optional(value)
        self._notify("WidthMaxText")

    @property
    def HeightMinText(self):
        return _format_optional(self._profile.size_filters.get("height_mm_min"))
    @HeightMinText.setter
    def HeightMinText(self, value):
        self._profile.size_filters["height_mm_min"] = _parse_optional(value)
        self._notify("HeightMinText")

    @property
    def HeightMaxText(self):
        return _format_optional(self._profile.size_filters.get("height_mm_max"))
    @HeightMaxText.setter
    def HeightMaxText(self, value):
        self._profile.size_filters["height_mm_max"] = _parse_optional(value)
        self._notify("HeightMaxText")

    @property
    def DiameterMinText(self):
        return _format_optional(self._profile.size_filters.get("diameter_mm_min"))
    @DiameterMinText.setter
    def DiameterMinText(self, value):
        self._profile.size_filters["diameter_mm_min"] = _parse_optional(value)
        self._notify("DiameterMinText")

    @property
    def DiameterMaxText(self):
        return _format_optional(self._profile.size_filters.get("diameter_mm_max"))
    @DiameterMaxText.setter
    def DiameterMaxText(self, value):
        self._profile.size_filters["diameter_mm_max"] = _parse_optional(value)
        self._notify("DiameterMaxText")

    # ---- Tag family --------------------------------------------------------

    @property
    def TagSymbolOptions(self):
        return self._tag_options

    @property
    def SelectedTagSymbolOption(self):
        return self._selected_tag_option
    @SelectedTagSymbolOption.setter
    def SelectedTagSymbolOption(self, value):
        self._selected_tag_option = value
        self._profile.tag_symbol_id = (
            None if value is None else value.symbol_id)
        self._notify("SelectedTagSymbolOption")

    def _initial_tag_option(self):
        if not self._tag_options:
            return None
        target_id = self._profile.tag_symbol_id
        if target_id is None:
            return self._tag_options[0]
        for opt in self._tag_options:
            if opt.symbol_id == target_id:
                return opt
        return self._tag_options[0]

    # ---- Placement (v6) ---------------------------------------------------

    @property
    def PlacementModeOptions(self):
        return _PLACEMENT_MODE_OPTIONS

    @property
    def SelectedPlacementOption(self):
        return _option_for(_PLACEMENT_MODE_OPTIONS, self._profile.placement_mode)
    @SelectedPlacementOption.setter
    def SelectedPlacementOption(self, value):
        if value is None:
            return
        new_mode = value.value
        if new_mode == self._profile.placement_mode:
            return
        self._profile.placement_mode = new_mode
        # Drive every dependent cell in one shot:
        #   IsAdjacent re-evaluates the gating DataTriggers on the
        #     offset / side / Lead cells.
        #   AddLeader re-renders the checkbox because effective_add_leader
        #     flips with the mode.
        self._notify("SelectedPlacementOption")
        self._notify("IsAdjacent")
        self._notify("AddLeader")

    @property
    def OffsetMmText(self):
        return _format_optional(self._profile.offset_mm)
    @OffsetMmText.setter
    def OffsetMmText(self, value):
        v = _parse_optional(value)
        # offset_mm is a hard-required field (no None semantics in the
        # engine), so a blank cell snaps back to DEFAULT_OFFSET_MM
        # rather than persisting None and breaking the strategies.
        self._profile.offset_mm = (
            v if v is not None else profile_module.DEFAULT_OFFSET_MM)
        self._notify("OffsetMmText")

    @property
    def PreferredSideOptions(self):
        return _PLACEMENT_SIDE_OPTIONS

    @property
    def SelectedPreferredSideOption(self):
        return _option_for(_PLACEMENT_SIDE_OPTIONS, self._profile.preferred_side)
    @SelectedPreferredSideOption.setter
    def SelectedPreferredSideOption(self, value):
        if value is None:
            return
        new_side = value.value
        if new_side == self._profile.preferred_side:
            return
        self._profile.preferred_side = new_side
        self._notify("SelectedPreferredSideOption")

    @property
    def IsAdjacent(self):
        """Drives DataTriggers on offset / side / leader cells."""
        return self._profile.placement_mode == profile_module.PLACEMENT_MODE_ADJACENT

    # ---- Capability flags (cell gating) -----------------------------------

    @property
    def SupportsMinLength(self):
        return self._profile.supports("min_length")
    @property
    def SupportsMaxLength(self):
        return self._profile.supports("max_length")
    @property
    def SupportsHorizontal(self):
        return self._profile.supports("horizontal_only")
    @property
    def SupportsVertical(self):
        return self._profile.supports("vertical_only")
    @property
    def SupportsOrientationTol(self):
        return (self._profile.supports("horizontal_only")
                or self._profile.supports("vertical_only"))
    @property
    def SupportsWidth(self):
        return "width" in self._profile.cfg.size_dimensions
    @property
    def SupportsHeight(self):
        return "height" in self._profile.cfg.size_dimensions
    @property
    def SupportsDiameter(self):
        return "diameter" in self._profile.cfg.size_dimensions


# ============================================================================
# AnnotationQAWindow
# ============================================================================

class AnnotationQAWindow(forms.WPFWindow):

    def __init__(self, doc, view):
        forms.WPFWindow.__init__(self, XAML_FILE)
        self.doc = doc
        self.view = view
        self._logger = log_module.get_logger(doc, tool_name="auto_tag")
        # Load scan_options + starting profiles from disk - project
        # config wins, then extension default, then in-code defaults.
        # config_io.load_for_doc never raises; on any failure it
        # falls through to the in-code defaults so the dialog always
        # opens in a usable state.
        self.scan_options, self._initial_profiles = config_io.load_for_doc(
            doc, logger=self._logger)
        # rows mirrors the DataGrid; surviving the lifetime of the
        # dialog. Settings preserved per profile.key in _row_cache so
        # un-ticking and re-ticking a binding restores the same row.
        self.rows = ObservableCollection[object]()
        self._row_cache = {}
        self._tag_options_cache = {}
        self.records = []
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
        self.whole_model_chk.IsChecked = bool(
            self.scan_options.get("whole_model"))
        self._render_results("(not scanned yet)")

    # ====================================================================
    # Initial population
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

    def _select_default_bindings(self):
        """Tick the bindings the loaded profiles target.

        self._initial_profiles is whatever config_io.load_for_doc
        returned - project config if present, extension default
        otherwise, in-code default as last resort. Bindings outside
        the currently-shown discipline don't get ticked here, but
        their ProfileRows are still seeded into _row_cache so a later
        discipline switch + re-tick restores their persisted values
        verbatim.
        """
        starting = self._initial_profiles

        # Seed row cache for ALL loaded profiles regardless of
        # discipline. Cross-discipline persistence relies on this.
        for p in starting:
            if p.key not in self._row_cache:
                self._row_cache[p.key] = ProfileRow(
                    p, self._tag_options_for(p.category_key))

        target_keys = {p.binding.key for p in starting
                       if p.discipline_key == self._current_discipline_key()}
        if not target_keys:
            if self._current_bindings():
                self.subcategory_list.SelectedIndex = 0
            return

        for binding in self._current_bindings():
            if binding.key in target_keys:
                self.subcategory_list.SelectedItems.Add(binding.label)

    # ====================================================================
    # Subcategory ListBox
    # ====================================================================

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
        disc = self._current_discipline()
        return list(disc.subcategories) if disc is not None else []

    def _selected_bindings(self):
        if not self._current_bindings():
            return []
        labels = set()
        try:
            for item in self.subcategory_list.SelectedItems:
                labels.add(item)
        except Exception:
            return []
        return [b for b in self._current_bindings() if b.label in labels]

    # ====================================================================
    # Row sync
    # ====================================================================

    def _sync_rows_to_selection(self):
        """Reconcile self.rows with the current discipline + ticked
        subcategories. Rows preserved across selection wobble via
        self._row_cache."""
        disc_key = self._current_discipline_key()
        if disc_key is None:
            self.rows.Clear()
            return

        wanted_bindings = self._selected_bindings()
        wanted_keys = []
        for b in wanted_bindings:
            wanted_keys.append("{0}/{1}".format(disc_key, b.key))

        # Remove rows that are no longer wanted (but keep in cache).
        i = self.rows.Count - 1
        while i >= 0:
            row = self.rows[i]
            if row.profile.key not in wanted_keys:
                self.rows.RemoveAt(i)
            i -= 1

        # Preserve order from the discipline registry: walk wanted in
        # order and ensure each present.
        present_keys = {self.rows[i].profile.key
                        for i in range(self.rows.Count)}
        for binding in wanted_bindings:
            key = "{0}/{1}".format(disc_key, binding.key)
            if key in present_keys:
                continue
            row = self._row_cache.get(key)
            if row is None:
                profile = profile_module.default_profile_for(disc_key, binding)
                row = ProfileRow(
                    profile, self._tag_options_for(profile.category_key))
                self._row_cache[key] = row
            self.rows.Add(row)

    def _tag_options_for(self, category_key):
        """Build (and cache) the per-category list of tag combo entries.

        Always starts with a 'Use Revit default' sentinel so the user
        can opt out of explicit family selection without leaving the
        combo blank.
        """
        if category_key in self._tag_options_cache:
            return self._tag_options_cache[category_key]
        opts = [TagSymbolOption(None, "<use Revit default>")]
        try:
            symbols = tagging_engine.collect_tag_symbols(self.doc, category_key)
        except Exception:
            symbols = []
        for s in symbols:
            opts.append(TagSymbolOption(s, _tag_symbol_label(s)))
        self._tag_options_cache[category_key] = opts
        return opts

    # ====================================================================
    # Event handlers
    # ====================================================================

    def discipline_changed(self, sender, args):  # noqa: ARG002
        if self._suspend_handlers:
            return
        # Guard the listbox mutations so subcategories_changed doesn't
        # fire mid-edit and call _sync_rows_to_selection prematurely.
        self._suspend_handlers = True
        try:
            self._populate_subcategories()
            # No bindings ticked in the new discipline yet. Default to
            # the first so the grid never goes empty after a switch.
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

    def scope_changed(self, sender, args):  # noqa: ARG002
        if self._suspend_handlers:
            return
        new_value = bool(self.whole_model_chk.IsChecked)
        if new_value == self.scan_options.get("whole_model") and not self.records:
            return
        self.scan_options["whole_model"] = new_value
        self._invalidate_scan_if_any("scope changed")

    def grid_cell_edited(self, sender, args):  # noqa: ARG002
        # Any cell change invalidates a prior scan; cheaper than
        # tracking which fields actually matter to the rule pipeline.
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

        whole_model = bool(self.scan_options.get("whole_model"))
        scope_label = "whole model" if whole_model else "active view"
        try:
            with forms.ProgressBar(
                    title="Auto Tag - scanning " + scope_label + "...",
                    cancellable=True) as pb:
                def _progress(processed, total):
                    if pb.cancelled:
                        return False
                    pb.update_progress(processed, total)
                    return True
                self.records = qa_engine.scan(
                    self.doc, self.view, profiles,
                    whole_model=whole_model,
                    progress=_progress)
        except Exception as exc:
            errors.show_error("auto_tag",
                              "Couldn't scan the model for tag candidates.",
                              exc=exc, logger=self._logger)
            return

        if self.records is None:
            # scan() returns None when the user clicked Cancel on the
            # progress bar. Clear any prior records (the run is partial
            # and not safe to act on) and let the user start over.
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
            forms.alert("Nothing eligible to tag.", exitscript=False)
            return

        confirm = forms.alert(
            "Place {0} tag(s) in '{1}'?".format(pending, self.view.Name),
            ok=False, yes=True, no=True)
        if not confirm:
            return

        profiles = self._current_profiles()
        try:
            qa_engine.place_tags(
                self.doc, self.view, self.records, profiles,
                scan_options=self.scan_options)
        except Exception as exc:
            errors.show_error("auto_tag",
                              "Couldn't place tags in the active view.",
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
            errors.show_error("auto_tag",
                              "Couldn't write the HTML report.",
                              exc=exc, logger=self._logger)
            return
        try:
            os.startfile(path)
        except Exception:
            forms.alert("Report written to:\n{0}".format(path),
                        exitscript=False)

    def csv_clicked(self, sender, args):  # noqa: ARG002
        """Export per-element rows to CSV (UTF-8 BOM); Excel opens it
        natively. One row per scanned element with profile, discipline,
        subcategory, length, system, eligibility, and placement columns
        - the right shape for pivot / filter analysis."""
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
            errors.show_error("auto_tag",
                              "Couldn't write the CSV report.",
                              exc=exc, logger=self._logger)
            return
        try:
            os.startfile(path)
        except Exception:
            forms.alert("CSV written to:\n{0}".format(path),
                        exitscript=False)

    def delete_existing_clicked(self, sender, args):  # noqa: ARG002
        """Wipe every existing tag in the ticked categories.

        Honours the same active-view / whole-model scope toggle the
        scanner uses, so what the user sees ticked + scoped is what
        gets cleaned up. The whole deletion runs in a single
        Transaction so Ctrl+Z undoes the lot, and an exception
        anywhere in the loop rolls back automatically rather than
        leaving the model half-stripped.
        """
        profiles = self._current_profiles()
        enabled = [p for p in profiles if p.enabled]
        if not enabled:
            forms.alert("Tick at least one subcategory first.",
                        exitscript=False)
            return

        # De-duplicate while preserving first-seen order so the confirm
        # message lists categories in the same sequence the grid shows.
        category_keys = []
        category_labels = []
        for p in enabled:
            if p.category_key in category_keys:
                continue
            category_keys.append(p.category_key)
            try:
                category_labels.append(p.cfg.label)
            except Exception:
                category_labels.append(p.category_key)

        whole_model = bool(self.scan_options.get("whole_model"))
        scope_text = ("the entire model" if whole_model
                      else "the active view ('{0}')".format(self.view.Name))

        msg = ("Delete every existing tag for these categories "
               "in {0}?\n\nCategories: {1}\n\n"
               "Ctrl+Z will undo it if needed.").format(
                   scope_text, ", ".join(category_labels))

        confirm = forms.alert(msg, ok=False, yes=True, no=True)
        if not confirm:
            return

        t = Transaction(self.doc, "Auto Tag: Delete Existing Tags")
        t.Start()
        try:
            deleted = tagging_engine.delete_existing_tags(
                self.doc, self.view, category_keys, whole_model=whole_model)
            t.Commit()
        except Exception as exc:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            errors.show_error("auto_tag",
                              "Couldn't delete existing tags.",
                              exc=exc, logger=self._logger)
            return

        self._logger.info(
            "Deleted %d existing tag(s). scope=%s categories=%s",
            deleted, "whole_model" if whole_model else "active_view",
            category_keys)

        # A scan run from before the delete is now stale - the records
        # still reference the just-deleted tags' targets as
        # 'already_tagged' / 'placed'. Invalidate so the user re-scans.
        self._invalidate_scan_if_any("existing tags deleted")

        forms.alert(
            "Deleted {0} existing tag{1}.".format(
                deleted, "" if deleted == 1 else "s"),
            exitscript=False)

    def close_clicked(self, sender, args):  # noqa: ARG002
        # Persist the current grid state to the project's auto_tag.json
        # so the next launch (and the rest of the team via the shared
        # project config) sees the same scan options, tag pickers,
        # placement modes, filters etc. Best-effort: any failure is
        # logged inside config_io and never blocks the close.
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
        """Snapshot the live profiles from the grid rows in display
        order (which is discipline-registry order)."""
        return [self.rows[i].profile for i in range(self.rows.Count)]

    def _validate_or_alert(self, profiles):
        errors, blocking = profile_module.validate_profiles(profiles)
        if not blocking:
            return True
        # Surface the most important blocking error first - the
        # "no enabled profile" sentinel takes priority, then the first
        # per-profile error.
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
        whole = bool(self.scan_options.get("whole_model"))
        counts = reporting.summary_counts(self.records)
        lines = [
            "View:               {0}".format(self.view.Name),
            "Scope:              {0}".format(
                "Whole model" if whole else "Active view"),
            "Profiles:           {0}".format(
                ", ".join(p.key for p in profiles if p.enabled) or "(none)"),
            "Total scanned:      {0}".format(counts["total"]),
            "Already tagged:     {0}".format(counts["already"]),
        ]
        if whole:
            lines.append(
                "Audit-eligible:     {0}".format(counts["audit_eligible"]))
            lines.append(
                "Eligible (here):    {0}".format(counts["eligible"]))
            lines.append(
                "Eligible elsewhere: {0}".format(counts["eligible_elsewhere"]))
        else:
            lines.append("Eligible:           {0}".format(counts["eligible"]))
        lines.append("Placed:             {0}".format(counts["placed"]))
        lines.append("Failed:             {0}".format(counts["failed"]))

        # Per-profile breakdown.
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
        # Profiles that ran but matched nothing (or were disabled).
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
            elif r.get("audit_eligible") and not r.get("in_active_view", True):
                status = "ELSEWHERE (not in active view)"
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
    """Format an optional mm value for a TextBox; None -> empty string."""
    if value is None:
        return ""
    try:
        return "{0:.0f}".format(float(value))
    except (TypeError, ValueError):
        return ""


def _parse_optional(text):
    """Parse a TextBox value into float-or-None. Blanks -> None."""
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _safe_element_name(elem):
    """Read Element.Name as a string under IronPython.

    Why: Revit's Element.Name property is shadowed by subclass-level
    Name members (Family.Name, FamilySymbol.Name). IronPython resolves
    `elem.Name` through the type descriptor and can return the property
    object itself instead of the value. Going through
    Element.Name.__get__ forces the get and always returns the string.
    """
    if elem is None:
        return ""
    try:
        v = Element.Name.__get__(elem)
        if v is not None:
            return v
    except Exception:
        pass
    try:
        return elem.Name or ""
    except Exception:
        return ""


def _tag_symbol_label(symbol):
    """Render a FamilySymbol as 'Family : Type' for the tag combo."""
    fam = ""
    try:
        family = symbol.Family
        if family is not None:
            fam = _safe_element_name(family)
    except Exception:
        pass
    typ = _safe_element_name(symbol)
    if fam and typ:
        return "{0} : {1}".format(fam, typ)
    if typ:
        return typ
    if fam:
        return fam
    return "<unnamed tag>"
