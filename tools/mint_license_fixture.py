# -*- coding: utf-8 -*-
"""Mint the synthetic Keygen machine-file fixtures used by the license
unit tests. DEV TOOL - run with CPython 3, output is committed.

    python tools/mint_license_fixture.py

Produces under tests/fixtures/:
    machine.lic       - a synthetic, Ed25519-signed Keygen machine file
    public_key.hex    - the DEV account public key (paste into
                        bim_core.licensing._ACCOUNT_PUBLIC_KEY_HEX)
    expected.json     - the known factor values + derived fingerprint
                        and validity window the tests assert against

The signing key is a FIXED dev seed so the fixtures and public key are
reproducible across re-runs. It is NOT the real Keygen account key -
that gets swapped in during the online activation follow-up. Signing
uses the RFC 8032 reference implementation (tests/_ed25519_ref.py),
self-checked against the spec's known-answer vectors before minting, so
the fixtures are guaranteed RFC-conformant (and thus BouncyCastle will
accept them in Revit).
"""

import os
import sys
import json
import base64
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, os.pardir))
sys.path.insert(0, os.path.join(ROOT, "tests"))   # _ed25519_ref
sys.path.insert(0, os.path.join(ROOT, "lib"))     # bim_core

import _ed25519_ref as ed                          # noqa: E402
from bim_core import fingerprint                    # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures")

# Fixed DEV seed (clearly not a real key) for reproducible fixtures.
DEV_SEED = bytes(bytearray.fromhex(
    "00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff"))

# Known machine factors the tests pin against. SID is the machine SID
# form (no trailing -RID) that fingerprint._live_sid would yield.
UUID = "4C4C4544-0042-3010-8044-B4C04F503432"
SID = "S-1-5-21-1111111111-2222222222-3333333333"
MAC = "AABBCCDDEEFF"


def _rfc_self_check():
    """Refuse to mint unless the reference impl reproduces the RFC 8032
    known-answer vectors - guarantees conformance with BouncyCastle."""
    cases = [
        ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
         "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
         "",
         "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555f"
         "b8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
        ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
         "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
         "72",
         "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da08"
         "5ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ]
    for seed_hex, pk_hex, msg_hex, sig_hex in cases:
        seed = bytes(bytearray.fromhex(seed_hex))
        msg = bytes(bytearray.fromhex(msg_hex))
        pk = ed.publickey(seed)
        assert pk == bytes(bytearray.fromhex(pk_hex)), "KAT public key mismatch"
        sig = ed.sign(msg, seed, pk)
        assert sig == bytes(bytearray.fromhex(sig_hex)), "KAT signature mismatch"
        assert ed.verify(sig, msg, pk), "KAT verify failed"
    print("RFC 8032 self-check passed.")


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _pem_wrap(body_b64, width=64):
    lines = [body_b64[i:i + width] for i in range(0, len(body_b64), width)]
    return ("-----BEGIN MACHINE FILE-----\n"
            + "\n".join(lines)
            + "\n-----END MACHINE FILE-----\n")


def main():
    _rfc_self_check()
    if not os.path.isdir(FIXTURES):
        os.makedirs(FIXTURES)

    pubkey = ed.publickey(DEV_SEED)
    pubkey_hex = "".join("%02x" % _b(c) for c in pubkey)

    fp = fingerprint.compute(uuid=UUID, sid=SID, mac=MAC)

    now = datetime.datetime.utcnow()
    issued = now - datetime.timedelta(days=1)
    expiry = now + datetime.timedelta(days=365)

    dataset = {
        "data": {
            "type": "machines",
            "id": "11111111-2222-3333-4444-555555555555",
            "attributes": {"fingerprint": fp},
            "relationships": {
                "license": {"data": {"type": "licenses",
                                     "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}},
            },
        },
        "included": [
            {"type": "licenses",
             "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
             "attributes": {"name": "Seat - Kinetic BIM Standard"}},
            {"type": "policies",
             "id": "99999999-8888-7777-6666-555555555555",
             "attributes": {"name": "Standard"}},
        ],
        "meta": {
            "issued": _iso(issued),
            "expiry": _iso(expiry),
            "ttl": 31536000,
        },
    }

    enc = base64.b64encode(
        json.dumps(dataset).encode("utf-8")).decode("ascii")
    signing_message = ("machine/" + enc).encode("utf-8")
    sig = ed.sign(signing_message, DEV_SEED, pubkey)
    sig_b64 = base64.b64encode(sig).decode("ascii")

    outer = {"enc": enc, "sig": sig_b64, "alg": "base64+ed25519"}
    body = base64.b64encode(
        json.dumps(outer).encode("utf-8")).decode("ascii")
    machine_lic = _pem_wrap(body)

    expected = {
        "uuid": UUID, "sid": SID, "mac": MAC,
        "fingerprint": fp,
        "policy_name": "standard",
        "issued": _iso(issued),
        "expiry": _iso(expiry),
        "file_type": "machine",
        "alg": "base64+ed25519",
    }

    _write(os.path.join(FIXTURES, "machine.lic"), machine_lic)
    _write(os.path.join(FIXTURES, "public_key.hex"), pubkey_hex + "\n")
    _write(os.path.join(FIXTURES, "expected.json"),
           json.dumps(expected, indent=2) + "\n")

    print("Wrote fixtures to {0}".format(FIXTURES))
    print("")
    print("Public key hex (paste into licensing._ACCOUNT_PUBLIC_KEY_HEX):")
    print("    " + pubkey_hex)


def _b(c):
    return c if isinstance(c, int) else ord(c)


def _write(path, text):
    import io
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


if __name__ == "__main__":
    main()
