# Optional Alembic column-constraint acceptance gate (1.6)

The read-only `scripts/inspect_sqlite_lineage_16.py` now reports `alembic_stamp_constraint_error` for an `alembic_version.version_num` column lacking the expected NOT NULL, single-column PRIMARY KEY, or ordinary (non-hidden) column topology.

Use `python scripts/inspect_sqlite_lineage_16.py current.sqlite --compare-to reference.sqlite --fail-on-noncanonical-stamp` for strict comparison acceptance. The command emits JSON evidence before returning exit status 2 when either database has a noncanonical column. The comparison report includes `schema_comparison.reference_integrity.alembic_stamp_constraint_error`. It does not modify databases or approve migration reconciliation.

This is intentionally **opt-in**: some legacy test or research databases have `CREATE TABLE alembic_version (version_num TEXT)`. They remain inspectable, and existing `--fail-on-integrity-error` behavior remains unchanged. A canonical-looking table does **not** establish that two revision identifiers have the same migration history. Continue using revision, schema, FK and integrity evidence, and require researcher review.

Regression: `tests/test_inspect_sqlite_lineage_16.py::test_opt_in_alembic_column_constraints_gate_is_read_only` exercises both primary/reference failure directions, legacy compatibility, confidential observations and byte preservation. Full repository CI, scientific acceptance, and Windows installed-GUI testing remain required.
