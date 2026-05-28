# -*- coding: utf-8 -*-
"""Tests for bim_core.licensing.check() - the offline gate's own logic.

check() sequences pieces that are tested in depth elsewhere: the Ed25519
primitive (test_ed25519_kat), envelope parsing + signing-bytes
reconstruction (test_license_file), and the activation state machine
(test_activation). So here the CLR-backed _crypto.verify and the hardware
fingerprint are stubbed - what's under test is check()'s OWN branching:
the _ENFORCE_WHEN_ABSENT gate (the reason this suite exists), the
signature / validity-window / fingerprint sequence, and policy coverage.
"""

import os
import sys
import json
import base64
import shutil
import tempfile
import datetime
import unittest

# Keep the licensing logger out of the real %LOCALAPPDATA%.
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="kbim-test-lic-")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "lib"))

from bim_core import licensing                          # noqa: E402


def _future():
    return datetime.datetime.utcnow() + datetime.timedelta(days=14)


def _past():
    return datetime.datetime.utcnow() - datetime.timedelta(days=1)


def _machine_file(expiry_dt, fingerprint="FP", policy="Standard"):
    """A parseable plaintext machine file. The signature is a placeholder
    ('AA==') because these tests stub _crypto.verify; the real signing
    bytes are validated by test_license_file."""
    dataset = {
        "data": {"type": "machines", "id": "MID",
                 "attributes": {"fingerprint": fingerprint}},
        "included": [{"type": "policies", "attributes": {"name": policy}}],
        "meta": {"expiry": expiry_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")},
    }
    enc = base64.b64encode(json.dumps(dataset).encode("utf-8")).decode("ascii")
    outer = {"enc": enc, "sig": "AA==", "alg": "base64+ed25519"}
    body = base64.b64encode(json.dumps(outer).encode("utf-8")).decode("ascii")
    lines = [body[i:i + 64] for i in range(0, len(body), 64)]
    return ("-----BEGIN MACHINE FILE-----\n" + "\n".join(lines)
            + "\n-----END MACHINE FILE-----\n")


class LicensingGateTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cert_path = os.path.join(self.tmp, "machine.lic")

        # Snapshot every module-level name these tests mutate.
        self._orig = {
            "path": licensing._license_path,
            "verify": licensing._crypto.verify,
            "fp": licensing.fingerprint.current,
            "enforce": licensing._ENFORCE_WHEN_ABSENT,
            "auto": licensing._AUTO_REFRESH,
            "attempted": licensing._REFRESH_ATTEMPTED,
        }
        licensing._license_path = lambda: self.cert_path
        licensing._crypto.verify = lambda pub, msg, sig: True
        licensing.fingerprint.current = lambda: "FP"
        # No once-per-session online refresh: keeps the Keygen client /
        # HTTP stack out of these tests entirely.
        licensing._AUTO_REFRESH = False
        licensing._REFRESH_ATTEMPTED = False

    def tearDown(self):
        licensing._license_path = self._orig["path"]
        licensing._crypto.verify = self._orig["verify"]
        licensing.fingerprint.current = self._orig["fp"]
        licensing._ENFORCE_WHEN_ABSENT = self._orig["enforce"]
        licensing._AUTO_REFRESH = self._orig["auto"]
        licensing._REFRESH_ATTEMPTED = self._orig["attempted"]
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, text):
        import io
        with io.open(self.cert_path, "w", encoding="utf-8") as fh:
            fh.write(text)

    # --- absence: the gate this suite exists to guard ----------------

    def test_absent_file_blocks_when_enforced(self):
        licensing._ENFORCE_WHEN_ABSENT = True
        self.assertFalse(os.path.exists(self.cert_path))
        self.assertRaises(licensing.LicenseError, licensing.check, "auto_tag")

    def test_absent_file_permissive_in_grace_mode(self):
        licensing._ENFORCE_WHEN_ABSENT = False
        self.assertTrue(licensing.check("auto_tag"))

    # --- present, valid file -----------------------------------------

    def test_valid_file_licensed_tool_passes(self):
        self._write(_machine_file(_future()))
        self.assertTrue(licensing.check("auto_tag"))

    def test_about_always_allowed_for_valid_seat(self):
        self._write(_machine_file(_future()))
        self.assertTrue(licensing.check("about"))

    def test_tool_outside_policy_returns_false(self):
        # Valid seat, but the Standard policy doesn't list this tool:
        # check() returns False rather than raising (distinct from infra
        # failure - see the LicenseError docstring).
        self._write(_machine_file(_future()))
        self.assertFalse(licensing.check("nonexistent_tool"))

    # --- present, invalid file -> LicenseError -----------------------

    def test_expired_file_raises(self):
        self._write(_machine_file(_past()))
        self.assertRaises(licensing.LicenseError, licensing.check, "auto_tag")

    def test_fingerprint_mismatch_raises(self):
        self._write(_machine_file(_future(), fingerprint="OTHER"))
        self.assertRaises(licensing.LicenseError, licensing.check, "auto_tag")

    def test_bad_signature_raises(self):
        licensing._crypto.verify = lambda pub, msg, sig: False
        self._write(_machine_file(_future()))
        self.assertRaises(licensing.LicenseError, licensing.check, "auto_tag")

    def test_corrupt_file_raises(self):
        self._write("this is not a license file")
        self.assertRaises(licensing.LicenseError, licensing.check, "auto_tag")


if __name__ == "__main__":
    unittest.main()
