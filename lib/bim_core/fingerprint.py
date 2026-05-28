# -*- coding: utf-8 -*-
"""Composite workstation fingerprint for license/machine binding.

A seat is bound to one machine (Keygen License with maxMachines:1).
The offline core compares the fingerprint embedded in the signed
machine file against the one computed here; the online activation
follow-up will reuse this exact function to register the machine with
Keygen, so both sides MUST agree byte-for-byte.

The composite is three slots hashed together:

    1. Anchor   - registry HKLM\\...\\Cryptography\\MachineGuid (stable,
                  unique), falling back to the hostname when the registry
                  isn't reachable. Always non-empty.
    2. (SID)    - intentionally blank: the account-domain SID needs WMI,
                  which is unsupported on Revit 2025's .NET (Core) runtime.
                  Kept as a slot so the layout is stable if restored later.
    3. Primary MAC - lowest physical address among non-loopback,
                  non-tunnel adapters.

Runtime note: Revit 2025's pyRevit runs IronPython on .NET (Core), not
.NET Framework, so System.Management (WMI) is unavailable and
Microsoft.Win32.Registry lives in its own assembly. The collectors are
written to work on that runtime; failures are logged to the licensing
log so a live "couldn't read hardware ID" can be diagnosed.

Each slot is normalised (uppercased, separators stripped), joined with
"|", and SHA-256 hashed to a hex digest. compute() is seamed so tests
inject fixed values and never touch the machine.

current() caches the live result for the process lifetime so the gate
stays cheap when called at every tool launch.
"""

import os
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
    """Anchor factor. Prefer the registry MachineGuid (stable + unique);
    fall back to the hostname, which is always present and needs no CLR.

    WMI is intentionally NOT used: under Revit 2025's .NET (Core) runtime
    System.Management raises "only supported for Windows desktop
    applications" (see the licensing log), so it can't be relied on."""
    mg = _machine_guid()
    if mg:
        return mg
    host = _hostname()
    if host:
        return host
    return ""


def _hostname():
    """Machine name - always available on Windows, no CLR needed."""
    name = os.environ.get("COMPUTERNAME")
    if name:
        return name
    try:
        import socket
        return socket.gethostname()
    except Exception as exc:
        _log_warn("hostname lookup failed: {0}".format(exc))
    return ""


def _live_mac():
    """Lowest physical address among real (non-loopback, non-tunnel)
    network adapters. Sorting makes the choice deterministic regardless
    of adapter enumeration order. Empty string on failure (logged)."""
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
    except Exception as exc:
        _log_warn("MAC lookup failed: {0}".format(exc))
    return ""


def _live_sid():
    """Second SID factor is unavailable under the .NET (Core) runtime
    (System.Management is unsupported there), so it is intentionally blank.
    The MachineGuid/hostname anchor plus the MAC already bind the seat.
    Kept as a slot so the composite layout stays stable if SID support is
    restored later."""
    return ""


def _machine_guid():
    """HKLM\\SOFTWARE\\Microsoft\\Cryptography\\MachineGuid - the preferred
    stable, unique anchor. References Microsoft.Win32.Registry explicitly so
    it resolves under both .NET Framework (mscorlib) and .NET (Core), where
    it lives in its own assembly. Empty on failure (logged)."""
    try:
        import clr  # type: ignore
        try:
            clr.AddReference("Microsoft.Win32.Registry")   # .NET (Core)
        except Exception:
            pass   # .NET Framework: Registry is already in mscorlib
        from Microsoft.Win32 import Registry  # type: ignore
        key = Registry.LocalMachine.OpenSubKey(
            r"SOFTWARE\Microsoft\Cryptography")
        if key is not None:
            value = key.GetValue("MachineGuid")
            if value:
                return str(value)
    except Exception as exc:
        _log_warn("MachineGuid lookup failed: {0}".format(exc))
    return ""


def _log_warn(message):
    """Log a collector failure to the licensing log; never raise."""
    try:
        from bim_core import log as log_module
        log_module.get_logger(tool_name="licensing").warning(
            "fingerprint: %s", message)
    except Exception:
        pass
