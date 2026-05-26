# Auto Tag - Annotation QA (v5)

Per-subcategory rule-based BIM annotation QA + intelligent tagging
across **20 Revit categories** spanning linear MEP, equipment,
fixtures, accessories, fittings, devices, and generic models. Runs as
a pyRevit pushbutton under **Kinetic > Audits > Auto Tag**.

In v5 every ticked subcategory becomes a row in a configuration grid
where its filters, size constraints, tag family, leader and skip
preferences are edited independently. The engine iterates the row
list and runs one rule pipeline per profile - cable trays can be on
1000mm + horizontal-only + Cable Tray Tag while conduits in the same
scan are on 3000mm + horizontal-only + Conduit Tag while ducts are on
1500mm + no-orientation + Duct Tag.

Internally the package is still `lib/annotation_qa/`; the user-facing
tool is "Auto Tag".

## Supported categories

| Priority | Category | Geometry | Rules supported |
| --- | --- | --- | --- |
| Linear MEP | Cable Trays, Conduits, Ducts, Pipes | LocationCurve | length, orientation, size, visibility, skip-tagged |
| P1 | Pipe Accessories, Mechanical Equipment, Electrical Equipment | LocationPoint | visibility, skip-tagged |
| P2 | Sprinklers, Lighting Fixtures, Plumbing Fixtures | LocationPoint | visibility, skip-tagged |
| P3 | Pipe / Duct / Conduit / Cable Tray Fittings | LocationPoint | visibility, skip-tagged |
| P3 | Duct Accessories, Lighting Devices, Electrical Fixtures, Fire Alarm Devices, Specialty Equipment | LocationPoint | visibility, skip-tagged |
| P3 | Generic Models | LocationPoint | visibility, skip-tagged |

Point-based categories run a shorter pipeline (visibility +
skip-already-tagged) and place tags at the element's `LocationPoint`
rather than a curve midpoint. The grid renders the inapplicable cells
disabled with a soft-grey background so it's obvious which filters
are running per row.

## Layout

```
kinetic.extension/
  Kinetic.tab/Audits.panel/
    Auto Tag.pushbutton/            thin entry-point: script.py + bundle.yaml + icons
  lib/annotation_qa/
    profiles.py                     TaggingProfile + default_profile_for + validate_profiles
    core/
      category_config.py            CategoryConfig + REGISTRY (single source of truth)
      discipline_config.py          DisciplineConfig + SubcategoryBinding (binding filters)
      geometry_utils.py             units + curve geometry + element_origin
      parameter_utils.py            per-category size BuiltInParameter map
      system_classification.py      MEP system classification reader
    rules_engine/
      base.py                       Rule + RulePipeline
      length_rules.py               MinimumLengthRule, MaximumLengthRule
      orientation_rules.py          HorizontalRule, VerticalRule
      size_rules.py                 SizeRule (per-category dispatch)
      visibility_rules.py           VisibilityRule
      tagged_rule.py                NotAlreadyTaggedRule
      system_classification_rule.py SystemClassificationRule
      family_name_rule.py           FamilyNamePatternRule
      __init__.py                   build_pipeline(profile) - composes rules from one TaggingProfile
    element_filters.py              collection (registry-backed)
    tagging_engine.py               tag discovery + placement (point + curve)
    qa_engine.py                    scan + place + per-profile records
    rules.py                        DEFAULT_SCAN_OPTIONS + from_config (v5 + v3/v4 migration)
    reporting.py                    per-profile HTML report (sections, exclusions, rows)
    log.py                          file logger
    ui.py / ui.xaml                 WPF dialog: discipline + subcategory + profile DataGrid
    configs/default.json
```

## TaggingProfile

```python
class TaggingProfile(object):
    discipline_key       # e.g. "mechanical"
    binding              # SubcategoryBinding (carries category_key,
                         # system_classifications, family_name_patterns)
    enabled
    min_length_mm        # None = no lower bound; rule omitted
    max_length_mm        # None = no upper bound; rule omitted
    horizontal_only / vertical_only / orientation_tol_deg
    size_filters         # flat dict {"width_mm_min": ..., "width_mm_max": ...,
                         #            "height_mm_min": ..., "height_mm_max": ...,
                         #            "diameter_mm_min": ..., "diameter_mm_max": ...}
                         # only the dims this category supports are present
    skip_already_tagged
    add_leader
    tag_symbol_id        # int FamilySymbol.Id or None for "use Revit default"

    @property
    def category_key(self): ...   # via binding
    @property
    def cfg(self): ...            # CategoryConfig from registry
    @property
    def key(self): ...            # "<discipline>/<binding>" - unique

    def supports(self, rule_key): ...
    def validate(self):           # first user-fixable error or None
    def active_rule_summary(self):  # short text, used in HTML report
    def to_dict(self) / from_dict(cls, data): ...
```

