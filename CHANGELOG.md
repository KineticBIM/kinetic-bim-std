# Changelog

All notable changes to Kinetic BIM Standard are recorded here.
The format follows [Keep a Changelog](https://keepachangelog.com/), and the
project uses [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.
The version is set in `lib/bim_core/version.py` and surfaced in the ribbon's
**Help > About** dialog.

## [Unreleased]

## [0.1.0-dev] - 2026-05-29

First packaged developer build. Six tools across four ribbon panels, a
licence-activation client, and a distributable installer.

### Added
- **Tools** — Auto Tag, Auto Dimension, Health Audit, QA Check, Sheet
  Automation (Create / Rename / Renumber), and Clash Reporting, organised under
  the **Audits**, **Sheets**, **Coordination**, and **Help** ribbon panels.
- **Licensing** — per-seat activation against the Kinetic licence service:
  enter a licence key in **Help > Activate**, with offline verification and a
  cached check-out so tools keep working without a constant connection. Every
  tool is gated at launch with a clear message if the seat is not activated.
- **Progress + cancel** — the long-running scans (Auto Tag, Auto Dimension,
  Health Audit, QA Check) show a progress bar and can be cancelled.
- **Friendly error dialogs** — failures surface as readable, per-tool dialogs
  with the detail and a path to the log file, instead of raw tracebacks.
- **Help > About** — shows the version, the installed tools, licence status,
  and the local logs folder.
- **Packaging** — `tools/build_extension.py` builds a clean, distributable
  `Kinetic.extension`, and `install.ps1` deploys it into pyRevit and clears the
  caches (with an `-Uninstall` switch).

[Unreleased]: https://github.com/KineticBIM/kinetic-bim-std/compare/v0.1.0-dev...HEAD
[0.1.0-dev]: https://github.com/KineticBIM/kinetic-bim-std/releases/tag/v0.1.0-dev
