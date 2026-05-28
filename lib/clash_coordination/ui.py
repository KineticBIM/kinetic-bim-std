# -*- coding: utf-8 -*-
"""WPF coordination window.

Layout (matches ui.xaml):

    Header
    Project profile picker  [combo]  [Reload]
    Federated NWF           [path]   [Browse...]
    Output folder           [path]   [Browse...]
    +--- Clash tests ---+   +--- Weekly run options ---+
    | (grouped tree)    |   | (checkboxes)              |
    +-------------------+   +---------------------------+
    Status + progress bar
    [Open output folder]    [Save profile override] [Close] [Run]

Threading
---------
The orchestrator's `run_coordination(...)` is synchronous and CPU-
heavy. We run it on a worker thread and dispatch progress callbacks
back onto the UI thread via Dispatcher.Invoke so the WPF controls
update safely.

IronPython 2.7 / CPython 3 compatible. WPF/.NET imports below assume
the script is running inside Revit via pyRevit; the module is not
importable outside that host.
"""

from __future__ import print_function, division, absolute_import

import io
import json
import os
import threading
import traceback

import clr  # type: ignore
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
clr.AddReference("System.Windows.Forms")

from System import Action  # type: ignore
from System.ComponentModel import (   # type: ignore
    INotifyPropertyChanged, PropertyChangedEventArgs,
)
from System.Windows import (   # type: ignore
    MessageBox, MessageBoxButton, MessageBoxImage,
)

from pyrevit import forms

from bim_core import errors
from clash_coordination import orchestrator, project_config
from clash_coordination.output import folder_layout


TOOL_NAME = "clash_reporting"


XAML_FILE = os.path.join(os.path.dirname(__file__), "ui.xaml")


# ---------------------------------------------------------------------------
# Bindable test / group rows
# ---------------------------------------------------------------------------

class TestRow(INotifyPropertyChanged):
    """Bindable row in the test list. WPF DataTemplate binds to
    .Name and .IsSelected (two-way)."""

    def __init__(self, name, is_selected=False):
        self._name = name
        self._is_selected = is_selected
        self._handlers = []

    # INotifyPropertyChanged ----------------------------------------------
    def add_PropertyChanged(self, handler):
        self._handlers.append(handler)

    def remove_PropertyChanged(self, handler):
        if handler in self._handlers:
            self._handlers.remove(handler)

    def _raise(self, prop):
        args = PropertyChangedEventArgs(prop)
        for h in list(self._handlers):
            try:
                h(self, args)
            except Exception:
                pass

    # WPF-visible properties ----------------------------------------------
    @property
    def Name(self):
        return self._name

    @Name.setter
    def Name(self, v):
        self._name = v
        self._raise("Name")

    @property
    def IsSelected(self):
        return self._is_selected

    @IsSelected.setter
    def IsSelected(self, v):
        self._is_selected = bool(v)
        self._raise("IsSelected")


class TestGroup(object):
    """Group header + its tests. Plain object; the inner ItemsControl
    binds to .Tests (the rows are bindable)."""

    def __init__(self, name, tests):
        self.Name = name
        self.Tests = tests

    @property
    def selected_test_names(self):
        return [t.Name for t in self.Tests if t.IsSelected]


# ---------------------------------------------------------------------------
# Profile combo entry
# ---------------------------------------------------------------------------

class ProfileEntry(object):
    """Entry in the project profile dropdown."""

    def __init__(self, display, source_path):
        self.Display = display
        self.source_path = source_path


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------