`profiles.default_profile_for(discipline_key, binding)` constructs a
profile with category-appropriate defaults (linear MEP starts at
min_length=1000mm + horizontal_only=True; point categories get just
skip_already_tagged=True).

`profiles.validate_profiles(profiles)` returns `(errors_by_key,
has_blocking)` - the dialog refuses to scan when blocking.

## CategoryConfig + capability gating

```python
class CategoryConfig:
    key                # "pipe_accessory"
    label              # "Pipe Accessories"
    bic                # BuiltInCategory.OST_PipeAccessory
    tag_bic            # BuiltInCategory.OST_PipeAccessoryTags
    geometry_kind      # "linear" | "point"
    supported_rules    # frozenset of rule names this category supports
    size_dimensions    # tuple of dim keys ("width", "diameter", ...) - empty = none

    def supports(self, rule_key): ...
```

Both the rule pipeline and the UI grid read `cfg.supports(rule_name)`
to decide whether to compose a rule / render a cell as editable.
Adding a new category is still a single-file edit in
`core/category_config.py`.

## Rule architecture

```python
class Rule:
    name = "rule"
    def passes(self, element, context):
        return True, None     # or (False, "reason")
```

`RulePipeline.evaluate(element, ctx)` short-circuits on the first
failing rule; `(passes, reason, failing_rule_name)`. `qa_engine`
tallies failures by rule name and logs which rule excluded each
element.

Per-element `ctx` is mutable; rules cache computed values
(`length_mm`, `slope_from_horizontal_deg`, `system_classification`)
so peer rules don't re-hit Revit. `ctx` carries the active `profile`
(not a shared options dict) so per-profile values like
`orientation_tol_deg` flow through cleanly.

## Filters surfaced in the grid

| Column | Rule class | Where it applies |
| --- | --- | --- |
| Min Len mm | `MinimumLengthRule` | Linear MEP only; blank = no lower bound |
| Max Len mm | `MaximumLengthRule` | Linear MEP only; blank = no upper bound |
| Horiz | `HorizontalRule` | Linear MEP only; mutex with Vert |
| Vert | `VerticalRule` | Linear MEP only; mutex with Horiz |
| Tol mm | (param of orientation rules) | Linear MEP only; default 50mm |
| W min / W max | `SizeRule` | Cable Trays, Ducts |
| H min / H max | `SizeRule` | Ducts |
| Dia min / Dia max | `SizeRule` | Conduits, Flex Ducts, Pipes |
| Tag family | (engine) | Per-row ComboBox; remembered per profile |
| Lead | (engine) | Per row |
| Skip | `NotAlreadyTaggedRule` | Per row |

Cells that don't apply to a row's category render disabled +
soft-grey via per-column `CellStyle` DataTriggers in `ui.xaml` bound
to the row's `Supports{X}` flags.

## Adding a new rule

```python
# rules_engine/cost_centre_rule.py
from bim_core.rules_engine.base import Rule

class CostCentreRule(Rule):
    name = "cost_centre"
    def __init__(self, allowed_centres):
        self.allowed = frozenset(allowed_centres)
    def passes(self, element, context):
        cc = _read_cost_centre(element)
        if cc is None:
            return False, "no cost centre"
        if cc not in self.allowed:
            return False, "cost centre '{0}' not in allow-list".format(cc)
        return True, None
```

Then:

1. Add a field to `TaggingProfile` (and serialize it in
   `to_dict`/`from_dict`).
2. Wire it into `rules_engine.build_pipeline` reading the new field
   from the profile and gating on `profile.supports("cost_centre")`.
3. Add `"cost_centre"` to the relevant categories' `supported_rules`
   set in `core/category_config.REGISTRY`.
4. Add a column to `ui.xaml` (with a `Supports*` flag and a
   `Min*Text` / boolean property on `ProfileRow` in `ui.py`) so the
   user can edit it.

The pipeline + grid both honour the capability declaration; no engine
refactor required.

## Setup

1. Ensure `kinetic.extension` is registered with pyRevit.
2. Reload pyRevit (`pyRevit > Tools > Reload`). The **Auto Tag**
   button appears in **Audits**.
3. Load at least one tag family for each category you'll tag (each
   category looks for its native tag BIC - `OST_CableTrayTags`,
   `OST_PipeAccessoryTags`, `OST_MechanicalEquipmentTags`, etc.).

## Using the tool

1. Open the view you want to tag in.
2. Click **Auto Tag**.
3. Pick a discipline from the top-left dropdown. Tick one or more
   subcategories on the right. Each ticked subcategory drops a row
   into the grid below.
