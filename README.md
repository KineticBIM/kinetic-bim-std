# Kinetic BIM Standard

A pyRevit extension for Autodesk Revit that bundles Kinetic BIM's QA,
documentation, and coordination tools into a single ribbon tab.

| Panel | Tools |
|-------|-------|
| **Audits** | Auto Tag, Auto Dimension, Health Audit, QA Check |
| **Sheets** | Sheet Create, Sheet Rename, Sheet Renumber |
| **Coordination** | Clash Reporting, Refresh Models, Regenerate Pack, Open Output |
| **Help** | About, Activate Licence |

## Requirements

- Autodesk Revit with [pyRevit](https://github.com/pyrevitlabs/pyRevit/releases)
  installed.
- Windows.

## Install

Download the latest `Kinetic-<version>.zip`, unzip it, and follow
[`INSTALL.txt`](INSTALL.txt) — in short: close Revit, run `install.ps1`, start
Revit, then activate your licence from **Help > Activate**.

## Build a release (maintainers)

```
python tools/build_extension.py
```

This stages a clean `Kinetic.extension` (test suite, build tooling, and git
metadata stripped) and writes `dist/Kinetic-<version>.zip`, which contains the
extension plus `install.ps1` and `INSTALL.txt`. The version comes from
`lib/bim_core/version.py`; bump it there before cutting a build and record the
change in [`CHANGELOG.md`](CHANGELOG.md).

## Licence

Commercial. Use requires an active Kinetic BIM Standard licence.
