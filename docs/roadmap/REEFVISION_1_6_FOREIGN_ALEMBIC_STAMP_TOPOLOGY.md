# ReefVision 1.6 — foreign Alembic stamp topology gate

The read-only `scripts/inspect_sqlite_lineage_16.py` diagnostic now
requires an existing `alembic_version` **table** to expose exactly the
`version_num` column (including SQLite hidden/generated columns) before its
stamp can pass the optional `--fail-on-integrity-error` acceptance gate.

A valid-looking revision in a foreign or partially migrated table is not
evidence of an applicable migration lineage. Additional or reordered columns
produce `alembic_stamp_validation_error:
unexpected_alembic_version_columns` and exit status 2 when the gate is
enabled. Without the gate, diagnostic JSON is still emitted and the database
remains read-only. This never authorizes an upgrade or resolves the independent
1.1/1.6 revision-0038 collision.

Regression:
`scripts/tests/test_inspect_sqlite_lineage_stamp_topology_16.py` covers a
canonical table and two foreign-column layouts, preservation of observation
bytes, privacy of biological values, and the mandatory researcher-review
classification.

**Outstanding acceptance:** run exact-head pytest, Ruff, type checks, complete
migration/Workflow Builder suites, and Windows installed-GUI/MSI acceptance
before any release-readiness claim. Do not modify applied migration history
without a reviewed, data-preserving reconciliation.
