# -*- coding: utf-8 -*-
"""Pin the reference Ed25519 implementation to the RFC 8032 Section 7.1
known-answer vectors.

This is the conformance anchor for the whole licensing test suite: it
proves tests/_ed25519_ref.py is a correct RFC 8032 implementation, which
in turn guarantees that any fixture it signs will verify under the
shipped BouncyCastle primitive in Revit (also RFC 8032 conformant).
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import _ed25519_ref as ed  # noqa: E402


def _hex(s):
    return bytes(bytearray.fromhex(s))


# (seed, public key, message, signature) from RFC 8032 7.1
VECTORS = [
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
     "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb88"
     "21590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
     "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac"
     "1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
]


class Ed25519KatTest(unittest.TestCase):

    def test_public_key_derivation(self):
        for seed_hex, pk_hex, _, _ in VECTORS:
            self.assertEqual(ed.publickey(_hex(seed_hex)), _hex(pk_hex))

    def test_signature_generation(self):
        for seed_hex, pk_hex, msg_hex, sig_hex in VECTORS:
            sig = ed.sign(_hex(msg_hex), _hex(seed_hex), _hex(pk_hex))
            self.assertEqual(sig, _hex(sig_hex))

    def test_verify_accepts_valid(self):
        for _, pk_hex, msg_hex, sig_hex in VECTORS:
            self.assertTrue(
                ed.verify(_hex(sig_hex), _hex(msg_hex), _hex(pk_hex)))

    def test_verify_rejects_tampered_message(self):
        _, pk_hex, _, sig_hex = VECTORS[1]
        self.assertFalse(
            ed.verify(_hex(sig_hex), b"\x73", _hex(pk_hex)))


if __name__ == "__main__":
    unittest.main()
