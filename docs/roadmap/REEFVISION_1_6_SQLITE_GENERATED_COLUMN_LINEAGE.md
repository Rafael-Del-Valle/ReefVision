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
