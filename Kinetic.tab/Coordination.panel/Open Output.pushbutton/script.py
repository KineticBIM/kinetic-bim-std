# -*- coding: utf-8 -*-
"""Open the most recent coordination output folder.

Precedence: explicit recent-run record -> active project's profile
output_root -> default profile. If nothing resolves, prompt for a
folder.

Shift-click: open the project's coordination ROOT (parent of the
dated folders), not the latest dated run inside it. Useful when you
want to navigate to last week's run or compare two weeks side by side.
"""

__title__   = "Open\nOutput"
__author__  = "Kinetic BIM"
__doc__     = "Open the most recent coordination output folder."

import os
from pyrevit import revit, script, forms

from clash_coordination import project_config, quick_actions
from clash_coordination.output import folder_layout


def main():
    doc = revit.doc
    output = script.get_output()

    profile, _ = project_config.load_profile(doc=doc)
    profile_root = profile.get("output_root") if profile else None

    if __shiftclick__:  # noqa: F821
        # Open the coordination root, not the latest dated subfolder.
        target = profile_root
        if not target or not os.path.isdir(target):
            recent = project_config.last_output_folder(doc)
            if recent:
                # Walk up to the dated-folder parent if the recent
                # record points at one.
                parent = os.path.dirname(recent)
                if os.path.isdir(parent):
                    target = parent
        if not target or not os.path.isdir(target):
            target = forms.pick_folder(
                title="Pick the coordination output root to open")
        if target and os.path.isdir(target):
            os.startfile(target)
        else:
            output.print_md("Nothing to open.")
        return

    # Normal click: open the most recent dated coordination folder.
    target = quick_actions.find_latest_output_folder(doc=doc)
    if not target or not os.path.isdir(target):
        # Last-ditch fallback - prompt.
        picked = forms.pick_folder(
            title="No coordination folder recorded yet. Pick one to open.")
        if not picked:
            output.print_md("Nothing to open.")
            return
        target = folder_layout.latest_run_folder(picked) or picked

    output.print_md("Opening: `{0}`".format(target))
    os.startfile(target)


main()
