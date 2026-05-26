# -*- coding: utf-8 -*-
"""Federated model refresh.

refresher.py drives Navisworks via the navisworks/ COM layer to
refresh linked NWC/NWD references. validator.py checks that link
paths resolve on disk before the run starts so a missing model
fails loudly with a clear log entry instead of producing a silent
out-of-date clash report.
"""
