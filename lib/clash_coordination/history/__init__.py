# -*- coding: utf-8 -*-
"""History snapshots - inert in V1, hooks for V2 trend tracking.

Every coordination run writes a weekly_snapshot.json keyed by date
and project. V2 will ingest these into SQLite (or ACC Issues) and
render trend charts of new/resolved clash counts over time. V1 just
writes the file; nothing reads it yet.

The snapshot format is documented in snapshots.py - schema_version
on every snapshot so the V2 ingester can reject mismatched formats
loudly instead of silently mis-reading.
"""
