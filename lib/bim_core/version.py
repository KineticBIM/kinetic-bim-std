# -*- coding: utf-8 -*-
"""Single source of truth for the Kinetic BIM Standard version.

Read by the About dialog, and intended to be read by the future
installer build script and any telemetry / support headers we add
during M2-M7. Bump here when cutting a build; nothing else hard-codes
the string.

Version scheme:
    MAJOR.MINOR.PATCH[-stage]

    - MAJOR bumps on incompatible changes to per-doc config JSON
      (auto_tag.json / auto_dimension.json / qa_config.json).
    - MINOR bumps on new tools or non-breaking behavior shifts.
    - PATCH bumps on bug fixes.
    - -stage suffix: "dev" (current M1 work), "alpha" (internal),
      "beta" (pilot firms M6), absent for GA (M7+).
"""

__version__ = "0.1.0-dev"
