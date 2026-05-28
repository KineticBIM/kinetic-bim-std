# -*- coding: utf-8 -*-
"""Local persistence for the license key and the cached machine file.

Rooted at %LOCALAPPDATA%\\KineticBIM\\license\\ (same base resolution as
bim_core.log), holding:

    machine.lic   - the signed Keygen machine file (PEM, plaintext; it is
                    already Ed25519-signed and machine-bound, so nothing
                    secret is exposed)
    license.key   - the user's license key, DPAPI-protected (CurrentUser)

The license key can activate/deactivate machines, so it is encrypted at
rest with Windows DPAPI via the CLR. Where the CLR is unavailable (the
CPython unit tests / non-Windows dev), it gracefully falls back to a
base64 encoding tagged "plain:" - obfuscation only - which never happens
on a real Revit workstation. The scheme tag is stored alongside the data
so reads always know how to decode.

FileStore is injectable (base_dir) so tests run against a temp directory;
default_store() returns the singleton rooted at the real license folder.
"""

import os
import io
import base64


_CERT_NAME = "machine.lic"
_KEY_NAME = "license.key"

_DEFAULT = None


def _resolve_base_dir():
    base = (os.environ.get("LOCALAPPDATA")
            or os.environ.get("APPDATA")
            or os.path.expanduser("~"))
    base = os.path.expandvars(base or "")
    if not base:
        base = os.path.expanduser("~")
    return os.path.normpath(os.path.join(base, "KineticBIM", "license"))


def default_store():
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = FileStore()
    return _DEFAULT


class FileStore(object):

    def __init__(self, base_dir=None):
        self.base_dir = base_dir or _resolve_base_dir()

    # --- machine file -------------------------------------------------

    def certificate_path(self):
        return os.path.join(self.base_dir, _CERT_NAME)

    def read_certificate(self):
        """Return the cached machine file text, or None if absent.
        Raises IOError if the file exists but cannot be read."""
        path = self.certificate_path()
        if not os.path.isfile(path):
            return None
        with io.open(path, "r", encoding="utf-8") as fh:
            return fh.read()

    def write_certificate(self, text):
        self._ensure_dir()
        with io.open(self.certificate_path(), "w", encoding="utf-8") as fh:
            fh.write(text if isinstance(text, type(u"")) else text.decode("utf-8"))

    # --- license key (encrypted at rest) ------------------------------

    def key_path(self):
        return os.path.join(self.base_dir, _KEY_NAME)

    def read_key(self):
        """Return the stored license key, or None if absent/unreadable."""
        path = self.key_path()
        if not os.path.isfile(path):
            return None
        try:
            with io.open(path, "r", encoding="utf-8") as fh:
                blob = fh.read().strip()
            return _decode_key(blob)
        except Exception:
            return None

    def write_key(self, key):
        self._ensure_dir()
        with io.open(self.key_path(), "w", encoding="utf-8") as fh:
            fh.write(_encode_key(key))

    # --- lifecycle ----------------------------------------------------

    def clear(self):
        for path in (self.certificate_path(), self.key_path()):
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except (OSError, IOError):
                pass

    def _ensure_dir(self):
        if not os.path.isdir(self.base_dir):
            os.makedirs(self.base_dir)   # IronPython 2.7 - no exist_ok


# --- key encoding (DPAPI with a tagged base64 fallback) ---------------

def _encode_key(key):
    protected = _dpapi_protect(key)
    if protected is not None:
        return "dpapi:" + protected
    return "plain:" + base64.b64encode(key.encode("utf-8")).decode("ascii")


def _decode_key(blob):
    if ":" not in blob:
        return None
    scheme, data = blob.split(":", 1)
    if scheme == "dpapi":
        return _dpapi_unprotect(data)
    if scheme == "plain":
        return base64.b64decode(data).decode("utf-8")
    return None


def _dpapi_protect(key):
    """Base64 of DPAPI-protected bytes, or None when the CLR is absent."""
    try:
        import clr  # type: ignore
        clr.AddReference("System.Security")
        from System.Security.Cryptography import (  # type: ignore
            ProtectedData, DataProtectionScope)
        from System.Text import Encoding  # type: ignore
        from System import Convert  # type: ignore
        raw = Encoding.UTF8.GetBytes(key)
        enc = ProtectedData.Protect(raw, None, DataProtectionScope.CurrentUser)
        return Convert.ToBase64String(enc)
    except Exception:
        return None


def _dpapi_unprotect(data):
    try:
        import clr  # type: ignore
        clr.AddReference("System.Security")
        from System.Security.Cryptography import (  # type: ignore
            ProtectedData, DataProtectionScope)
        from System.Text import Encoding  # type: ignore
        from System import Convert  # type: ignore
        enc = Convert.FromBase64String(data)
        raw = ProtectedData.Unprotect(enc, None, DataProtectionScope.CurrentUser)
        return Encoding.UTF8.GetString(raw)
    except Exception:
        return None
