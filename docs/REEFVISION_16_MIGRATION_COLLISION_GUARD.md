# ReefVision 1.6 — cross-track Alembic 0038 safety gate

## Verified conflict (2026-10-23)

`develop/reefvision-1.6` contains `0038_review_queue_item_events.py` (`0037` → `0038`) and creates `review_queue_item_events`.
`develop/reefvision-1.1` contains `0038_scientific_data.py` (`0037` → `0038`) and creates `scientific_records` plus `environmental_cache_entries`.
Both are independent unmerged branches. Alembic stores revision IDs, not migration-file content. An upgrade from one branch to the other could silently skip required tables.

## Guarded behavior

Before **online** Alembic migration, `assert_compatible_revision_0038` checks an existing database's revision. For `0038`, the 1.6 branch requires the review-events table with expected columns and rejects either scientific table. It does not write to or stamp the database. Fresh databases and non-0038 revisions are unchanged. Offline SQL generation is not protected by this database introspection.

This is a **temporary fail-closed guard**, not a resolution. Do not renumber an already-applied `0038`, stamp an installation, merge the branches, or delete a conflicting table. Coordinate a reviewed, backed-up, data-preserving migration path for both existing lineages before integration, then replace the guard with compatible upgrade tests. The 1.1 branch has its own responsibility to protect its existing installations.

## 2026-10-25 hardening: concurrent review revision heads

The read-only guard also rejects databases that simultaneously report two or
more Alembic heads when any head is a review-lineage revision `0038`, `0039`, or `0040`.
Previously, selecting the highest marker could conceal an additional
incompatible head. Rejection preserves the revision rows, scientific tables,
and original research assets; it does not attempt a repair or rewrite.
Parameterized SQLite regressions cover all three two-review-head combinations,
plus a review revision paired with an older or foreign scientific branch head.
The guard is read-only and intentionally rejects unrecognized multi-head states
until an explicit, backed-up migration reconciliation is approved.

The 0040 completion-event CHECK is still verified independently. This is a
narrow compatibility safeguard, **not** a reconciliation with the separate
1.1 scientific-data 0038. Exact-head CI and Windows upgrade acceptance must
pass before any release decision.

## Acceptance remaining

Run `pytest apps/api/reefvision/tests/test_migration_lineage_guard_16.py` and a real SQLite upgrade/downgrade/upgrade with representative data for **both** lineages on isolated backups. Confirm Windows packaged sidecar startup and error messaging. This guard alone does not make 1.6 release-ready.

## 2026-10-25 — Duplicate Alembic marker hardening

The 1.6 read-only guard now checks the **number of stored Alembic revision rows**, not only the number of distinct revision strings. Two identical `0038`, `0039` or `0040` rows previously collapsed into a one-element set, potentially allowing an ambiguous database state to pass the preflight. Duplicate rows now fail closed with both original marker values in the diagnostic; no revision rows, QC events, or research assets are rewritten. SQLite regressions cover all three duplicate pairs and assert preservation. The same increment corrects the exact Ruff formatting failure in `test_desktop_runtime_paths.py` from the preceding 17/20 CI run. Full exact-head CI and Windows migration/installer acceptance remain pending; this is not a migration reconciliation or release authorization.
