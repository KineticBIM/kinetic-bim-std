# -*- coding: utf-8 -*-
"""Navisworks COM wrappers (pywin32).

This is the ONLY subpackage in clash_coordination that requires
Navisworks to be installed and accessible via COM. Everything that
talks to Navisworks lives here; parsing of the exported XML happens
in `parsing/` so that side of the system is unit-testable without
Navisworks.

The COM ProgID is `Navisworks.Application.x` (where x is the major
version, e.g. `Navisworks.Application.20` for Navisworks 2023+).
connection.dispatch() probes the available versions and binds to
the newest one installed.

Integration test plan (manual, run on a machine with NW installed):
  1. Open a known NWF with at least one clash test.
  2. Call document.open_federated(path), assert no exception.
  3. Call document.refresh_links(), assert returned status report
     lists the expected NWC files.
  4. Call clash_tests.list_tests(), assert the saved test names
     come back.
  5. Call clash_tests.run_tests(...), assert the ClashDetective
     XML lands on disk and contains <clashtest> elements.
  6. Call viewpoints.export_viewpoints(...) and screenshots
     .capture_clash_screenshots(...), assert files land.
"""
