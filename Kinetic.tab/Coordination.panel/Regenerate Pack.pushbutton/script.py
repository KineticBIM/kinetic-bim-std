# -*- coding: utf-8 -*-
"""Regenerate coordination pack from an existing ClashDetective XML.

Skips Navisworks entirely. The user picks the source XML (and
optionally an output root override if the project profile doesn't
have one), and the tool produces a fresh dated coordination folder
with Excel, PDF, and weekly snapshot regenerated from the XML.

Useful when:
  - The previous run finished the clash export but failed during
    reporting and you want to recover without re-running clashes.
  - You changed the coordination profile (e.g. discipline keywords,
    naming, screenshot cap) and want to re-render an old run.
  - You have a NW-generated XML from another machine.

Shift-click: prompt for output root even when the profile has one.
"""

__title__   = "Regenerate\nPack"
__author__  = "Kinetic BIM"
__doc__     = "Regenerate Excel + PDF + snapshot from an existing clash XML."

import os
from pyrevit import revit, script, forms

from clash_coordination import project_config, quick_actions


def main():
    doc = revit.doc
    output = script.get_output()

    # 1) Pick the XML - always prompt, no auto-resolve.
    xml_path = forms.pick_file(
        file_ext="xml",
        files_filter="Clash report XML (*.xml)|*.xml|All files (*.*)|*.*",
        title="Pick the ClashDetective XML to regenerate from",
    )
    if not xml_path:
        output.print_md("Cancelled.")
        return

    # 2) Resolve output root from profile (with shift-click override).
    profile, _ = project_config.load_profile(doc=doc)
    output_root = (profile or {}).get("output_root")
    if __shiftclick__ or not output_root or not os.path.isdir(output_root):  # noqa: F821
        picked = forms.pick_folder(
            title="Pick the coordination output root to write into")
        if not picked:
            output.print_md("Cancelled - no output root.")
            return
        output_root = picked

    options = quick_actions.build_regenerate_options_from_profile(
        profile or {}, xml_path=xml_path, output_root=output_root,
    )

    output.print_md("# Regenerating coordination pack")
    output.print_md("- Source XML: `{0}`".format(xml_path))
    output.print_md("- Output root: `{0}`".format(output_root))
    output.print_md("---")

    def _progress(label, fraction):
        output.print_md("- {0} ({1:.0f}%)".format(label, fraction * 100))

    try:
        run, artifacts = quick_actions.regenerate_from_existing_xml(
            options, progress=_progress)
    except FileNotFoundError as e:
        output.print_md("**FAILED:** {0}".format(e))
        return
    except Exception as e:
        output.print_md("**FAILED:** {0}".format(e))
        return

    output.print_md("---")
    output.print_md("## Done")
    output.print_md(
        "- {0} clashes across {1} tests".format(run.total, len(run.tests)))
    output.print_md(
        "- Excel: `{0}`".format(artifacts.excel_path or "(skipped)"))
    output.print_md(
        "- PDF:   `{0}`".format(artifacts.pdf_path or "(skipped)"))
    output.print_md(
        "- Snapshot: `{0}`".format(artifacts.snapshot_path or "(skipped)"))
    output.print_md(
        "- Log: `{0}`".format(artifacts.log_path or ""))

    if artifacts.run_folder:
        project_config.record_run(doc, output_root, artifacts.run_folder)


main()
