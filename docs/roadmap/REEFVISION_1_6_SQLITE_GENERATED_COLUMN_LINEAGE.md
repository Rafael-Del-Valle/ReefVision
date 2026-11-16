# 1.6 SQLite lineage: generated and hidden columns

The read-only `scripts/inspect_sqlite_lineage_16.py` diagnostic previously used
`PRAGMA table_info`, which intentionally omits generated and hidden columns.
Those columns can carry scientific unit conversions or derived metrics, and
their absence from a column inventory is misleading when reviewing the
independent 1.1/1.6 Alembic revision-0038 collision.

The inspector now retains the existing `columns` response for backwards
compatibility and adds `extended_columns` from `PRAGMA table_xinfo`.
The `hidden` field distinguishes ordinary (0), virtual-table hidden (1),
virtual generated (2), and stored generated (3) columns. SQLite's full
`CREATE TABLE` DDL remains part of the existing schema SHA-256 fingerprint.
Neither the fingerprint nor the column inventory proves applied migrations.

The regression tests cover a stored generated length conversion (mm to cm),
legacy column metadata compatibility, mandatory researcher review, and
database-byte preservation. No research record is recalculated, accepted,
repaired, or migrated by this inspection. Full repository pytest, lint/type,
cross-version migration acceptance, saved Workflow Builder regressions and
Windows installed-GUI/MSI testing remain release gates.

## 2026-11-16 — Canonical Alembic stamp parity in the standalone inspector

The separate read-only `scripts/inspect-alembic-lineage.py` preflight also
used SQLite `PRAGMA table_info` to decide whether `alembic_version` had
exactly one canonical column. Because `table_info` suppresses generated
columns, a malformed stamp with an extra virtual or stored generated column
could appear canonical even though the underlying schema differs.

The preflight now inspects `table_xinfo` and requires exactly one ordinary
`version_num` column with its existing text, NOT NULL and primary-key
constraints. It emits the pre-existing `unexpected_alembic_version_columns`
and `noncanonical_alembic_stamp_constraints` warnings on generated-column
forgeries, causing `--fail-on-warning` to reject them. Regression fixtures
include both generated-column kinds, a genuine single-column control,
unchanged QC/biological records, no leaked observation text, and strict CLI
exit status. This is read-only diagnostic parity, **not** authorization to
reconcile the independent 1.1/1.6 revision-0038 collision.

## 2026-11-16 — Desktop preflight parity for 1.6 QC audit tables

The desktop startup guard previously checked only that required columns were
present in the 0038 review-event table and the 0041 bulk-request table.
An extra ordinary column was tolerated, and SQLite generated VIRTUAL/STORED
columns could escape the ordinary SQLAlchemy column inventory entirely.
Neither is part of the exact append-only reviewer-audit migration contract.

The **read-only** `assert_compatible_revision_0038` guard now checks both
tables against their frozen column sets, using `PRAGMA table_xinfo` for SQLite.
It rejects unexpected ordinary columns, unexpected generated columns, and any
hidden-column flag before the application can perform migration writes.
No generated expression is evaluated, no QC action is approved, and no
researcher data is rewritten. Twelve file-backed parameterized regressions
cover legitimate 0038/0041 shapes and ordinary/VIRTUAL/STORED additions,
asserting two repeatable inspections, preserved reviewer/biological records,
privacy-safe errors, and byte-for-byte preservation of the SQLite database.

This is a stricter **1.6 lineage compatibility check**, not a migration
reconciliation. Both independent 1.1/1.6 Alembic revision-0038 histories,
saved Workflow Builder acceptance, complete backend/frontend/E2E CI, real
Windows MSI/CAB install-upgrade-rollback, and installed-GUI validation remain
mandatory release blockers until separately demonstrated.
