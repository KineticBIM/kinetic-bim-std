# -*- coding: utf-8 -*-
"""Refresh-only - pre-flight federated model check.

Opens the project's federated NWF in Navisworks, refreshes every
linked NWC/NWD reference, and logs the result. Doesn't run clashes
or produce reports - just confirms the federated model is healthy
before the full coordination run.

Path resolution:
  1. Active Revit project's coordination profile (best case).
  2. Most-recently used coordination output folder.
  3. Prompt the user for NWF + output folder.

Shift-click: force the prompt path even when a profile is available
(useful for one-off refreshes of an alternative NWF).
"""

__title__   = "Refresh\nModels"
__author__  = "Kinetic BIM"
__doc__     = "Refresh the federated NWF's linked references."

import os
from pyrevit import revit, script, forms

from clash_coordination import project_config, quick_actions


def _resolve_paths(doc, force_prompt=False):
    """Return (nwf_path, output_root, profile)."""
    profile, source = project_config.load_profile(doc=doc)
    nwf = (profile or {}).get("nwf_path")
    output_root = (profile or {}).get("output_root")

    if force_prompt or not nwf or not os.path.isfile(nwf):
        picked = forms.pick_file(
            file_ext="nwf",
            files_filter="Navisworks (*.nwf;*.nwd)|*.nwf;*.nwd|All files (*.*)|*.*",
            title="Pick the federated NWF/NWD to refresh",
        )
        if not picked:
            return None, None, profile
        nwf = picked

    if force_prompt or not output_root or not os.path.isdir(output_root):
        picked = forms.pick_folder(
            title="Pick the coordination output root for logs")
        if not picked:
            return None, None, profile
        output_root = picked

    return nwf, output_root, profile


def main():
    doc = revit.doc
    output = script.get_output()

    nwf, output_root, profile = _resolve_paths(
        doc, force_prompt=bool(__shiftclick__))  # noqa: F821
    if not nwf or not output_root:
        output.print_md("Cancelled - no NWF / output folder.")
        return

    output.print_md("# Refreshing federated model")
    output.print_md("- NWF: `{0}`".format(nwf))
    output.print_md("- Logs into: `{0}`".format(output_root))
    output.print_md("---")

    fail_on_missing = bool(
        (profile or {}).get("options", {}).get("fail_on_missing_models", False))

    def _progress(label, fraction):
        output.print_md("- {0} ({1:.0f}%)".format(label, fraction * 100))

    try:
        result = quick_actions.refresh_only(
            nwf, output_root,
            fail_on_missing=fail_on_missing,
            progress=_progress,
        )
    except FileNotFoundError as e:
        output.print_md("**FAILED:** {0}".format(e))
        return
    except Exception as e:
        output.print_md("**FAILED:** {0}".format(e))
        return

    output.print_md("---")
    if result.failed:
        output.print_md("## Refresh failed")
        if result.error:
            output.print_md("`{0}`".format(result.error))
        if result.log_path:
            output.print_md("Log: `{0}`".format(result.log_path))
        return

    rr = result.refresh_report
    if rr is None:
        output.print_md("No refresh report produced.")
        return

    output.print_md("## Refresh complete")
    output.print_md(
        "- {0} refreshed".format(len(rr.refreshed)))
    output.print_md(
        "- {0} missing".format(len(rr.missing)))
    output.print_md(
        "- {0} failed".format(len(rr.failed)))
    if rr.missing:
        output.print_md("### Missing link files")
        for p in rr.missing:
            output.print_md("- `{0}`".format(p))
    if rr.failed:
        output.print_md("### Failed operations")
        for p, msg in rr.failed:
            output.print_md("- `{0}` - {1}".format(p, msg))
    if result.log_path:
        output.print_md("---")
        output.print_md("Log file: `{0}`".format(result.log_path))

    # Record this run folder so Open Output / Clash Reporting know
    # where the last action happened.
    if result.run_folder:
        project_config.record_run(doc, output_root, result.run_folder)


main()