4. Tune each row in place: adjust min/max length, flip orientation
   flags, set width / height / diameter bounds, pick a tag family
   from the row's combo, toggle leaders / skip. Inapplicable cells
   are visibly disabled (grey background).
5. Use the **On** column to temporarily exclude a profile without
   losing its settings.
6. **Scan Model** runs every enabled profile against its category;
   the results pane shows a per-profile breakdown.
7. **Place Tags** wraps placement in one Transaction in the active
   view; each profile's chosen tag family is used per record.
8. **Save Report** writes an HTML QA report to
   `<project>/.bim/reports/auto_tag_<timestamp>.html` with one
   section per profile.
9. **Save Excel** writes a flat CSV (one row per scanned element)
   with profile / discipline / subcategory / category / id / name
   / length / system / eligibility / placement columns. UTF-8 BOM
   so Excel auto-detects the encoding; opens natively, sort and
   pivot from there.

**Shift-click** opens the project's `auto_tag.json` config (creates
from the shipped default on first use).

## Reports + logs

- `<project>/.bim/reports/auto_tag_<timestamp>.html` - per-profile
  sections: profile label, active filters line, per-profile counts,
  exclusions table, per-element rows.
- `<project>/.bim/reports/auto_tag_<timestamp>.csv` - flat
  per-element table for Excel (UTF-8 with BOM). Column order is
  reporting.CSV_HEADER; one row per scanned element.
- `<project>/.bim/logs/auto_tag.log` - timestamped log of every scan,
  placement, and rule failure (rule name + element id + element
  name).

All three fall back to the user's home folder when the project is
unsaved.

## Project config persistence

`<project>/.bim/auto_tag.json` shape:

```json
{
  "scan":     {"whole_model": false, "default_discipline_key": "mechanical"},
  "profiles": [
    {
      "discipline":          "mechanical",
      "binding":             "duct",
      "enabled":             true,
      "min_length_mm":       1500.0,
      "max_length_mm":       null,
      "horizontal_only":     false,
      "vertical_only":       false,
      "orientation_tol_deg": 15.0,
      "size_filters":        {"width_mm_min":  null, "width_mm_max":  null,
                              "height_mm_min": null, "height_mm_max": null},
      "skip_already_tagged": true,
      "add_leader":          false,
      "tag_symbol_id":       null
    }
  ]
}
```

Legacy v3 / v4 configs (the `{"rule": {...}}` shape with
`selected_bindings` + global filter values) are auto-migrated by
`rules.from_config`: each binding entry becomes a TaggingProfile
carrying the lifted global rule values and the matching
`size_filters[cat_key]` sub-dict. Old project files keep working with
no manual conversion.

## IronPython 2.7 notes

The pushbutton runs on IronPython 2.7:

- PEP-263 `# -*- coding: utf-8 -*-` headers on every file.
- `.format()` strings only (no f-strings).
- `open(path, "rb") / open(path, "wb")` for binary IO; no Py3
  `encoding=` kwarg.
- Stdlib `logging` + `datetime` only.
- `INotifyPropertyChanged` on `ProfileRow` is implemented manually
  via `add_/remove_PropertyChanged` handler list - the canonical
  IronPython idiom for WPF data binding.

## Future expansion (NOT in v5)

- **Saved standards / discipline templates / project profiles /
  company standards.** The architecture supports them - each is a
  JSON file producing a list of `TaggingProfile` via
  `TaggingProfile.from_dict`. v5 ships no UI, no chooser, no export
  flow; that's the natural next step.
- **Architectural + structural categories** (doors, windows, rooms,
  furniture, casework, framing, columns, foundations). Same pattern
  as the existing point categories - register them in
  `core/category_config.REGISTRY`, decide which rules apply, add
  unique placement logic in `geometry_utils.element_origin` if
  needed.
- **Linked-model support.** Currently the collector skips
  `RevitLinkInstance`. Add a second pass over each link and use
  `LinkElementId` when creating the tag reference.
- **Multi-view placement.** Whole-model scope reports "eligible
  elsewhere" but can't tag those records itself.
- **Collision avoidance / smart placement.** Replace
  `geometry_utils.element_origin` with a geometry-aware helper for
  specific categories. The grid and rule pipeline don't change.
- **Missing-tag / duplicate-tag / wrong-family-tag detection** and
  **standards compliance reporting** are natural extensions of the
  per-profile breakdown + new rule classes for the additional
  checks. Architecture supports it; v5 doesn't ship UI for it.
- Items listed as out-of-scope by the spec: cloud sync,
  subscriptions, licensing, AI positioning, multi-user, dashboards,
  ACC integration.
