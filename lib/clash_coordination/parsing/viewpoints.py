# -*- coding: utf-8 -*-
"""Parse Navisworks viewpoints XML.

IronPython 2.7 / CPython 3 compatible.
"""

from __future__ import print_function, division, absolute_import

import os
from xml.etree import ElementTree as ET

from clash_coordination.parsing.clash_detective import (
    _attr, _tag, _children_by_tag,
)


class ViewpointEntry(object):
    def __init__(self, name="", folder_path="", guid=None, note=None):
        self.name = name
        self.folder_path = folder_path
        self.guid = guid
        self.note = note


def _walk(el, folder_path, out):
    for child in el:
        tag = _tag(child).lower()
        if tag in ("viewfolder", "folder"):
            name = _attr(child, "name") or ""
            sub = folder_path + " > " + name if folder_path else name
            _walk(child, sub, out)
        elif tag in ("view", "viewpoint"):
            out.append(ViewpointEntry(
                name=_attr(child, "name") or "",
                folder_path=folder_path,
                guid=_attr(child, "guid"),
                note=_attr(child, "comment", "note"),
            ))


def parse_viewpoints(xml_source):
    """Return a flat list of ViewpointEntry from a viewpoints XML.

    `xml_source` is a path, a parsed root, or a string of XML.
    """
    if isinstance(xml_source, ET.Element):
        root = xml_source
    elif hasattr(xml_source, "read"):
        root = ET.parse(xml_source).getroot()
    elif isinstance(xml_source, str) and os.path.isfile(xml_source):
        root = ET.parse(xml_source).getroot()
    else:
        root = ET.fromstring(xml_source)

    # Root may itself be the viewpoint container, or wrap it in
    # <exchange> / <viewpoints>.
    container = root
    inner = None
    for tag in ("viewpoints", "savedviewpoints"):
        for child in root:
            if _tag(child).lower() == tag:
                inner = child
                break
        if inner is not None:
            container = inner
            break

    out = []
    _walk(container, "", out)
    return out
