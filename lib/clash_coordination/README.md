# clash_coordination

Level 1 Navisworks clash reporting automation for the Kinetic BIM
platform. Part of the `kinetic.extension` pyRevit ribbon under the
**Coordination** panel.

## What it does

Automates the *administrative* half of a weekly coordination run.
The clash tests themselves live in the NWF — coordinators author them
in Navisworks as usual. This tool drives the workflow around them:

1. Open the federated NWF / NWD.
2. Refresh linked NWC / NWD references.
3. Run the saved clash tests the coordinator selects.
4. Export ClashDetective XML, viewpoints XML, and viewpoint screenshots.
5. Parse those exports into a structured `ClashRun` object.
6. Render an Excel detail report + a PDF management summary.
7. Save a `weekly_snapshot.json` (history hook — feeds future trend
   tracking when SQLite / ACC integration arrives).
8. Drop everything into a dated coordination folder:

```
<output_root>/
  2026-05-14/
    Reports/
      ClashReport_2026-05-14.xlsx
      ClashSummary_2026-05-14.pdf
    Viewpoints/
      <NWV viewpoint exports>
    Screenshots/
      <clash PNG renders>
    Logs/
      coordination_2026-05-14_1430.log
    weekly_snapshot.json
```

## Not in V1

- Custom clash geometry engine (use Navisworks)
- Native Revit clash detection
- AI clash classification / auto-resolution
- ACC integration, cloud platform, real-time sync
- Dashboards (`history/` is structured for trend tracking but the
  trend-rendering UI itself is a later release)

## Architecture

```
clash_coordination/
├── data/                ClashResult / ClashTest / ClashRun classes
├── navisworks/          COM-bound (pywin32 or CLR) - only layer that needs NW
├── parsing/             XML -> classes (pure Python, unit-tested)
├── model_refresh/       Refresh + validate link paths
├── reporting/           Stdlib xlsx writer + HTML summary
├── output/              Dated folder layout
├── logging/             Coord-aware logger (writes to output folder)
├── history/             Weekly JSON snapshots (SQLite/ACC future)
├── configs/             default.json + per-project profiles
├── projects/            Committed coordination project profiles
├── project_config.py    Profile load / save
├── orchestrator.py      Top-level weekly-run workflow
├── ui.py / ui.xaml      WPF coordination window
└── README.md            (this file)
```

The **Navisworks-bound code is isolated** to `navisworks/`. Everything
else is plain Python that operates on XML / dataclasses / JSON and is
unit-tested in `tests/clash_coordination/` without any Navisworks or
Revit dependency. This follows the repo's existing
"separate Revit-bound from analysis" convention (see `CLAUDE.md`).

## Dependencies

**None at runtime.** The engine is deliberately stdlib-only so it
runs under pyRevit's default IronPython 2.7 engine without any
third-party install on team members' machines.

- Navisworks COM: accessed via either pywin32 (CPython) or
  IronPython's CLR interop - the connection layer probes both.
- Excel output: hand-rolled minimal xlsx writer (`reporting/xlsx_writer.py`),
  matching the existing `sheet_tools/excel_reader.py` pattern.
- "PDF" summary: actually an HTML report (matches the
  `audit_engine` HTML-report pattern). Opens in any browser,
  prints to PDF via Ctrl+P -> Save as PDF if a static PDF is
  needed.

## Configuration

Three-tier config lookup, matching `audit_engine`:

1. `<output_root>/coord_config.json` — per-coordination-project
   override, version controlled with the project files.
2. `lib/clash_coordination/projects/<project_number>.json` — committed
   coordination profile for a Revit project.
3. `lib/clash_coordination/configs/default.json` — platform default.

A coordination profile is a JSON document with:

```json
{
  "project_number": "23001",
  "project_name": "Example Hospital",
  "nwf_path": "C:/Projects/.../Coordination/Federated.nwf",
  "output_root": "C:/Projects/.../Coordination",
  "clash_test_groups": [
    {"name": "Mechanical vs Structure", "tests": ["MEC vs STR - Ducts", "MEC vs STR - Equipment"]},
    {"name": "Electrical vs Ceiling", "tests": ["ELE vs ARC - Cable Trays vs Ceiling"]}
  ],
  "disciplines": {
    "MEC": "Mechanical",
    "ELE": "Electrical",
    "HYD": "Hydraulic",
    "FIR": "Fire"
  },
  "options": {
    "screenshot_resolution": [1920, 1080],
    "export_viewpoints": true,
    "export_screenshots": true,
    "include_pdf_summary": true,
    "include_excel_report": true,
    "save_weekly_snapshot": true
  }
}
```

## Usage

The **Coordination** ribbon panel has four pushbuttons:

| Button | What it does | Shift-click |
|---|---|---|
| **Clash Reporting** | Opens the coordination window. Pick a project profile (or NWF + output folder ad hoc), tick the weekly-run options, hit Run. The full workflow: refresh -> run clashes -> export XML/viewpoints/screenshots -> render Excel detail report + HTML management summary -> save snapshot. | Opens the most recent coordination output folder instead of running. |
| **Refresh Models** | Pre-flight check. Opens the project's federated NWF in Navisworks, refreshes every linked NWC/NWD, logs the result. No clash run, no reports - just confirms the model is healthy before a full run. | Forces the file-picker prompt even when a profile path exists. |
| **Regenerate Pack** | Skips Navisworks entirely. Pick an existing ClashDetective XML and the tool re-renders Excel + HTML summary + snapshot from it. Use to recover from a partial run, or to re-render after a config change. | Forces an output-root prompt even when the profile has one. |
| **Open Output** | Opens the most recent coordination output folder. | Opens the project's coordination ROOT (parent of the dated folders) so you can navigate to previous weeks. |

## Testing

Plain-Python layers are unit-tested in `tests/clash_coordination/`.
The Navisworks COM layer is integration-tested manually on a machine
with Navisworks installed — see `navisworks/README.md` for the test
plan.
