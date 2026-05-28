# -*- coding: utf-8 -*-
"""Tests for bim_core.activation - the online activation state machine.

Uses a scripted fake KeygenClient and a real FileStore rooted at a temp
directory (so the actual path / file IO is exercised; the DPAPI key
encryption falls back to its tagged-base64 path under CPython). The live
machine fingerprint is monkeypatched so no CLR/WMI is touched.
"""

import os
import sys
import json
import base64
import shutil
import tempfile
import datetime
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "lib"))

from bim_core import activation                       # noqa: E402
from bim_core import license_store                    # noqa: E402
from bim_core.keygen_client import ValidationResult, KeygenError  # noqa: E402


def _make_cert(expiry_dt, machine_id="MID"):
    """A parseable (not necessarily signature-valid) machine file with a
    given expiry and machine id. activation only parses it for expiry /
    machine id - signature verification is the offline core's job."""
    dataset = {
        "data": {"type": "machines", "id": machine_id,
                 "attributes": {"fingerprint": "FP"}},
        "included": [{"type": "policies", "attributes": {"name": "Standard"}}],
        "meta": {"expiry": expiry_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")},
    }
    enc = base64.b64encode(json.dumps(dataset).encode("utf-8")).decode("ascii")
    outer = {"enc": enc, "sig": "AA==", "alg": "base64+ed25519"}
    body = base64.b64encode(json.dumps(outer).encode("utf-8")).decode("ascii")
    lines = [body[i:i + 64] for i in range(0, len(body), 64)]
    return ("-----BEGIN MACHINE FILE-----\n" + "\n".join(lines)
            + "\n-----END MACHINE FILE-----\n")


class FakeClient(object):
    def __init__(self):
        self.validate_result = ValidationResult(False, "NO_MACHINE", "", "LIC")
        self.validate_exc = None
        self.activate_exc = None
        self.activate_id = "MID"
        self.checkout_exc = None
        self.checkout_cert = _make_cert(
            datetime.datetime.utcnow() + datetime.timedelta(days=14))
        self.find_id = "MID"
        self.calls = []

    def validate_key(self, key, fp):
        self.calls.append("validate")
        if self.validate_exc:
            raise self.validate_exc
        return self.validate_result

    def activate_machine(self, key, license_id, fp, name, platform):
        self.calls.append("activate")
        if self.activate_exc:
            raise self.activate_exc
        return self.activate_id

    def find_machine(self, key, fp):
        self.calls.append("find")
        return self.find_id

    def check_out(self, key, machine_id, ttl=None):
        self.calls.append("checkout")
        if self.checkout_exc:
            raise self.checkout_exc
        return self.checkout_cert

    def deactivate(self, key, machine_id):
        self.calls.append("deactivate")


class ActivationTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = license_store.FileStore(base_dir=self.tmp)
        self.client = FakeClient()
        self._orig_fp = activation.fingerprint.current
        activation.fingerprint.current = lambda: "FP"

    def tearDown(self):
        activation.fingerprint.current = self._orig_fp
        shutil.rmtree(self.tmp, ignore_errors=True)


class ActivateTest(ActivationTestBase):

    def test_fresh_activation_writes_cert_and_key(self):
        self.client.validate_result = ValidationResult(
            False, "NO_MACHINE", "", "LIC")
        outcome = activation.activate("KEY", self.client, self.store)
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.status, "activated")
        self.assertIn("activate", self.client.calls)
        self.assertIn("checkout", self.client.calls)
        self.assertEqual(self.store.read_certificate(), self.client.checkout_cert)
        self.assertEqual(self.store.read_key(), "KEY")

    def test_fingerprint_scope_mismatch_activates(self):
        self.client.validate_result = ValidationResult(
            False, "FINGERPRINT_SCOPE_MISMATCH", "", "LIC")
        outcome = activation.activate("KEY", self.client, self.store)
        self.assertTrue(outcome.ok)
        self.assertIn("activate", self.client.calls)

    def test_already_valid_uses_find_machine(self):
        self.client.validate_result = ValidationResult(True, "VALID", "", "LIC")
        outcome = activation.activate("KEY", self.client, self.store)
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.status, "already_active")
        self.assertIn("find", self.client.calls)
        self.assertNotIn("activate", self.client.calls)
        self.assertEqual(self.store.read_certificate(), self.client.checkout_cert)

    def test_expired_is_terminal_no_files(self):
        self.client.validate_result = ValidationResult(False, "EXPIRED", "", "LIC")
        outcome = activation.activate("KEY", self.client, self.store)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.status, "expired")
        self.assertIsNone(self.store.read_certificate())
        self.assertIsNone(self.store.read_key())

    def test_suspended_is_terminal(self):
        self.client.validate_result = ValidationResult(False, "SUSPENDED", "", "LIC")
        outcome = activation.activate("KEY", self.client, self.store)
        self.assertEqual(outcome.status, "suspended")

    def test_too_many_machines_is_seat_in_use(self):
        self.client.validate_result = ValidationResult(
            False, "TOO_MANY_MACHINES", "", "LIC")
        outcome = activation.activate("KEY", self.client, self.store)
        self.assertEqual(outcome.status, "seat_in_use")

    def test_unknown_key_is_invalid(self):
        self.client.validate_result = ValidationResult(False, "NOT_FOUND", "", None)
        outcome = activation.activate("KEY", self.client, self.store)
        self.assertEqual(outcome.status, "invalid_key")

    def test_empty_key_short_circuits(self):
        outcome = activation.activate("   ", self.client, self.store)
        self.assertEqual(outcome.status, "invalid_key")
        self.assertEqual(self.client.calls, [])

    def test_network_error_on_validate(self):
        self.client.validate_exc = KeygenError("boom", status=0)
        outcome = activation.activate("KEY", self.client, self.store)
        self.assertEqual(outcome.status, "network_error")

    def test_activate_limit_maps_to_seat_in_use(self):
        self.client.validate_result = ValidationResult(
            False, "NO_MACHINE", "", "LIC")
        self.client.activate_exc = KeygenError(
            "limit", code="MACHINE_LIMIT_EXCEEDED", status=422)
        outcome = activation.activate("KEY", self.client, self.store)
        self.assertEqual(outcome.status, "seat_in_use")
        self.assertIsNone(self.store.read_certificate())


