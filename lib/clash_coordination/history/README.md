# history/

Weekly coordination snapshots. **Inert in V1.**

Every run of the orchestrator writes one `weekly_snapshot.json` into
the dated coordination folder. The file captures the per-test clash
totals + per-clash status so a future ingester can compute
new-vs-resolved deltas week over week.

## V1

- `snapshots.py` writes `weekly_snapshot.json` next to the reports.
- Nothing reads these files yet.

## V2 (planned, not in this release)

- SQLite ingester in this folder (`store.py` etc.) consuming all the
  per-week JSONs under `<output_root>/`.
- Trend chart rendering in `reporting/trends.py`.
- ACC Issues sync (push new clashes as issues; pull resolution state
  back) — probably its own subpackage at that point.

## Snapshot format

See the docstring on `snapshots.write_snapshot` for the authoritative
spec. Always check the `schema_version` field before consuming.
