# -*- coding: utf-8 -*-
"""License gating for Kinetic BIM tools.

Contract surface that all six Standard tools call at entry to verify
the running user / workstation is licensed for the named tool. Tools
call licensing.require(tool_name) at the top of main(); require() shows
a friendly error dialog and exits the script when the check fails,
otherwise returns normally.

The check() / require() split lets future code call check() directly
when it just needs a yes/no answer without the UX side effects - e.g.
the About dialog reads check("about") to render license status.

M2 offline verification core (this is what check() does now):
    - Locate the cached, signed machine file under
      %LOCALAPPDATA%\\KineticBIM\\license\\
    - Verify its Ed25519 signature against the hard-coded Kinetic BIM
      Keygen account public key (offline; see _crypto.py)
    - Enforce the file's validity window (meta.issued / meta.expiry)
    - Confirm the embedded machine fingerprint matches this workstation
      (see fingerprint.py)
    - Confirm the active policy (Standard / Pro) covers tool_name

Grace mode: until the online activation flow exists, no machine file is
present on disk in normal use. So when no file is found the gate is
permissive (_ENFORCE_WHEN_ABSENT = False) - this avoids locking users
out of the tools before activation ships. A file that IS present is
fully enforced (bad signature / expired / wrong machine -> LicenseError).
Flip _ENFORCE_WHEN_ABSENT to True once activation can produce a file.

Still out of scope (online follow-up): Keygen API client, license-key
entry, machine activation, online check-out / TTL refresh, AES-256-GCM
encrypted files, and swapping the DEV public key for the real account
key below.

Named licensing (not license) to avoid shadowing Python's built-in
license object from site.py.
"""

import os
import datetime

from bim_core import log as log_module
from bim_core import license_file
from bim_core import fingerprint
from bim_core import _crypto


# --- M2 configuration -------------------------------------------------

# Permissive when no machine file is present. See grace-mode note above.
# Flip to True with the online activation follow-up.
_ENFORCE_WHEN_ABSENT = False

# Kinetic BIM Keygen account Ed25519 public key (hex). Ed25519 public
# keys are not secret - hard-coding it is the whole point of offline
# verification.
# DEV PLACEHOLDER: this is the throwaway key that signs the synthetic
# test fixtures. Replace with the real Keygen account public key during
# the online activation follow-up.
_ACCOUNT_PUBLIC_KEY_HEX = (
    "3ccd241cffc9b3618044b97d036d8614593d8b017c340f1dee8773385517654b")

# Which tools each policy entitles. Standard is a single all-tools
# policy; the granularity exists for the future Pro tier.
_STANDARD_TOOLS = frozenset([
    "auto_tag",
    "auto_dimension",
    "health_audit",
    "qa_check",
    "clash_reporting",
    "sheet_create",
    "sheet_rename",
    "sheet_renumber",
])
_POLICY_TOOLS = {
    "standard": _STANDARD_TOOLS,
}

_LICENSE_FILENAME = "machine.lic"


class LicenseError(Exception):
    """Raised when the licensing infrastructure itself fails (file
    unreadable, corrupt, signature invalid, expired, wrong machine,
    verification primitive unavailable). Distinct from check() returning
    False, which means the license is valid but its policy doesn't cover
    the requested tool."""


def check(tool_name):
    """Return True when the named tool is licensed to run, False when
    the seat is valid but its policy doesn't cover the tool. Raises
    LicenseError on any infrastructure failure.

    See the module docstring for the full verification sequence and the
    grace-mode behaviour when no machine file is present.
    """
    path = _license_path()

    if not os.path.isfile(path):
        if _ENFORCE_WHEN_ABSENT:
            raise LicenseError(
                "No license found for this workstation.\n\n"
                "Activate your seat or contact support@kineticbim.com.")
        _log("No machine file found; running in pre-activation grace mode.")
        return True

    text = _read_file(path)
    parsed = _parse(text)
    _verify_signature(parsed)
    _verify_current(parsed)
    _verify_fingerprint(parsed)

    # Seat is valid. About is a diagnostic - always allowed.
    if tool_name == "about":
        return True
    tools = _POLICY_TOOLS.get(parsed.policy_name() or "", frozenset())
    return tool_name in tools


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
    # imported outside Revit (e.g. by the unit tests that exercise
    # check() against a fixture cache).
    from bim_core import errors
    errors.show_error(tool_name, message, exitscript=True)


# --- verification steps (each raises LicenseError on failure) ---------

def _read_file(path):
    import io
    try:
        with io.open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except (OSError, IOError) as exc:
        raise LicenseError(
            "Couldn't read the license file.\n\nDetail: {0}".format(exc))


def _parse(text):
    try:
        return license_file.parse(text)
    except Exception as exc:
        raise LicenseError(
            "The license file is corrupt or unreadable.\n\n"
            "Detail: {0}".format(exc))


def _verify_signature(parsed):
    try:
        ok = _crypto.verify(
            _ACCOUNT_PUBLIC_KEY_HEX,
            parsed.signing_message,
            parsed.signature)
    except Exception as exc:
        # The BouncyCastle primitive couldn't be loaded - infrastructure
        # failure, not an invalid license.
        raise LicenseError(
            "License verification is unavailable on this machine.\n\n"
            "Contact support@kineticbim.com.\n\nDetail: {0}".format(exc))
    if not ok:
        raise LicenseError(
            "The license signature is invalid. The file may have been "
            "altered.\n\nContact support@kineticbim.com.")


def _verify_current(parsed):
    if not license_file.is_current(parsed, datetime.datetime.utcnow()):
        expiry = parsed.expiry()
        when = expiry.strftime("%Y-%m-%d") if expiry else "an earlier date"
        raise LicenseError(
            "Your license expired on {0}.\n\n"
            "Reconnect to the internet to refresh it, or contact "
            "support@kineticbim.com.".format(when))


def _verify_fingerprint(parsed):
    embedded = parsed.fingerprint()
    try:
        local = fingerprint.current()
    except Exception as exc:
        raise LicenseError(
            "Couldn't read this workstation's hardware ID.\n\n"
            "Contact support@kineticbim.com.\n\nDetail: {0}".format(exc))
    if embedded != local:
        raise LicenseError(
            "This license is registered to a different workstation.\n\n"
            "Transfer your seat at support@kineticbim.com.")


# --- helpers ----------------------------------------------------------

def _license_path():
    """%LOCALAPPDATA%\\KineticBIM\\license\\machine.lic. Mirrors the
    base-dir resolution in bim_core.log."""
    base = (os.environ.get("LOCALAPPDATA")
            or os.environ.get("APPDATA")
            or os.path.expanduser("~"))
    base = os.path.expandvars(base or "")
    if not base:
        base = os.path.expanduser("~")
    return os.path.normpath(
        os.path.join(base, "KineticBIM", "license", _LICENSE_FILENAME))


def _log(message):
    try:
        log_module.get_logger(tool_name="licensing").info(message)
    except Exception:
        pass


def _display_name(tool_name):
    """auto_tag -> Auto Tag. Duplicated from errors._display_title
    rather than imported to keep licensing.py importable outside
    pyRevit / Revit."""
    if not tool_name:
        return "Kinetic BIM"
    parts = [p.capitalize() for p in tool_name.replace("_", " ").split() if p]
    return " ".join(parts) or "Kinetic BIM"
