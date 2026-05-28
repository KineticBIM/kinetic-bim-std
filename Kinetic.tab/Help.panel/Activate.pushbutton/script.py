# -*- coding: utf-8 -*-
"""Activate / manage this workstation's Kinetic BIM license.

Normal click:
    - not activated -> prompt for the license key and activate
    - activated     -> show status (tier + expiry)

Shift-click: release this seat (deactivate), freeing it for another
workstation.

Deliberately NOT wrapped in licensing.require() - an unlicensed user
must be able to reach this button to activate.
"""

__title__   = "Activate\nLicense"
__author__  = "Kinetic BIM"
__doc__     = "Activate, inspect, or release this workstation's license."

from pyrevit import forms

from bim_core import activation

SUPPORT_EMAIL = "support@kineticbim.com"


def _status_line(status):
    if not status.get("activated"):
        return "Not activated on this workstation."
    tier = (status.get("policy_name") or "standard").capitalize()
    expiry = status.get("expiry")
    when = expiry.strftime("%Y-%m-%d") if expiry else "unknown"
    return "Licensed ({0}) - valid until {1}.".format(tier, when)


def _deactivate():
    if not forms.alert(
            "Release this workstation's seat?\n\n"
            "The tools will stop working here until you activate again. "
            "Use this when moving your seat to another machine.",
            title="Deactivate Kinetic BIM", yes=True, no=True):
        return
    outcome = activation.deactivate()
    forms.alert(outcome.message, title="Deactivate Kinetic BIM")


def _activate():
    key = forms.ask_for_string(
        default="",
        prompt="Enter your Kinetic BIM license key:",
        title="Activate Kinetic BIM")
    if not key:
        return
    outcome = activation.activate(key)
    forms.alert(outcome.message, title="Activate Kinetic BIM")


def main():
    status = activation.current_status()

    if __shiftclick__:  # noqa: F821 - injected by pyRevit
        if status.get("activated"):
            _deactivate()
        else:
            forms.alert("Nothing to deactivate - this workstation isn't "
                        "activated.", title="Deactivate Kinetic BIM")
        return

    if status.get("activated"):
        forms.alert(
            "\n".join([
                _status_line(status),
                "",
                "Shift-click this button to release the seat.",
                "Support: " + SUPPORT_EMAIL,
            ]),
            title="Kinetic BIM License")
        return

    _activate()


main()
