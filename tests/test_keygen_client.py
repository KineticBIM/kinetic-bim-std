# -*- coding: utf-8 -*-
"""Tests for bim_core.keygen_client driven by an injected mock transport.

No network: the fake transport records each request and returns scripted
(status, body) pairs. The key security guard here is that validate-key
carries NO Authorization header while the machine actions carry
"Authorization: License <key>".
"""

import os
import sys
import json
import tempfile
import unittest

# Redirect the licensing logger's base dir to a temp folder so non-2xx
# responses logged during these tests don't pollute the real
# %LOCALAPPDATA%\KineticBIM\logs.
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="kbim-test-")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "lib"))

from bim_core.keygen_client import KeygenClient, KeygenError   # noqa: E402


class FakeTransport(object):
    def __init__(self):
        self.calls = []
        self.responses = []

    def queue(self, status, body):
        self.responses.append((status, body if isinstance(body, str)
                               else json.dumps(body)))

    def __call__(self, method, url, headers, body):
        self.calls.append({"method": method, "url": url,
                           "headers": headers, "body": body})
        return self.responses.pop(0)

    @property
    def last(self):
        return self.calls[-1]


def _client(transport):
    return KeygenClient(account_id="testacct", transport=transport)


class ValidateKeyTest(unittest.TestCase):

    def setUp(self):
        self.t = FakeTransport()
        self.c = _client(self.t)

    def test_unauthenticated_and_body_shape(self):
        self.t.queue(200, {"meta": {"valid": False, "code": "NO_MACHINE",
                                    "detail": "d"},
                           "data": {"id": "LIC"}})
        result = self.c.validate_key("KEY", "FP")

        call = self.t.last
        self.assertEqual(call["method"], "POST")
        self.assertTrue(call["url"].endswith(
            "/accounts/testacct/licenses/actions/validate-key"))
        # SECURITY: validate-key must never carry the license key as auth.
        self.assertNotIn("Authorization", call["headers"])
        self.assertEqual(call["headers"]["Content-Type"],
                         "application/vnd.api+json")
        body = json.loads(call["body"])
        self.assertEqual(body["meta"]["key"], "KEY")
        self.assertEqual(body["meta"]["scope"]["fingerprint"], "FP")

        self.assertFalse(result.valid)
        self.assertEqual(result.code, "NO_MACHINE")
        self.assertEqual(result.license_id, "LIC")
        self.assertTrue(result.needs_activation())

    def test_valid_code(self):
        self.t.queue(200, {"meta": {"valid": True, "code": "VALID"},
                           "data": {"id": "LIC"}})
        result = self.c.validate_key("KEY", "FP")
        self.assertTrue(result.valid)
        self.assertFalse(result.needs_activation())

    def test_hard_error_without_meta_raises(self):
        self.t.queue(500, {"errors": [{"code": "INTERNAL", "detail": "boom"}]})
        self.assertRaises(KeygenError, self.c.validate_key, "KEY", "FP")


class ActivateMachineTest(unittest.TestCase):

    def setUp(self):
        self.t = FakeTransport()
        self.c = _client(self.t)

    def test_body_auth_and_id(self):
        self.t.queue(201, {"data": {"id": "MID"}})
        mid = self.c.activate_machine("KEY", "LIC", "FP", "PC1", "Windows")

        call = self.t.last
        self.assertEqual(call["method"], "POST")
        self.assertTrue(call["url"].endswith("/accounts/testacct/machines"))
        self.assertEqual(call["headers"]["Authorization"], "License KEY")
        body = json.loads(call["body"])
        self.assertEqual(body["data"]["type"], "machines")
        self.assertEqual(body["data"]["attributes"]["fingerprint"], "FP")
        self.assertEqual(
            body["data"]["relationships"]["license"]["data"]["id"], "LIC")
        self.assertEqual(mid, "MID")

    def test_limit_error_carries_code(self):
        self.t.queue(422, {"errors": [{"code": "MACHINE_LIMIT_EXCEEDED",
                                       "detail": "too many"}]})
        try:
            self.c.activate_machine("KEY", "LIC", "FP", "PC1", "Windows")
            self.fail("expected KeygenError")
        except KeygenError as exc:
            self.assertEqual(exc.code, "MACHINE_LIMIT_EXCEEDED")
            self.assertEqual(exc.status, 422)


class CheckOutTest(unittest.TestCase):

    def setUp(self):
        self.t = FakeTransport()
        self.c = _client(self.t)

    def test_query_auth_and_certificate(self):
        self.t.queue(200, {"data": {"attributes": {"certificate": "PEM"}}})
        cert = self.c.check_out("KEY", "MID", ttl=1209600)

        call = self.t.last
        self.assertEqual(call["method"], "POST")
        self.assertIn("/machines/MID/actions/check-out", call["url"])
        self.assertIn("ttl=1209600", call["url"])
        self.assertIn("include=license.policy", call["url"])
        self.assertEqual(call["headers"]["Authorization"], "License KEY")
        self.assertEqual(cert, "PEM")

    def test_missing_certificate_raises(self):
        self.t.queue(200, {"data": {"attributes": {}}})
        self.assertRaises(KeygenError, self.c.check_out, "KEY", "MID")


class FindAndDeactivateTest(unittest.TestCase):

    def setUp(self):
        self.t = FakeTransport()
        self.c = _client(self.t)

    def test_find_machine_returns_id(self):
        self.t.queue(200, {"data": [{"id": "MID"}]})
        self.assertEqual(self.c.find_machine("KEY", "FP"), "MID")
        self.assertIn("fingerprint=FP", self.t.last["url"])
        self.assertEqual(self.t.last["headers"]["Authorization"], "License KEY")

    def test_find_machine_none_when_empty(self):
        self.t.queue(200, {"data": []})
        self.assertIsNone(self.c.find_machine("KEY", "FP"))

    def test_deactivate_deletes(self):
        self.t.queue(204, "")
        self.c.deactivate("KEY", "MID")
        call = self.t.last
        self.assertEqual(call["method"], "DELETE")
        self.assertTrue(call["url"].endswith("/machines/MID"))
        self.assertEqual(call["headers"]["Authorization"], "License KEY")

    def test_deactivate_error_raises(self):
        self.t.queue(404, {"errors": [{"code": "NOT_FOUND", "detail": "x"}]})
        self.assertRaises(KeygenError, self.c.deactivate, "KEY", "MID")


if __name__ == "__main__":
    unittest.main()