class RefreshTest(ActivationTestBase):

    def test_no_file_no_refresh(self):
        self.assertFalse(activation.refresh_if_needed(self.client, self.store))
        self.assertNotIn("checkout", self.client.calls)

    def test_healthy_file_not_refreshed(self):
        self.store.write_certificate(_make_cert(
            datetime.datetime.utcnow() + datetime.timedelta(days=30)))
        self.store.write_key("KEY")
        self.assertFalse(activation.refresh_if_needed(self.client, self.store))
        self.assertNotIn("checkout", self.client.calls)

    def test_near_expiry_refreshes(self):
        self.store.write_certificate(_make_cert(
            datetime.datetime.utcnow() + datetime.timedelta(days=3)))
        self.store.write_key("KEY")
        fresh = _make_cert(
            datetime.datetime.utcnow() + datetime.timedelta(days=14))
        self.client.checkout_cert = fresh
        self.assertTrue(activation.refresh_if_needed(self.client, self.store))
        self.assertEqual(self.store.read_certificate(), fresh)

    def test_near_expiry_offline_keeps_old(self):
        old = _make_cert(datetime.datetime.utcnow() + datetime.timedelta(days=2))
        self.store.write_certificate(old)
        self.store.write_key("KEY")
        self.client.checkout_exc = KeygenError("offline", status=0)
        self.assertFalse(activation.refresh_if_needed(self.client, self.store))
        self.assertEqual(self.store.read_certificate(), old)

    def test_no_key_no_refresh(self):
        self.store.write_certificate(_make_cert(
            datetime.datetime.utcnow() + datetime.timedelta(days=2)))
        self.assertFalse(activation.refresh_if_needed(self.client, self.store))


class DeactivateTest(ActivationTestBase):

    def test_deactivates_and_clears(self):
        self.store.write_certificate(_make_cert(
            datetime.datetime.utcnow() + datetime.timedelta(days=14)))
        self.store.write_key("KEY")
        outcome = activation.deactivate(self.client, self.store)
        self.assertTrue(outcome.ok)
        self.assertIn("deactivate", self.client.calls)
        self.assertIsNone(self.store.read_certificate())
        self.assertIsNone(self.store.read_key())

    def test_network_error_keeps_files(self):
        self.store.write_certificate(_make_cert(
            datetime.datetime.utcnow() + datetime.timedelta(days=14)))
        self.store.write_key("KEY")

        def boom(key, machine_id):
            raise KeygenError("offline", status=0)
        self.client.deactivate = boom

        outcome = activation.deactivate(self.client, self.store)
        self.assertEqual(outcome.status, "network_error")
        self.assertIsNotNone(self.store.read_certificate())

    def test_nothing_to_deactivate_still_ok(self):
        outcome = activation.deactivate(self.client, self.store)
        self.assertTrue(outcome.ok)


class StatusTest(ActivationTestBase):

    def test_status_not_activated(self):
        status = activation.current_status(self.store)
        self.assertFalse(status["activated"])

    def test_status_activated(self):
        self.store.write_certificate(_make_cert(
            datetime.datetime.utcnow() + datetime.timedelta(days=10)))
        status = activation.current_status(self.store)
        self.assertTrue(status["activated"])
        self.assertEqual(status["policy_name"], "standard")
        self.assertIsNotNone(status["expiry"])


if __name__ == "__main__":
    unittest.main()
