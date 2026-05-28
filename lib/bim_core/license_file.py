# -*- coding: utf-8 -*-
"""Parse and interpret Keygen license / machine files (offline).

A Keygen license/machine file is a PEM-style envelope:

    -----BEGIN MACHINE FILE-----
    <base64, wrapped every 80 chars>
    -----END MACHINE FILE-----

The base64 body decodes to a small JSON object {enc, sig, alg}:

    - alg "base64+ed25519": `enc` is base64-encoded JSON-API data; the
      Ed25519 signature `sig` is computed over the UTF-8 bytes of the
      string  "<type>/" + enc  where <type> is "machine" or "license".
    - alg "aes-256-gcm+ed25519": `enc` is encrypted. Not supported by
      the offline core (we only check out plaintext machine files).

This module is pure stdlib so it runs identically under IronPython 2.7
(pyRevit) and CPython (the unit tests). It does NOT perform the Ed25519
verification itself - that needs the BouncyCastle primitive in
_crypto.py. parse() exposes `signing_message` and `signature` for the
caller to verify, and the decoded `dataset` for reading fingerprint /
expiry / policy once the signature checks out.

parse() raises ValueError on any malformed input; the licensing layer
wraps that into a friendly LicenseError.
"""

import re
import json
import base64
import datetime


_PEM_RE = re.compile(
    r"-----BEGIN (MACHINE|LICENSE) FILE-----"
    r"(.*?)"
    r"-----END \1 FILE-----",
    re.DOTALL,
)

# Algorithms whose `enc` payload is plaintext base64 (not encrypted).
_PLAINTEXT_ALGS = ("base64+ed25519",)


class ParsedFile(object):
    """Decoded, not-yet-verified license/machine file.

    Hold onto `signature` + `signing_message` for the Ed25519 check,
    and read `dataset` (the JSON-API document) for fingerprint / expiry
    / policy *after* the signature has been verified.
    """

    def __init__(self, file_type, enc, signature, alg, dataset):
        self.file_type = file_type            # "machine" or "license"
        self.enc = enc                        # base64 str (the signed payload)
        self.signature = signature            # bytes
        self.alg = alg                        # str
        self.dataset = dataset                # dict (JSON-API document)
        self.signing_message = (
            "{0}/{1}".format(file_type, enc).encode("utf-8"))

    def fingerprint(self):
        """Machine fingerprint embedded in the file, or None (license
        files are not machine-scoped)."""
        try:
            return self.dataset["data"]["attributes"]["fingerprint"]
        except (KeyError, TypeError):
            return None

    def issued(self):
        """meta.issued as a naive UTC datetime, or None."""
        return _parse_iso8601(self._meta("issued"))

    def expiry(self):
        """meta.expiry as a naive UTC datetime, or None (no expiry)."""
        return _parse_iso8601(self._meta("expiry"))

    def policy_name(self):
        """Lower-cased policy name from the included resources, or None.

        Keygen embeds the license's policy as a resource in the
        top-level `included` array (type == "policies").
        """
        for res in self.dataset.get("included", []) or []:
            try:
                if res.get("type") == "policies":
                    name = res.get("attributes", {}).get("name")
                    if name:
                        return name.strip().lower()
            except AttributeError:
                continue
        return None

    def _meta(self, key):
        try:
            return self.dataset["meta"].get(key)
        except (KeyError, TypeError, AttributeError):
            return None


def parse(text):
    """Parse a license/machine file string into a ParsedFile.

    Raises ValueError if the envelope, base64, JSON, or algorithm is
    malformed or unsupported.
    """
    if not text:
        raise ValueError("Empty license file")

    match = _PEM_RE.search(text)
    if not match:
        raise ValueError("No license/machine file envelope found")

    file_type = match.group(1).lower()        # "machine" / "license"
    body = re.sub(r"\s+", "", match.group(2))  # strip the 80-char wrapping
    if not body:
        raise ValueError("Empty license file body")

    try:
        outer_json = base64.b64decode(body).decode("utf-8")
        outer = json.loads(outer_json)
    except Exception as exc:
        raise ValueError("Could not decode license file body: {0}".format(exc))

    enc = outer.get("enc")
    sig = outer.get("sig")
    alg = outer.get("alg")
    if not (enc and sig and alg):
        raise ValueError("License file missing enc/sig/alg")

    if "ed25519" not in alg:
        raise ValueError("Unsupported signature algorithm: {0}".format(alg))
    if alg not in _PLAINTEXT_ALGS:
        # e.g. aes-256-gcm+ed25519 - encrypted files need the license
        # key as a decryption secret, which the offline core does not
        # handle. The online follow-up can add this.
        raise ValueError("Encrypted license files are not supported: {0}"
                         .format(alg))

    try:
        signature = base64.b64decode(sig)
    except Exception as exc:
        raise ValueError("Could not decode signature: {0}".format(exc))

    try:
        dataset_json = base64.b64decode(enc).decode("utf-8")
        dataset = json.loads(dataset_json)
    except Exception as exc:
        raise ValueError("Could not decode license payload: {0}".format(exc))

    return ParsedFile(file_type, enc, signature, alg, dataset)


def is_current(parsed, now):
    """True when `now` (naive UTC datetime) falls within the file's
    validity window: issued <= now < expiry.

    A missing issued is treated as "already issued"; a missing expiry
    is treated as "never expires" (perpetual license file).
    """
    issued = parsed.issued()
    expiry = parsed.expiry()
    if issued is not None and now < issued:
        return False
    if expiry is not None and now >= expiry:
        return False
    return True


def _parse_iso8601(value):
    """Parse a Keygen ISO-8601 timestamp into a naive UTC datetime.

    Handles the shapes Keygen emits, e.g.:
        2026-05-28T12:00:00.000Z
        2026-05-28T12:00:00Z
        2026-05-28T12:00:00+00:00
    Fractional seconds and timezone designators are normalised away;
    Keygen timestamps are UTC. Returns None for falsy / unparseable
    input (callers treat None as "no bound").

    IronPython 2.7 has no datetime.fromisoformat, so parse by hand.
    """
    if not value:
        return None
    s = value.strip()

    # Split off any timezone designator. Keygen is always UTC.
    if s.endswith("Z"):
        s = s[:-1]
    else:
        # Trim a trailing +HH:MM / -HH:MM offset if present (after the
        # 'T', so we don't clip the date's own hyphens).
        t = s.find("T")
        if t != -1:
            for sign in ("+", "-"):
                pos = s.find(sign, t)
                if pos != -1:
                    s = s[:pos]
                    break

    # Drop fractional seconds.
    if "." in s:
        s = s.split(".", 1)[0]

    try:
        return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        try:
            return datetime.datetime.strptime(s, "%Y-%m-%d")
        except ValueError:
            return None
