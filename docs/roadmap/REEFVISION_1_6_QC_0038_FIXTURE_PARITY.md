# ReefVision 1.6 — QC event migration fixture parity

**Status:** regression/CI-repair increment, not release acceptance (2026-11-12).

## Why this was needed

The exact predecessor [CI run 43354576983](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/43354576983) passed frontend but failed backend pytest: **17 failed, 1,796 passed and 32 skipped**. The failed positive startup/migration fixtures had an original-0038 `review_queue_item_events` table with no declared parent foreign keys or history indexes. The production fail-closed migration guard now verifies those original audit-history contracts and correctly rejected the synthetically incomplete fixtures. Loosening that guard would permit restored/revised QC histories with lost relationships.

## Correction

- Reusable **test-only** `review_lineage_fixture_16.py` declares the three original `ON DELETE CASCADE` relationships, seeds minimal consistent parent records and constructs both ordered, nonunique `(item_id, created_at)` and `(queue_id, created_at)` audit indexes.
- Corrected positive 0038–0041 startup, bulk-registry, provenance/default, event-ID uniqueness, named CHECK, event-value-case and nullable-attribution regression fixtures. Intentionally broken constraints remain broken in each negative test.
- Updated sqlite3 desktop startup fixtures to preserve these historical relationships/indexes as well. Nothing on the production migration path is weakened or automatically rewritten.
- The shared fixture is SQLite-specific; no PostgreSQL or native Windows startup test passes are inferred from it.

## Verification and scientific boundary

A standalone SQLite/SQLAlchemy smoke check on 2026-11-12 established that the composed 0038 event schema has exactly the three intended cascading relationships, two ascending nonunique indexes, and zero `PRAGMA foreign_key_check` violations for valid seeded parent and event rows. This smoke test is **not** a substitute for the committed pytest, lint or installed-GUI gates. Saved `qc_review_queue` Workflow Builder executions and mandatory researcher review were not changed.

The exact-head CI and Windows installed-GUI/upgrade/rollback remain required. The **independent 1.1 vs 1.6 Alembic revision 0038 collision** is not repaired by these synthetic test fixtures; a reviewed data-preserving reconciliation and migration compatibility proof are required before version acceptance. Real biological study data, QC provenance, snapshots and model weights are untouched.
