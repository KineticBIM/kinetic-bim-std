# -*- coding: utf-8 -*-
"""Tests for bim_core.license_file against the committed synthetic
machine-file fixture.

Covers envelope parsing, signing-data construction, the algorithm
allow-list, dataset accessors, and the validity window. The Ed25519
signature itself is checked with the RFC 8032 reference oracle
(_ed25519_ref) - this proves parse() reconstructs the exact bytes the
signature was computed over.
"""

import os
import sys
import json
import base64
import datetime
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, os.pardir, "lib"))

import _ed25519_ref as ed                 # noqa: E402
from bim_core import license_file          # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures")


def _read(name):
    with open(os.path.join(FIXTURES, name)) as fh:
        return fh.read()


def _pem(outer):
    body = base64.b64encode(json.dumps(outer).encode("utf-8")).decode("ascii")
    lines = [body[i:i + 64] for i in range(0, len(body), 64)]
    return ("-----BEGIN MACHINE FILE-----\n" + "\n".join(lines)
            + "\n-----END MACHINE FILE-----\n")


class LicenseFileTest(unittest.TestCase):

    def setUp(self):
        self.text = _read("machine.lic")
        self.expected = json.loads(_read("expected.json"))
        self.pubkey = bytes(bytearray.fromhex(_read("public_key.hex").strip()))
        self.parsed = license_file.parse(self.text)

    def test_envelope_and_alg(self):
        self.assertEqual(self.parsed.file_type, "machine")
        self.assertEqual(self.parsed.alg, "base64+ed25519")

    def test_signing_message_is_typed_prefix_plus_enc(self):
        self.assertEqual(
            self.parsed.signing_message,
            ("machine/" + self.parsed.enc).encode("utf-8"))

    def test_signature_verifies_under_reference(self):
        # The crux: parse() rebuilt the exact signed bytes.
        self.assertTrue(ed.verify(
            self.parsed.signature, self.parsed.signing_message, self.pubkey))

    def test_dataset_accessors(self):
        self.assertEqual(self.parsed.fingerprint(),
                         self.expected["fingerprint"])
        self.assertEqual(self.parsed.policy_name(), "standard")
        self.assertIsNotNone(self.parsed.issued())
        self.assertIsNotNone(self.parsed.expiry())
        self.assertGreater(self.parsed.expiry(), self.parsed.issued())

    def test_is_current_within_window(self):
        midpoint = self.parsed.issued() + datetime.timedelta(days=1)
        self.assertTrue(license_file.is_current(self.parsed, midpoint))

    def test_is_current_rejects_expired(self):
        after = self.parsed.expiry() + datetime.timedelta(seconds=1)
        self.assertFalse(license_file.is_current(self.parsed, after))

    def test_is_current_rejects_not_yet_issued(self):
        before = self.parsed.issued() - datetime.timedelta(seconds=1)
        self.assertFalse(license_file.is_current(self.parsed, before))

    def test_rejects_encrypted_alg(self):
        outer = {"enc": "aGVsbG8=", "sig": "aGVsbG8=",
                 "alg": "aes-256-gcm+ed25519"}
        self.assertRaises(ValueError, license_file.parse, _pem(outer))

    def test_rejects_non_ed25519_alg(self):
        outer = {"enc": "aGVsbG8=", "sig": "aGVsbG8=", "alg": "base64+rsa"}
        self.assertRaises(ValueError, license_file.parse, _pem(outer))

    def test_rejects_missing_fields(self):
        outer = {"enc": "aGVsbG8=", "alg": "base64+ed25519"}  # no sig
        self.assertRaises(ValueError, license_file.parse, _pem(outer))

    def test_rejects_garbage(self):
        self.assertRaises(ValueError, license_file.parse, "not a license file")

    def test_rejects_empty(self):
        self.assertRaises(ValueError, license_file.parse, "")

    def test_tampered_signature_fails_verification(self):
        sig = bytearray(self.parsed.signature)
        sig[0] ^= 0x01
        self.assertFalse(ed.verify(
            bytes(sig), self.parsed.signing_message, self.pubkey))

    def test_tampered_payload_fails_verification(self):
        # Re-sign nothing: flip a byte of enc and confirm the original
        # signature no longer matches the new signing message.
        tampered_msg = ("machine/" + "X" + self.parsed.enc[1:]).encode("utf-8")
        self.assertFalse(ed.verify(
            self.parsed.signature, tampered_msg, self.pubkey))


if __name__ == "__main__":
    unittest.main()
