# Auto Dimension - Rule-based MEP dimensioning (v1)

Standards-driven dimension automation for BIM documentation. Each
ticked subcategory becomes its own DimensioningProfile carrying its
own filters, measurement reference (where on the element the
dimension is taken from), reference target (what the dimension
measures to), dimension style, and offset distance. Architecturally
mirrors the Auto Tag tool; both share the discipline / category /
geometry / rule-engine plumbing in `lib/bim_core/`.

Runs as a pyRevit pushbutton under **Kinetic > Audits > Auto
Dimension**.

## v1 scope

- Linear MEP categories only: Cable Trays, Conduits, Ducts, Pipes.
- Active view only (current_view_only must stay true).
- Reference target: Nearest Grid only.
- Dimension geometry: aligned dimensions only.

Not in v1 (architecture supports, but no shipped behaviour):

- collision avoidance / chained dimensions / smart spacing
- Nearest Wall / Nearest Column / Selected Reference targets
- multi-view automation
- linked-model elements
- saved standards presets / discipline templates / company QA profiles

## Layout

```
kinetic.extension/
  Kinetic.tab/Audits.panel/
    Auto Dimension.pushbutton/    thin entry-point: script.py + bundle.yaml + icons
  lib/dimension_qa/
    profiles.py                   DimensioningProfile + default_profile_for + validate_profiles
    measurement_strategies/
      __init__.py                 (category_key, strategy_key) -> strategy registry
      base.py                     MeasurementReferenceStrategy ABC
      centreline.py               CentrelineStrategy (universal)
      face_strategies.py          Top / Bottom / Outside / Inside (face) + InvertLevel
    target_strategies/
      __init__.py                 strategy_key -> strategy registry
      base.py                     ReferenceTargetStrategy ABC
      nearest_grid.py             NearestGridStrategy (v1)
    rules_engine/
      __init__.py                 build_pipeline(profile, scope_is_active_view)
      already_dimensioned_rule.py NotAlreadyDimensionedRule
    dimensioning_engine.py        scan + place_dimensions + dimensioned_element_ids
    rules.py                      DEFAULT_SCAN_OPTIONS + from_config + default_profiles
    reporting.py                  per-profile HTML + flat CSV
    ui.py / ui.xaml               WPF dialog: discipline + subcategory + profile DataGrid
    configs/default.json
```

Shared with Auto Tag (in `lib/bim_core/`):
- `core.category_config` / `core.discipline_config`
- `core.geometry_utils` / `core.parameter_utils` / `core.system_classification`
- `rules_engine.{base, length_rules, orientation_rules, size_rules,
  visibility_rules, system_classification_rule, family_name_rule}`
- `element_filters` / `log`

## Measurement reference strategies

Each strategy returns `(Reference, anchor_xyz)` for one end of the
dimension. The dimension VALUE is exact (Revit measures from the
Reference itself); anchor_xyz is used by the engine to compute the
dim line geometry.

| Category | Available strategies |
| --- | --- |
| Cable Trays | Centreline, Outside Edge, Inside Edge, Top, Bottom |
| Conduits | Centreline, Outside Edge |
| Ducts | Centreline, Outside Face, Inside Face, Top, Bottom |
| Pipes | Centreline, Outside Face, Invert Level, Top, Bottom |

**Round elements (Pipes, Conduits) limitations.** Revit doesn't
expose distinct Top / Bottom / Invert face references for cylindrical
geometry. v1 strategies for these on round elements either:

- Return the curved cylinder side reference (Outside Face, Invert
  Level on pipes) - the dimension pins to the closest point on the
  cylinder along the dim line direction, which positions correctly
  when the dim line is offset above/below appropriately.
- Fail explicitly with a clear reason (Top / Bottom on pipes /
  conduits) - the report shows the skip and the user can switch the
  profile to Centreline or Outside Face.

Adding a new measurement strategy:
1. Subclass `MeasurementReferenceStrategy` in
   `measurement_strategies/face_strategies.py` (or a new module).
2. Register `(category_key, strategy_key): StrategyInstance()` in
   `measurement_strategies/__init__.REGISTRY`.
3. Append the key to `ORDER_BY_CATEGORY` for the desired display
   position.

## Reference target strategies

| key | label | scope | implemented in v1 |
| --- | --- | --- | --- |
| `nearest_grid` | Nearest Grid | universal | yes |
| `nearest_wall` | Nearest Wall | universal | no (v2) |
| `nearest_column` | Nearest Column | universal | no (v2) |
| `selected_reference` | Selected Reference | universal | no (v2) |

NearestGridStrategy looks for the closest grid line (dot product
with element direction <= 0.3 to be "perpendicular enough") and
returns its `Reference` + the foot of the perpendicular from the
element midpoint.

## Setup

1. Ensure `kinetic.extension` is registered with pyRevit.
2. Reload pyRevit (`pyRevit > Tools > Reload`). The **Auto
   Dimension** button appears in **Audits**.
3. Have at least one Dimension Type loaded in your project (any
   default Linear style works for v1).

## Using the tool

1. Open the plan view you want to dimension in.
2. Click **Auto Dimension**.
3. Pick a discipline. Tick one or more subcategories.
4. Tune each row in the grid:
   - filters: min/max length, horizontal/vertical, tolerance
   - measurement reference: per-row dropdown of category-applicable
     strategies (Centreline, Outside Face, Top, etc)
   - reference target: per-row dropdown (Nearest Grid in v1)
   - dimension style + offset distance
5. **Scan Model** runs every enabled profile against its category;
   the results pane shows a per-profile breakdown.
6. **Place Dimensions** wraps placement in one Transaction in the
   active view.
7. **Save Report** writes an HTML QA report; **Save Excel** writes a
   flat per-element CSV (UTF-8 BOM).

**Shift-click** opens the project's `auto_dimension.json` config
(creates from the shipped default on first use).

## Reports + logs

- `<project>/.bim/reports/auto_dimension_<timestamp>.html`
- `<project>/.bim/reports/auto_dimension_<timestamp>.csv`
- `<project>/.bim/logs/auto_dimension.log`

## Project config persistence

```json
{
  "scan": {"default_discipline_key": "mechanical"},
  "profiles": [
    {
      "discipline":               "mechanical",
      "binding":                  "duct",
      "enabled":                  true,
      "min_length_mm":            1500.0,
      "horizontal_only":          true,
      "current_view_only":        true,
      "skip_already_dimensioned": true,
      "measurement_reference":    "centreline",
      "reference_target":         "nearest_grid",
      "offset_distance_mm":       200.0
    }
  ]
}
```

## IronPython 2.7 notes

- PEP-263 `# -*- coding: utf-8 -*-` headers on every file.
- `.format()` strings only.
- `open(path, "wb")` for binary IO; no Py3 `encoding=` kwarg.
- `INotifyPropertyChanged` on `ProfileRow` implemented via the
  `add_/remove_PropertyChanged` handler-list idiom (mirror of the
  one in Auto Tag).
