# ReefVision 1.6 — installed SQLite reviewer-registry foreign-key acceptance

Track D / master issue #76. This note records an additional **release-blocking test**, not an accepted installer.

## Gap and contract

The 0041 migration declares `RESTRICT` links from bulk QC request records to their project and review queue. SQLite does not enforce declared foreign keys unless `PRAGMA foreign_keys=ON` is effective on the actual application connection. A migrated database could otherwise accept an orphaned manual-review request marker, weakening saved Workflow Builder provenance.

`test_real_0041_sqlite_enforces_reviewer_registry_foreign_keys` creates a disposable database through the real Alembic desktop migration runner, opens it with the real ReefVision engine, verifies foreign-key enforcement, attempts to insert an orphaned reviewer batch, and requires an integrity error and zero persisted registry records. This complements existing standalone/manual QC tests and executable saved `project_source -> qc_review_queue` Workflow Builder regression coverage; it does not authorize or verify annotations.

## Pooled-connection regression (2026-10-29)

`test_reused_desktop_sqlite_connection_restores_foreign_key_enforcement`
uses the **real 0041 migrated schema**, disables foreign-key checks on a
returned local SQLAlchemy connection, and verifies that the next checkout
restores enforcement. It then attempts an orphaned bulk-review insert and
requires an integrity error and no persisted review-request marker.
This extends the existing `test_sqlite_runtime_foreign_keys_16.py` coverage,
which already checks synthetic foreign-key tables and pooled PRAGMA recovery
but not an actual migrated reviewer-registry write after that recovery.

The previous exact-head CI (40902859597) failed Ruff SIM117/E501 in the
real-migration regression; the nested context managers and long SQL string
were corrected. Passing CI is still required on the updated head.

## Acceptance boundary

Run backend Ruff lint/format, this real-migration test, complete backend/frontend/E2E and saved-workflow regressions, and native Windows installed-MSI create/reopen/upgrade/rollback validation. The independent 1.1/1.6 revision-0038 collision remains unresolved; never stamp or rewrite an installed research database to bypass it. Do not treat a passing synthetic SQLite check as evidence that the installed Windows GUI works.

No pretrained weights, network services, asset mutation, version merge, or release are part of this change.
