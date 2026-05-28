# -*- coding: utf-8 -*-
"""Reference Ed25519 implementation - TEST / DEV USE ONLY.

This is the canonical, public-domain reference implementation of
Ed25519 from the original paper / NaCl (RFC 8032 conformant). It is
deliberately small and readable, NOT fast or side-channel safe, and is
NEVER loaded by the shipped pyRevit extension. It exists only to:

    1. mint the synthetic license-file fixtures (tools/mint_license_fixture.py)
    2. act as the conformance oracle in the unit tests

Conformance is pinned against the RFC 8032 Section 7.1 known-answer
vectors in tests/test_ed25519_kat.py. Because this implementation and
the shipped BouncyCastle primitive both conform to RFC 8032, a fixture
that verifies here is guaranteed to verify under BouncyCastle in Revit.

Runs on CPython 3 (and Python 2). Not for production cryptography.
"""

import hashlib

b = 256
q = 2 ** 255 - 19                                       # field prime
l = 2 ** 252 + 27742317777372353535851937790883648493  # group order


def _h(m):
    return hashlib.sha512(m).digest()


def _inv(x):
    return pow(x, q - 2, q)


d = (-121665 * _inv(121666)) % q
I = pow(2, (q - 1) // 4, q)


def _xrecover(y):
    xx = (y * y - 1) * _inv(d * y * y + 1)
    x = pow(xx, (q + 3) // 8, q)
    if (x * x - xx) % q != 0:
        x = (x * I) % q
    if x % 2 != 0:
        x = q - x
    return x


By = (4 * _inv(5)) % q
Bx = _xrecover(By)
B = [Bx % q, By % q]


def _edwards(P, Q):
    x1, y1 = P[0], P[1]
    x2, y2 = Q[0], Q[1]
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + d * x1 * x2 * y1 * y2)
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - d * x1 * x2 * y1 * y2)
    return [x3 % q, y3 % q]


def _scalarmult(P, e):
    if e == 0:
        return [0, 1]
    Q = _scalarmult(P, e // 2)
    Q = _edwards(Q, Q)
    if e & 1:
        Q = _edwards(Q, P)
    return Q


def _bit(h, i):
    return (_byte(h, i // 8) >> (i % 8)) & 1


def _byte(h, i):
    # Index a bytes object as int under both Py2 and Py3.
    v = h[i]
    return v if isinstance(v, int) else ord(v)


def _encodeint(y):
    bits = [(y >> i) & 1 for i in range(b)]
    return bytes(bytearray(
        sum([bits[i * 8 + j] << j for j in range(8)]) for i in range(b // 8)))


def _encodepoint(P):
    x, y = P[0], P[1]
    bits = [(y >> i) & 1 for i in range(b - 1)] + [x & 1]
    return bytes(bytearray(
        sum([bits[i * 8 + j] << j for j in range(8)]) for i in range(b // 8)))


def _hint(m):
    h = _h(m)
    return sum(2 ** i * _bit(h, i) for i in range(2 * b))


def publickey(seed):
    """Derive the 32-byte public key from a 32-byte secret seed."""
    h = _h(seed)
    a = 2 ** (b - 2) + sum(2 ** i * _bit(h, i) for i in range(3, b - 2))
    return _encodepoint(_scalarmult(B, a))


def sign(message, seed, pubkey):
    """Return the 64-byte Ed25519 signature of message."""
    h = _h(seed)
    a = 2 ** (b - 2) + sum(2 ** i * _bit(h, i) for i in range(3, b - 2))
    prefix = bytes(bytearray(_byte(h, j) for j in range(b // 8, b // 4)))
    r = _hint(prefix + message)
    R = _scalarmult(B, r)
    S = (r + _hint(_encodepoint(R) + pubkey + message) * a) % l
    return _encodepoint(R) + _encodeint(S)


def _isoncurve(P):
    x, y = P[0], P[1]
    return (-x * x + y * y - 1 - d * x * x * y * y) % q == 0


def _decodeint(s):
    return sum(2 ** i * _bit(s, i) for i in range(0, b))


def _decodepoint(s):
    y = sum(2 ** i * _bit(s, i) for i in range(0, b - 1))
    x = _xrecover(y)
    if x & 1 != _bit(s, b - 1):
        x = q - x
    P = [x, y]
    if not _isoncurve(P):
        raise ValueError("decoding point that is not on curve")
    return P


def verify(signature, message, pubkey):
    """True iff signature is valid for message under pubkey."""
    if len(signature) != b // 4 or len(pubkey) != b // 8:
        return False
    try:
        R = _decodepoint(signature[0:b // 8])
        A = _decodepoint(pubkey)
        S = _decodeint(signature[b // 8:b // 4])
    except ValueError:
        return False
    h = _hint(_encodepoint(R) + pubkey + message)
    return _scalarmult(B, S) == _edwards(R, _scalarmult(A, h))
