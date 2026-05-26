# -*- coding: utf-8 -*-
"""clash_coordination - Level 1 Navisworks clash reporting automation.

What this engine does
---------------------
Automates the *administrative* half of a weekly Navisworks coordination
run: refresh the federated model, run the saved clash tests, export
the results, render Excel + PDF reports, save the viewpoints and
screenshots, and drop the lot into a dated coordination folder ready
to send to the wider team.

What it deliberately does NOT do
--------------------------------
- It does not replace Navisworks clash detection. The clash tests
  themselves stay in the NWF, authored by the coordinator.
- It does not invent clash rules, classify clashes with AI, or resolve
  anything automatically.
- It does not talk to ACC, BIM 360 issues, or any cloud platform
  in V1. The history/ subpackage prepares for that integration but
  is inert until a later release.

Layout
------
    configs/             default + per-project profile JSONs.
    projects/            committed coordination-project profiles.
    data/                ClashResult / ClashTest / ClashRun dataclasses
                         (plain Python, no Navisworks dependency).
    navisworks/          pywin32 COM wrappers - the only modules in
                         this package that require Navisworks running.
    parsing/             ClashDetective + viewpoints XML -> dataclasses.
                         Pure Python, unit-tested against fixtures.
    model_refresh/       Drive NW refresh, validate link paths.
    reporting/           openpyxl Excel detail + reportlab PDF summary.
    output/              Dated coordination folder layout.
    logging/             Coordination-aware logger (writes into the
                         output folder, not the Revit project folder).
    history/             Weekly snapshot writer prep for trend/SQLite
                         integration (deliberately a stub in V1).
    project_config.py    Coordination profile load/save.
    orchestrator.py      Top-level weekly-run workflow.
    ui.py / ui.xaml      WPF coordination window.

Entry point: pushbutton script.py imports `ui` and calls
`ui.show_window(revit_doc)`. The user picks a coordination project
profile (or NWF + output folder ad hoc), ticks the weekly-run options,
hits Run, and the orchestrator does the rest.
"""
