# -*- coding: utf-8 -*-
"""Composite workstation fingerprint for license/machine binding.

A seat is bound to one machine (Keygen License with maxMachines:1).
The offline core compares the fingerprint embedded in the signed
machine file against the one computed here; the online activation
follow-up will reuse this exact function to register the machine with
Keygen, so both sides MUST agree byte-for-byte.

The composite is three factors hashed together:

    1. Hardware UUID  - WMI Win32_ComputerSystemProduct.UUID
    2. Machine SID    - the S-1-5-21-X-Y-Z account-domain SID, with a
                        registry MachineGuid fallback
    3. Primary MAC    - lowest physical address among non-loopback,
                        non-tunnel adapters

Each factor is normalised (uppercased, separators stripped), joined
with "|", and SHA-256 hashed to a hex digest. Live collection needs
the CLR (WMI / NetworkInformation / registry) and only runs under
IronPython on Windows; compute() is seamed so tests inject fixed
factor values and never touch the machine.

current() caches the live result for the process lifetime so the gate
stays cheap when called at every tool launch.
"""

import re
import hashlib


_SEPARATORS = re.compile(r"[\s{}:.\-]")

_CACHED = None   # process-lifetime cache of the live composite fingerprint


def compute(uuid=None, sid=None, mac=None):
    """Return the hex SHA-256 fingerprint for the given factors.

    Any factor left as None is collected live from this machine. Tests
    pass all three explicitly for a deterministic, machine-independent
    result.

    Raises RuntimeError when the anchor factor (hardware UUID) cannot
    be obtained live - an empty fingerprint must never silently match.
    """
    uuid = _live_uuid() if uuid is None else uuid
    sid = _live_sid() if sid is None else sid
    mac = _live_mac() if mac is None else mac

    if not _normalize(uuid):
        raise RuntimeError("Could not read this workstation's hardware ID")

    composite = "|".join([_normalize(uuid), _normalize(sid), _normalize(mac)])
    return hashlib.sha256(composite.encode("utf-8")).hexdigest()


def current():
    """Live fingerprint for this workstation, cached per process."""
    global _CACHED
    if _CACHED is None:
        _CACHED = compute()
    return _CACHED


def _normalize(value):
    """Uppercase and strip separators so 'AA:BB' == 'aabb' and a UUID
    with or without braces/hyphens hashes identically."""
    if not value:
        return ""
    return _SEPARATORS.sub("", value).upper()


def _live_uuid():
    """Win32_ComputerSystemProduct.UUID via WMI. Empty string on failure."""
    try:
        import clr  # type: ignore
        clr.AddReference("System.Management")
        from System.Management import ManagementObjectSearcher  # type: ignore
        searcher = ManagementObjectSearcher(
            "SELECT UUID FROM Win32_ComputerSystemProduct")
        for obj in searcher.Get():
            value = obj["UUID"]
            if value:
                return str(value)
    except Exception:
        pass
    return ""


def _live_mac():
    """Lowest physical address among real (non-loopback, non-tunnel)
    network adapters. Sorting makes the choice deterministic regardless
    of adapter enumeration order. Empty string on failure."""
    try:
        import clr  # type: ignore
        clr.AddReference("System")
        from System.Net.NetworkInformation import (  # type: ignore
            NetworkInterface, NetworkInterfaceType,
        )
        macs = []
        for nic in NetworkInterface.GetAllNetworkInterfaces():
            nic_type = nic.NetworkInterfaceType
            if nic_type in (NetworkInterfaceType.Loopback,
                            NetworkInterfaceType.Tunnel):
                continue
            addr = nic.GetPhysicalAddress().ToString()
            if addr:
                macs.append(str(addr))
        if macs:
            macs.sort()
            return macs[0]
    except Exception:
        pass
    return ""


def _live_sid():
    """Machine (account-domain) SID, e.g. S-1-5-21-X-Y-Z.

    Derived by taking any local account's SID and stripping its trailing
    RID. Falls back to the registry MachineGuid when the WMI query is
    unavailable or slow to resolve. Empty string only if both fail.
    """
    try:
        import clr  # type: ignore
        clr.AddReference("System.Management")
        from System.Management import ManagementObjectSearcher  # type: ignore
        searcher = ManagementObjectSearcher(
            "SELECT SID FROM Win32_UserAccount WHERE LocalAccount=true")
        for obj in searcher.Get():
            sid = obj["SID"]
            if sid and str(sid).startswith("S-1-5-21-"):
                # Strip the trailing -<RID> to get the machine SID.
                return str(sid).rsplit("-", 1)[0]
    except Exception:
        pass
    return _machine_guid()


def _machine_guid():
    """HKLM\\SOFTWARE\\Microsoft\\Cryptography\\MachineGuid - a stable
    per-install identifier, used as the SID fallback. Empty on failure."""
    try:
        import clr  # type: ignore
        from Microsoft.Win32 import Registry  # type: ignore
        key = Registry.LocalMachine.OpenSubKey(
            r"SOFTWARE\Microsoft\Cryptography")
        if key is not None:
            value = key.GetValue("MachineGuid")
            if value:
                return str(value)
    except Exception:
        pass
    return ""
