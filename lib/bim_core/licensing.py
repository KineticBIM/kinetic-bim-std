# -*- coding: utf-8 -*-
"""License gating for Kinetic BIM tools.

Contract surface that all six Standard tools call at entry to verify
the running user / workstation is licensed for the named tool. M1
implementation is a no-op placeholder so tool entry points can be
wired up now and the real Keygen-backed check drops in during M2
without retouching tool code.

Tools call licensing.require(tool_name) at the top of main().
require() shows a friendly error dialog and exits the script when
the check fails; otherwise returns normally.

The check() / require() split lets future code call check() directly
when it just needs a yes/no answer without the UX side effects -
e.g. conditionally rendering a 'license expires in N days' badge in
the WPF window header, or skipping a background telemetry call when
the seat isn't active.

Named licensing (not license) to avoid shadowing Python's built-in
license object from site.py.
"""


class LicenseError(Exception):
    """Raised when the licensing infrastructure itself fails (network
    unreachable, cache corrupt, signature invalid). Distinct from
    check() returning False, which means the license is valid but
    doesn't cover the requested tool."""


def check(tool_name):
    """Return True when the named tool is licensed to run, False
    otherwise. May raise LicenseError on infrastructure failure.

    M1: always returns True. M2 will:
        - Load the cached license check-out from
          %LOCALAPPDATA%\\KineticBIM\\license\\
        - Verify the Ed25519 signature against the hard-coded
          Kinetic BIM Keygen account public key
        - Confirm the active policy (Standard / Pro) covers
          tool_name
        - Confirm the machine fingerprint (Win32_ComputerSystemProduct
          UUID + machine SID + primary MAC, hashed) matches the one
          recorded against the seat
        - Refresh the check-out via Keygen actions/check-out when
          online and the TTL window is closing
    """
    return True


def require(tool_name):
    """Gate a pushbutton entry point. Returns normally when licensed;
    shows a friendly error dialog and exits the script when not.

    Call at the top of each pushbutton main() before any other tool
    state setup so unlicensed users don't see partial UI flash up
    before being kicked back.
    """
    try:
        if check(tool_name):
            return
        message = (
            "{0} is not licensed for this workstation.\n\n"
            "Contact your team lead or support@kineticbim.com to "
            "activate or transfer your seat.").format(
                _display_name(tool_name))
    except LicenseError as exc:
        message = str(exc) or (
            "License check failed. Contact support@kineticbim.com.")

    # Lazy import: errors.py imports from pyrevit at module top, so a
    # top-level import here would prevent licensing.py from being
    # imported outside Revit (e.g. by future unit tests that exercise
    # check() against a mock cache).
    from bim_core import errors
    errors.show_error(tool_name, message, exitscript=True)


def _display_name(tool_name):
    """auto_tag -> Auto Tag. Duplicated from errors._display_title
    rather than imported to keep licensing.py importable outside
    pyRevit / Revit."""
    if not tool_name:
        return "Kinetic BIM"
    parts = [p.capitalize() for p in tool_name.replace("_", " ").split() if p]
    return " ".join(parts) or "Kinetic BIM"
