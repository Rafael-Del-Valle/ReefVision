# ReefVision 1.6 — opt-in SQLite lineage integrity CLI gate

The existing `scripts/inspect_sqlite_lineage_16.py` is a **read-only evidence inspector**, not a migration tool or a migration-history classifier. The 1.1 and 1.6 Alembic revision `0038` collision remains unresolved.

## Use

```powershell
python scripts/inspect_sqlite_lineage_16.py "C:\\path\\to\\research-copy.sqlite" --fail-on-integrity-error
```

The default invocation remains backward-compatible and emits JSON without setting an error exit code for reported anomalies. The optional flag emits the **same full JSON report**, then exits **2** if SQLite `quick_check` is not exactly `["ok"]`, the foreign-key check fails or finds violations, or an existing Alembic version table cannot be read. A healthy database exits **0** even when its `0038` stamp is ambiguous: it still reports `classification: requires_researcher_review`. Missing Alembic tables are not interpreted as proof of a valid lineage.

This gate is intended for controlled *copies* of databases and automated acceptance scripts. It does not repair foreign keys, rewrite revision stamps, mutate research records, grant scientific verification, or authorize migration/merge/release. A SQLite `quick_check` is not a replacement for full domain-specific integrity checks. Keep the full JSON evidence and review it before any migration reconciliation.

Regression fixtures cover an orphaned QC foreign key, an ambiguous-but-structurally-healthy `0038` database, and malformed Alembic metadata, including unchanged database bytes. Full repository/Windows installer and saved Workflow Builder acceptance remain separate release gates.

## Independent revision comparison evidence

With `--compare-to reference.sqlite`, the JSON includes the primary
`alembic_stamps` and `schema_comparison.reference_alembic_stamps` side by side,
plus `revision_markers_match`. This exposes the actual differing markers to a
researcher instead of reporting only a boolean. The reference values are read
from the independent database, never inferred from schema hashes. Even matching
markers and hashes do **not** establish compatible migration histories.
`--fail-on-revision-mismatch` exits 2 on mismatch while retaining the JSON
report; neither database is changed. No observation rows are included.

The integrity gate now evaluates both bounded full `integrity_check(100)`
and `quick_check`, FK evidence, and Alembic metadata for both inputs when
comparison is requested. This is diagnostic rather than scientific approval.

### Colliding Alembic revisions (1.6)

Run `python scripts/inspect_sqlite_lineage_16.py PRIMARY.sqlite --compare-to REFERENCE.sqlite --fail-on-lineage-collision` to exit with status 2 when **both** databases have the same single validated Alembic revision but their structural SQLite schema SHA-256 fingerprints differ. JSON evidence is emitted before the exit, and both databases are opened read-only. The flag requires `--compare-to`; it does not alter the existing schema-drift or revision-mismatch gates. Different revision markers with different schemas are **not** a collision under this narrowly defined gate; combine `--fail-on-schema-drift` and `--fail-on-revision-mismatch` when those independent conditions should also fail. Matching revision and schema fingerprints are not proof of migration equivalence or scientific-record consistency. Human reconciliation and the separate 1.1/1.6 revision-0038 collision remain unresolved. No database migration is performed.
