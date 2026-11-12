# ReefVision 1.6 — opt-in SQLite lineage integrity CLI gate

The existing `scripts/inspect_sqlite_lineage_16.py` is a **read-only evidence inspector**, not a migration tool or a migration-history classifier. The 1.1 and 1.6 Alembic revision `0038` collision remains unresolved.

## Use

```powershell
python scripts/inspect_sqlite_lineage_16.py "C:\\path\\to\\research-copy.sqlite" --fail-on-integrity-error
```

The default invocation remains backward-compatible and emits JSON without setting an error exit code for reported anomalies. The optional flag emits the **same full JSON report**, then exits **2** if SQLite `quick_check` is not exactly `["ok"]`, the foreign-key check fails or finds violations, or an existing Alembic version table cannot be read. A healthy database exits **0** even when its `0038` stamp is ambiguous: it still reports `classification: requires_researcher_review`. Missing Alembic tables are not interpreted as proof of a valid lineage.

This gate is intended for controlled *copies* of databases and automated acceptance scripts. It does not repair foreign keys, rewrite revision stamps, mutate research records, grant scientific verification, or authorize migration/merge/release. A SQLite `quick_check` is not a replacement for full domain-specific integrity checks. Keep the full JSON evidence and review it before any migration reconciliation.

Regression fixtures cover an orphaned QC foreign key, an ambiguous-but-structurally-healthy `0038` database, and malformed Alembic metadata, including unchanged database bytes. Full repository/Windows installer and saved Workflow Builder acceptance remain separate release gates.
