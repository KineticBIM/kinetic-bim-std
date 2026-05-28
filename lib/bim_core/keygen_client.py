# -*- coding: utf-8 -*-
"""Thin Keygen JSON:API client for the Kinetic BIM desktop license flow.

Carries ONLY the user's license key - never an admin or product secret.
validate-key is unauthenticated; activate / check-out / deactivate use
"Authorization: License <key>", which Keygen permits when the policy's
authenticationStrategy is LICENSE or MIXED.

The HTTP transport is injectable: the default lazily loads bim_core._http
(.NET HttpWebRequest) at first use, so this module stays importable - and
unit-testable with a mock transport - under plain CPython.

    client = KeygenClient(account_id, transport=None)
    result = client.validate_key(key, fingerprint)   # ValidationResult
    machine_id = client.activate_machine(key, license_id, fingerprint, name, platform)
    certificate = client.check_out(key, machine_id, ttl)
    client.deactivate(key, machine_id)
"""

import json


def _log_http(method, url, status, text, authed):
    """Log a non-2xx Keygen response (endpoint + status + body) to the
    licensing log so live failures are diagnosable. Body carries only
    error title/detail, no secrets. Never raises."""
    try:
        from bim_core import log as log_module
        snippet = (text or "")[:600]
        log_module.get_logger(tool_name="licensing").error(
            "keygen %s %s -> %s (authed=%s) body=%s",
            method, url, status, authed, snippet)
    except Exception:
        pass


# Keygen account id - a path param, not a secret. Sandbox account used
# for development/testing; swap in the production account id at GA.
_ACCOUNT_ID = "2141e382-072c-44d5-87f1-e076efb3e741"

API_HOST = "https://api.keygen.sh"
API_VERSION = "v1"
KEYGEN_VERSION = "1.7"                       # pinned API version header
CONTENT_TYPE = "application/vnd.api+json"

DEFAULT_TTL = 1209600                         # 14 days, in seconds


class KeygenError(Exception):
    """A Keygen API error (non-2xx) or transport failure. `code` is the
    JSON:API errors[].code when present (e.g. MACHINE_LIMIT_EXCEEDED);
    `status` is the HTTP status (0 for transport failures)."""

    def __init__(self, message, code=None, status=None):
        super(KeygenError, self).__init__(message)
        self.code = code
        self.status = status


class ValidationResult(object):
    def __init__(self, valid, code, detail, license_id):
        self.valid = valid              # bool
        self.code = code                # str, e.g. "VALID", "NO_MACHINE"
        self.detail = detail            # str
        self.license_id = license_id    # str or None

    # Codes that mean "the license is good, just activate this machine".
    _ACTIVATABLE = ("NO_MACHINE", "NO_MACHINES", "FINGERPRINT_SCOPE_MISMATCH")

    def needs_activation(self):
        return (not self.valid) and self.code in self._ACTIVATABLE


class KeygenClient(object):

    def __init__(self, account_id=None, transport=None):
        self.account_id = account_id or _ACCOUNT_ID
        self._transport = transport     # None -> lazy bim_core._http.request

    # --- public API ---------------------------------------------------

    def validate_key(self, key, fingerprint):
        """Unauthenticated validate-key with a machine fingerprint scope."""
        body = {"meta": {"key": key, "scope": {"fingerprint": fingerprint}}}
        status, doc = self._send(
            "POST", "licenses/actions/validate-key", body=body)
        meta = (doc or {}).get("meta")
        if not meta:
            # No meta block means a hard HTTP error, not a validation verdict.
            raise self._error(status, doc, "License validation failed")
        data = (doc or {}).get("data") or {}
        return ValidationResult(
            valid=bool(meta.get("valid")),
            code=meta.get("code"),
            detail=meta.get("detail"),
            license_id=data.get("id"))

    def activate_machine(self, key, license_id, fingerprint, name, platform):
        """Create a Machine bound to the license. Returns the machine id."""
        body = {"data": {
            "type": "machines",
            "attributes": {
                "fingerprint": fingerprint,
                "platform": platform,
                "name": name,
            },
            "relationships": {
                "license": {"data": {"type": "licenses", "id": license_id}},
            },
        }}
        status, doc = self._send("POST", "machines", key=key, body=body)
        if status < 200 or status >= 300:
            raise self._error(status, doc, "Machine activation failed")
        machine_id = ((doc or {}).get("data") or {}).get("id")
        if not machine_id:
            raise KeygenError("Activation returned no machine id", status=status)
        return machine_id

    def find_machine(self, key, fingerprint):
        """Return the id of this license's machine matching the
        fingerprint, or None. Used when validation says the seat is
        already active here but we have no cached machine id."""
        query = "fingerprint={0}".format(fingerprint)
        status, doc = self._send("GET", "machines", key=key, query=query)
        if status < 200 or status >= 300:
            raise self._error(status, doc, "Machine lookup failed")
        items = (doc or {}).get("data") or []
        if items:
            return items[0].get("id")
        return None

    def check_out(self, key, machine_id, ttl=DEFAULT_TTL):
        """Check out a signed machine file. Returns the PEM certificate."""
        path = "machines/{0}/actions/check-out".format(machine_id)
        # include=license (not the nested license.policy) matches Keygen's
        # documented working example; the offline gate defaults a missing
        # policy to Standard, so we don't need the policy embedded.
        query = "ttl={0}&include=license".format(int(ttl))
        status, doc = self._send("POST", path, key=key, query=query)
        if status < 200 or status >= 300:
            raise self._error(status, doc, "License check-out failed")
        cert = (((doc or {}).get("data") or {})
                .get("attributes") or {}).get("certificate")
        if not cert:
            raise KeygenError("Check-out returned no certificate", status=status)
        return cert

    def deactivate(self, key, machine_id):
        """Delete the Machine (free the seat). 204 on success."""
        path = "machines/{0}".format(machine_id)
        status, doc = self._send("DELETE", path, key=key)
        if status not in (200, 202, 204):
            raise self._error(status, doc, "Deactivation failed")

    # --- internals ----------------------------------------------------

    def _send(self, method, path, key=None, body=None, query=None):
        url = "{0}/{1}/accounts/{2}/{3}".format(
            API_HOST, API_VERSION, self.account_id, path)
        if query:
            url = url + "?" + query
        headers = {
            "Content-Type": CONTENT_TYPE,
            "Accept": CONTENT_TYPE,
            "Keygen-Version": KEYGEN_VERSION,
        }
        if key:
            headers["Authorization"] = "License " + key
        payload = json.dumps(body) if body is not None else None

        status, text = self._transport_fn()(method, url, headers, payload)
        if status < 200 or status >= 300:
            _log_http(method, url, status, text, authed=bool(key))
        doc = None
        if text and text.strip():
            try:
                doc = json.loads(text)
            except ValueError:
                doc = None
        return status, doc

    def _transport_fn(self):
        if self._transport is None:
            from bim_core import _http
            self._transport = _http.request
        return self._transport

    def _error(self, status, doc, fallback):
        code = None
        detail = fallback
        errors = (doc or {}).get("errors") if isinstance(doc, dict) else None
        if errors:
            first = errors[0]
            code = first.get("code")
            detail = first.get("detail") or first.get("title") or fallback
        return KeygenError(detail, code=code, status=status)
