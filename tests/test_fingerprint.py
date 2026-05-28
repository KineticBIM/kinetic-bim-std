# -*- coding: utf-8 -*-
"""Tests for bim_core.fingerprint.compute - the seamed, pure path.

Live collection (WMI / NetworkInformation / registry) needs the CLR and
is only exercised in Revit; here we inject fixed factor values to assert
determinism, separator-insensitivity, factor sensitivity, and the
empty-anchor guard.
"""

import os
import sys
import json
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "lib"))

from bim_core import fingerprint            # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures")


class FingerprintTest(unittest.TestCase):

    def setUp(self):
        with open(os.path.join(FIXTURES, "expected.json")) as fh:
            self.expected = json.load(fh)

    def test_matches_fixture(self):
        fp = fingerprint.compute(
            uuid=self.expected["uuid"],
            sid=self.expected["sid"],
            mac=self.expected["mac"])
        self.assertEqual(fp, self.expected["fingerprint"])

    def test_deterministic(self):
        a = fingerprint.compute(uuid="U", sid="S", mac="M")
        b = fingerprint.compute(uuid="U", sid="S", mac="M")
        self.assertEqual(a, b)

    def test_separator_insensitive(self):
        base = fingerprint.compute(
            uuid="4C4C4544", sid="S-1-5-21", mac="AABBCCDDEEFF")
        spaced = fingerprint.compute(
            uuid="4c4c4544", sid="s-1-5-21", mac="AA:BB:CC:DD:EE:FF")
        dashed = fingerprint.compute(
            uuid="{4C4C4544}", sid="S-1-5-21", mac="aa-bb-cc-dd-ee-ff")
        self.assertEqual(base, spaced)
        self.assertEqual(base, dashed)

    def test_factor_sensitivity(self):
        base = fingerprint.compute(uuid="U", sid="S", mac="M")
        self.assertNotEqual(base, fingerprint.compute(uuid="X", sid="S", mac="M"))
        self.assertNotEqual(base, fingerprint.compute(uuid="U", sid="X", mac="M"))
        self.assertNotEqual(base, fingerprint.compute(uuid="U", sid="S", mac="X"))

    def test_empty_uuid_raises(self):
        self.assertRaises(
            RuntimeError, fingerprint.compute, "", "S", "M")

    def test_whitespace_uuid_raises(self):
        self.assertRaises(
            RuntimeError, fingerprint.compute, "   ", "S", "M")


if __name__ == "__main__":
    unittest.main()
