# -*- coding: utf-8 -*-
"""Coordination-aware logger.

bim_core.log.get_logger writes into the *Revit project* folder. This
tool's natural log location is the coordination output folder
instead, since coordination runs operate on the federated model
which often lives separately from any one Revit project. coord_log
mirrors the bim_core API but takes an explicit output_folder.
"""
