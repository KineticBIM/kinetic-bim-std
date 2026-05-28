# -*- coding: utf-8 -*-
"""Online activation orchestration for Kinetic BIM Standard.

Drives the Keygen flow that produces the signed machine file the offline
gate (bim_core.licensing) consumes:

    validate-key -> (activate this machine if needed) -> check-out -> cache

and refreshes that file before it expires. The license key is the only
credential; it is stored locally (DPAPI) by license_store so refresh and
deactivate work without re-prompting.

The KeygenClient and the store are injectable so the whole state machine
is unit-testable under CPython with a mock transport and a temp-dir store
(no network, no CLR).
"""

import os
import datetime

from bim_core import fingerprint
from bim_core import license_file
from bim_core import license_store
from bim_core.keygen_client import KeygenClient, KeygenError


REFRESH_THRESHOLD_SECONDS = 7 * 86400        # refresh when < 7 days remain
_PLATFORM = "Windows"


class Outcome(object):
    def __init__(self, ok, status, message):
        self.ok = ok
        self.status = status        # machine-readable: activated, expired, ...
        self.message = message      # friendly, user-facing


def activate(key, client=None, store=None):
    """Run the full activation flow for a user-entered license key."""
    key = (key or "").strip()
    if not key:
        return Outcome(False, "invalid_key", "Please enter your license key.")

    client = client or KeygenClient()
    store = store or license_store.default_store()

    try:
        fp = fingerprint.current()
    except Exception as exc:
        _log_exc("fingerprint.current failed", exc)
        return Outcome(False, "error",
                       "Couldn't read this workstation's hardware ID.")

    try:
        v = client.validate_key(key, fp)
    except Exception as exc:
        return _network_outcome(exc)

    if v.valid and v.code == "VALID":
        return _checkout_existing(client, store, key, fp)

    if v.needs_activation():
        return _activate_and_checkout(client, store, key, fp, v.license_id)

    return _terminal_outcome(v)


def refresh_if_needed(client=None, store=None):
    """Re-check-out the machine file when it is within the refresh window.

    Fail-soft: returns False (keeping the existing file) on any error, so
    it is safe to call opportunistically from the license gate. Returns
    True only when a fresh file was successfully written.
    """
    store = store or license_store.default_store()
    try:
        cert = store.read_certificate()
    except Exception:
        return False
    if not cert:
        return False
    key = store.read_key()
    if not key:
        return False

    try:
        parsed = license_file.parse(cert)
    except Exception:
        return False

    expiry = parsed.expiry()
    if expiry is None:
        return False
    remaining = (expiry - datetime.datetime.utcnow()).total_seconds()
    if remaining > REFRESH_THRESHOLD_SECONDS:
        return False

    machine_id = _machine_id(parsed)
    if not machine_id:
        return False

    client = client or KeygenClient()
    try:
        fresh = client.check_out(key, machine_id)
        store.write_certificate(fresh)
        return True
    except Exception:
        return False        # keep the existing file until it truly expires


def deactivate(client=None, store=None):
    """Free this seat: delete the machine in Keygen, then clear local
    files. If the server call fails (e.g. offline), local files are kept
    so the user can retry rather than silently orphaning the activation."""
    store = store or license_store.default_store()
    cert = None
    try:
        cert = store.read_certificate()
    except Exception:
        cert = None
    key = store.read_key()

    if cert and key:
        try:
            parsed = license_file.parse(cert)
            machine_id = _machine_id(parsed)
            if machine_id:
                client = client or KeygenClient()
                client.deactivate(key, machine_id)
        except Exception as exc:
            return _network_outcome(exc, action="deactivate")

    store.clear()
    return Outcome(True, "deactivated",
                   "This workstation's seat has been released.")


def current_status(store=None):
    """Lightweight status for the Activate dialog: dict with activated,
    expiry (datetime or None), policy_name. Never raises."""
    store = store or license_store.default_store()
    try:
        cert = store.read_certificate()
        if not cert:
            return {"activated": False, "expiry": None, "policy_name": None}
        parsed = license_file.parse(cert)
        return {"activated": True,
                "expiry": parsed.expiry(),
                "policy_name": parsed.policy_name()}
    except Exception:
        return {"activated": False, "expiry": None, "policy_name": None}


# --- internals --------------------------------------------------------

def _activate_and_checkout(client, store, key, fp, license_id):
    name = os.environ.get("COMPUTERNAME") or "Unknown workstation"
    try:
        machine_id = client.activate_machine(
            key, license_id, fp, name, _PLATFORM)
    except KeygenError as exc:
        if _is_limit(exc):
            return _seat_in_use()
        return _network_outcome(exc)
    except Exception as exc:
        return _network_outcome(exc)
    return _checkout(client, store, key, machine_id, "activated",
                     "Activation complete - your tools are licensed on this "
                     "workstation.")


def _checkout_existing(client, store, key, fp):
    try:
        machine_id = client.find_machine(key, fp)
    except Exception as exc:
        return _network_outcome(exc)
    if not machine_id:
        return Outcome(False, "error",
                       "This seat looks active but the workstation record "
                       "couldn't be found. Contact support@kineticbim.com.")
    return _checkout(client, store, key, machine_id, "already_active",
                     "This workstation is already licensed - license "
                     "refreshed.")


def _checkout(client, store, key, machine_id, status, message):
    try:
        cert = client.check_out(key, machine_id)
    except Exception as exc:
        return _network_outcome(exc)
    try:
        store.write_certificate(cert)
        store.write_key(key)
    except Exception:
        return Outcome(False, "error",
                       "Activated, but couldn't save the license locally. "
                       "Check folder permissions and try again.")
    return Outcome(True, status, message)


def _terminal_outcome(v):
    code = v.code
    if code == "EXPIRED":
        return Outcome(False, "expired",
                       "Your license has expired. Renew it or contact "
                       "support@kineticbim.com.")
    if code == "SUSPENDED":
        return Outcome(False, "suspended",
                       "Your license has been suspended. Contact "
                       "support@kineticbim.com.")
    if code == "TOO_MANY_MACHINES":
        return _seat_in_use()
    return Outcome(False, "invalid_key",
                   "That license key wasn't recognised. Check it and try "
                   "again, or contact support@kineticbim.com.")


def _seat_in_use():
    return Outcome(False, "seat_in_use",
                   "Your seat is already active on another workstation. "
                   "Release it there (Deactivate) before activating here.")


def _network_outcome(exc, action="reach the licensing server"):
    _log_exc("activation transport/keygen error", exc)
    return Outcome(False, "network_error",
                   "Couldn't {0}. Check your internet connection and try "
                   "again.".format(action if action != "deactivate"
                                    else "release the seat right now"))


def _log_exc(message, exc):
    """Log a raw exception to the licensing log so live (in-Revit)
    failures are diagnosable; never raises."""
    try:
        from bim_core import log as log_module
        logger = log_module.get_logger(tool_name="licensing")
        code = getattr(exc, "code", None)
        status = getattr(exc, "status", None)
        logger.error("activation: %s: %s: %s (code=%s status=%s)",
                     message, type(exc).__name__, exc, code, status)
    except Exception:
        pass


def _is_limit(exc):
    code = getattr(exc, "code", None)
    return code in ("MACHINE_LIMIT_EXCEEDED", "TOO_MANY_MACHINES",
                    "FINGERPRINT_TAKEN")


def _machine_id(parsed):
    try:
        return parsed.dataset.get("data", {}).get("id")
    except AttributeError:
        return None
