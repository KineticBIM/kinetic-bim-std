# -*- coding: utf-8 -*-
"""Ed25519 signature verification primitive (BouncyCastle-backed).

The .NET Framework that pyRevit's IronPython engine runs on has no
native Ed25519, so verification goes through the bundled BouncyCastle
managed assembly (lib/bin/BouncyCastle.Crypto.dll - see bin/NOTICE.txt).
This is the ONLY module in bim_core that touches the CLR for crypto;
everything else (envelope parsing, expiry, fingerprint comparison) is
pure stdlib so it stays unit-testable under CPython.

Single entry point:

    verify(public_key_hex, message_bytes, signature_bytes) -> bool

A completed verification returns True/False. If the BouncyCastle
assembly cannot be loaded at all, _load() raises - the licensing layer
catches that and surfaces a friendly "verification unavailable" dialog
rather than a raw stack trace. (Kept free of any bim_core.licensing
import to avoid a circular dependency; licensing wraps the exception.)
"""

import os
import binascii


_DLL_NAME = "BouncyCastle.Crypto.dll"

# Populated lazily by _load(): (Ed25519PublicKeyParameters, Ed25519Signer)
_TYPES = None


def _dll_path():
    """Absolute path to the bundled DLL, resolved from this file's
    location: lib/bim_core/_crypto.py -> lib/bin/<dll>."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, os.pardir, "bin", _DLL_NAME))


def _load():
    """Load BouncyCastle and return (Ed25519PublicKeyParameters,
    Ed25519Signer). Raises on failure (missing DLL, blocked assembly,
    CLR unavailable) - treated as an infrastructure error upstream."""
    global _TYPES
    if _TYPES is not None:
        return _TYPES

    import clr  # type: ignore
    path = _dll_path()
    if not os.path.isfile(path):
        raise IOError("BouncyCastle assembly not found at {0}".format(path))
    clr.AddReferenceToFileAndPath(path)

    from Org.BouncyCastle.Crypto.Parameters import (  # type: ignore
        Ed25519PublicKeyParameters,
    )
    from Org.BouncyCastle.Crypto.Signers import Ed25519Signer  # type: ignore

    _TYPES = (Ed25519PublicKeyParameters, Ed25519Signer)
    return _TYPES


def _to_dotnet_bytes(data):
    """Convert python bytes / bytearray / str into a .NET byte[].

    Handles both runtimes: under IronPython 2.7 base64/hex decode and
    str.encode yield 8-bit `str` (iterate -> 1-char str -> ord); under
    CPython they yield `bytes`/`bytearray` (iterate -> int).
    """
    from System import Array, Byte  # type: ignore
    if isinstance(data, bytearray):
        ints = [b for b in data]
    elif isinstance(data, bytes):
        ints = [b if isinstance(b, int) else ord(b) for b in data]
    else:
        ints = [ord(c) for c in data]
    return Array[Byte](ints)


def verify(public_key_hex, message_bytes, signature_bytes):
    """Verify an Ed25519 signature.

    Args:
        public_key_hex: account public key as a hex string.
        message_bytes:  the exact signed bytes (e.g. b"machine/" + enc).
        signature_bytes: raw signature bytes (base64-decoded).

    Returns True/False. Raises (infra error) only when the BouncyCastle
    primitive itself cannot be loaded; a malformed key/signature that
    BouncyCastle rejects returns False, not an exception.
    """
    Ed25519PublicKeyParameters, Ed25519Signer = _load()
    try:
        key_bytes = _to_dotnet_bytes(binascii.unhexlify(public_key_hex))
        key = Ed25519PublicKeyParameters(key_bytes, 0)
        signer = Ed25519Signer()
        signer.Init(False, key)
        msg = _to_dotnet_bytes(message_bytes)
        signer.BlockUpdate(msg, 0, msg.Length)
        return bool(signer.VerifySignature(_to_dotnet_bytes(signature_bytes)))
    except Exception:
        return False