class CoordinationWindow(forms.WPFWindow):
    """Main coordination window."""

    def __init__(self, revit_doc=None, output=None):
        forms.WPFWindow.__init__(self, XAML_FILE)
        self._doc = revit_doc
        self._output = output
        self._profile = {}
        self._profile_source = None
        self._test_groups = []
        self._running = False

        self._load_profiles_into_combo()
        self._apply_default_paths_from_doc()

    # ---- Profile / project lifecycle ------------------------------------

    def _load_profiles_into_combo(self):
        entries = [ProfileEntry("(Default platform profile)", None)]
        for proj_num, path in project_config.list_committed_projects():
            name = ""
            try:
                with io.open(path, "r", encoding="utf-8") as fh:
                    obj = json.loads(fh.read())
                name = obj.get("project_name") or ""
            except Exception:
                name = ""
            label = "{0} - {1}".format(proj_num, name) if name else proj_num
            entries.append(ProfileEntry(label, path))
        self.ProfileComboBox.ItemsSource = entries

        # Pre-select the project whose number matches the current Revit doc.
        if self._doc is not None:
            doc_num = project_config._project_number_from_doc(self._doc)
            if doc_num:
                for i, entry in enumerate(entries):
                    if entry.source_path and doc_num in os.path.basename(entry.source_path):
                        self.ProfileComboBox.SelectedIndex = i
                        return
        if entries:
            self.ProfileComboBox.SelectedIndex = 0

    def _apply_default_paths_from_doc(self):
        if not self.NwfPathBox.Text and self._profile.get("nwf_path"):
            self.NwfPathBox.Text = self._profile["nwf_path"]
        if not self.OutputRootBox.Text and self._profile.get("output_root"):
            self.OutputRootBox.Text = self._profile["output_root"]

    def _load_profile(self, source_path):
        if source_path is None:
            self._profile, self._profile_source = project_config.load_profile(
                doc=self._doc)
        else:
            try:
                with io.open(source_path, "r", encoding="utf-8") as fh:
                    overlay = json.loads(fh.read())
            except Exception as e:
                errors.show_error_modal(
                    TOOL_NAME,
                    "Couldn't load profile:\n{0}".format(source_path),
                    exc=e)
                self._profile, self._profile_source = project_config.load_profile(
                    doc=self._doc)
                return
            default_profile, _ = project_config.load_profile(doc=self._doc)
            self._profile = project_config._deep_merge(default_profile, overlay)
            self._profile_source = source_path

        self.NwfPathBox.Text = self._profile.get("nwf_path") or ""
        self.OutputRootBox.Text = self._profile.get("output_root") or ""
        self._populate_test_groups()
        self._apply_options_from_profile()

    def _populate_test_groups(self):
        groups = []
        for grp in self._profile.get("clash_test_groups") or []:
            test_rows = [TestRow(name, True) for name in grp.get("tests") or []]
            groups.append(TestGroup(grp.get("name") or "(unnamed group)", test_rows))
        self._test_groups = groups
        self.TestGroupsControl.ItemsSource = groups

    def _apply_options_from_profile(self):
        opts = self._profile.get("options") or {}
        self.OptRefresh.IsChecked     = bool(opts.get("refresh_models_before_run", True))
        self.OptExcel.IsChecked       = bool(opts.get("include_excel_report", True))
        self.OptPdf.IsChecked         = bool(opts.get("include_pdf_summary", True))
        self.OptViewpoints.IsChecked  = bool(opts.get("export_viewpoints", True))
        self.OptScreenshots.IsChecked = bool(opts.get("export_screenshots", True))
        self.OptSnapshot.IsChecked    = bool(opts.get("save_weekly_snapshot", True))
        self.OptFailOnMissing.IsChecked = bool(opts.get("fail_on_missing_models", False))

    # ---- Event handlers --------------------------------------------------

    def OnProfileChanged(self, sender, args):
        entry = self.ProfileComboBox.SelectedItem
        if entry is None:
            return
        self._load_profile(entry.source_path)

    def OnReloadProfilesClicked(self, sender, args):
        self._load_profiles_into_combo()

    def OnBrowseNwfClicked(self, sender, args):
        path = forms.pick_file(
            file_ext="nwf",
            files_filter="Navisworks (*.nwf;*.nwd)|*.nwf;*.nwd|All files (*.*)|*.*",
            multi_file=False,
            init_dir=self._initial_dir(self.NwfPathBox.Text),
            title="Pick the federated NWF/NWD",
        )
        if path:
            self.NwfPathBox.Text = path

    def OnBrowseOutputClicked(self, sender, args):
        path = forms.pick_folder(
            title="Pick the coordination output root",
            owner=self,
        )
        if path:
            self.OutputRootBox.Text = path

    def _initial_dir(self, hint):
        if hint and os.path.isfile(hint):
            return os.path.dirname(hint)
        if hint and os.path.isdir(hint):
            return hint
        return None

    def OnSelectAllTestsClicked(self, sender, args):
        for grp in self._test_groups:
            for t in grp.Tests:
                t.IsSelected = True

    def OnSelectNoTestsClicked(self, sender, args):
        for grp in self._test_groups:
            for t in grp.Tests:
                t.IsSelected = False

    def OnOpenOutputClicked(self, sender, args):
        target = (self.OutputRootBox.Text or "").strip()
        if target:
            latest = folder_layout.latest_run_folder(target) or target
        else:
            latest = project_config.last_output_folder(self._doc) or ""
        if latest and os.path.isdir(latest):
            os.startfile(latest)
        else:
            errors.show_warning_modal(
                TOOL_NAME,
                "No coordination output folder to open yet.")

    def OnSaveProfileClicked(self, sender, args):
        output_root = (self.OutputRootBox.Text or "").strip()
        if not output_root:
            errors.show_warning_modal(
                TOOL_NAME,
                "Set the Output folder before saving an override.")
            return
        updates = self._build_profile_updates_from_ui()
        try:
            path = project_config.write_project_override(output_root, updates)
            MessageBox.Show(
                "Saved override:\n{0}".format(path),
                "Save profile",
                MessageBoxButton.OK, MessageBoxImage.Information)
        except Exception as e:
            errors.show_error_modal(
                TOOL_NAME,
                "Couldn't save the project override.",
                exc=e)

    def OnCloseClicked(self, sender, args):
        if self._running:
            errors.show_warning_modal(
                TOOL_NAME,
                "A run is in progress - please wait for it to finish.")
            return
        self.Close()

    def OnRunClicked(self, sender, args):
        if self._running:
            return
        nwf = (self.NwfPathBox.Text or "").strip()
        out_root = (self.OutputRootBox.Text or "").strip()
        if not nwf or not os.path.isfile(nwf):
            errors.show_warning_modal(
                TOOL_NAME,
                "The federated NWF/NWD does not exist:\n{0}".format(nwf))
            return
        if not out_root:
            errors.show_warning_modal(
                TOOL_NAME,
                "Pick an output folder before running.")
            return

        selected_tests = []
        for grp in self._test_groups:
            selected_tests.extend(grp.selected_test_names)
        if not selected_tests:
            confirm = MessageBox.Show(
                "No clash tests are selected. Run anyway? (will run every "
                "test saved in the NWF)",
                "Run",
                MessageBoxButton.YesNo, MessageBoxImage.Question)
            if str(confirm) != "Yes":
                return

        options = orchestrator.build_options_from_profile(
            self._profile,
            nwf_path=nwf,
            output_root=out_root,
            selected_tests=selected_tests,
            option_overrides=self._build_option_overrides_from_ui(),
        )

        self._running = True
        self.RunButton.IsEnabled = False
        self._set_status("Starting...", 0.0)

        thread = threading.Thread(target=self._run_on_worker, args=(options,))
        thread.daemon = True
        thread.start()

    # ---- Worker --------------------------------------------------------

    def _run_on_worker(self, options):
        try:
            run, artifacts = orchestrator.run_coordination(
                options, progress=self._progress_callback)
            project_config.record_run(
                self._doc, options.output_root, artifacts.run_folder)
            self._on_run_complete(run, artifacts)
        except Exception as e:
            tb = traceback.format_exc()
            self._on_run_failed(e, tb)

    def _progress_callback(self, label, fraction):
        self.Dispatcher.Invoke(Action(lambda: self._set_status(label, fraction)))

    def _set_status(self, label, fraction):
        self.StatusText.Text = label or ""
        f = max(0.0, min(1.0, fraction))
        self.StatusPercent.Text = "{0:.0f}%".format(f * 100)
        self.ProgressBar.Value = f

    def _on_run_complete(self, run, artifacts):
        def show():
            self._running = False
            self.RunButton.IsEnabled = True
            self._set_status(
                "Done. {0} clashes across {1} tests.".format(
                    run.total, len(run.tests)), 1.0)
            details = [
                "Run folder:  {0}".format(artifacts.run_folder),
                "Excel:       {0}".format(artifacts.excel_path or "(skipped)"),
                "HTML:        {0}".format(artifacts.pdf_path or "(skipped)"),
                "Snapshot:    {0}".format(artifacts.snapshot_path or "(skipped)"),
                "Log:         {0}".format(artifacts.log_path or ""),
            ]
            MessageBox.Show(
                "\n".join(details),
                "Coordination run complete",
                MessageBoxButton.OK, MessageBoxImage.Information)
        self.Dispatcher.Invoke(Action(show))

    def _on_run_failed(self, exc, tb):
        def show():
            self._running = False
            self.RunButton.IsEnabled = True
            self._set_status("Failed: {0}".format(exc), 0.0)
            errors.show_error_modal(
                TOOL_NAME,
                "The coordination run failed.",
                exc=exc,
                tb=tb)
        self.Dispatcher.Invoke(Action(show))

    # ---- Profile-from-UI helpers ----------------------------------------

    def _build_option_overrides_from_ui(self):
        return {
            "refresh_models":        bool(self.OptRefresh.IsChecked),
            "run_clash_tests":       bool(self.OptRunTests.IsChecked),
            "export_excel":          bool(self.OptExcel.IsChecked),
            "export_pdf":            bool(self.OptPdf.IsChecked),
            "export_viewpoints":     bool(self.OptViewpoints.IsChecked),
            "export_screenshots":    bool(self.OptScreenshots.IsChecked),
            "save_snapshot":         bool(self.OptSnapshot.IsChecked),
            "include_pdf_screenshots": bool(self.OptPdfThumbs.IsChecked),
            "fail_on_missing":       bool(self.OptFailOnMissing.IsChecked),
        }

    def _build_profile_updates_from_ui(self):
        groups = []
        for grp in self._test_groups:
            groups.append({
                "name": grp.Name,
                "tests": [t.Name for t in grp.Tests],
            })
        return {
            "schema_version": project_config.PROFILE_SCHEMA_VERSION,
            "nwf_path": (self.NwfPathBox.Text or "").strip(),
            "output_root": (self.OutputRootBox.Text or "").strip(),
            "clash_test_groups": groups,
            "options": {
                "refresh_models_before_run": bool(self.OptRefresh.IsChecked),
                "include_excel_report":      bool(self.OptExcel.IsChecked),
                "include_pdf_summary":       bool(self.OptPdf.IsChecked),
                "export_viewpoints":         bool(self.OptViewpoints.IsChecked),
                "export_screenshots":        bool(self.OptScreenshots.IsChecked),
                "save_weekly_snapshot":      bool(self.OptSnapshot.IsChecked),
                "fail_on_missing_models":    bool(self.OptFailOnMissing.IsChecked),
            },
        }


# ---------------------------------------------------------------------------
# Public entry point - called by the pushbutton script
# ---------------------------------------------------------------------------

def show_window(revit_doc=None, output=None):
    """Open the coordination window. Blocks until the user closes it."""
    win = CoordinationWindow(revit_doc=revit_doc, output=output)
    win.ShowDialog()
