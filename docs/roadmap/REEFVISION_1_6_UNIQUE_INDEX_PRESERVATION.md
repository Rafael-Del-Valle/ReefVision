# ReefVision 1.6: preserving scientific uniqueness during offline migration checks

The 1.1/1.6 Alembic-0038 histories have **not** been independently reconciled. This gate is read-only and requires researcher approval regardless of result; it neither upgrades a project nor authorizes an installer or release.

## Integrity gap

A database rewrite can retain every existing observation and workflow record, including foreign-key and column metadata, while dropping a `UNIQUE` constraint. Subsequent microscope counts, coral observations, QC decisions, or class-related records could then acquire duplicate logical keys without warning.

`scripts/verify-research-row-preservation-16.py` now compares SQLite unique-index contracts for every protected table. Using `PRAGMA index_list` and `index_xinfo`, it checks whether all baseline contracts survive: uniqueness, index origin, key column/expression shape, key order, collation and direction. For expression/partial indexes it conservatively checks their SQL definitions to preserve expression semantics and filtering predicates. Additional unique indexes are allowed. Index names are ignored for ordinary column-only indexes.

A lost or weakened contract produces `changed_unique_index_contract` and `HOLD`. Private SQL predicates, biological IDs, and observations are **not printed**. Both database copies and research assets remain untouched.

## Evidence and limits

Database-backed regressions exercise an identical ordinary unique index (PASS preservation-only), dropped uniqueness, replacement by a non-unique index, collation drift, changed partial predicates, expression changes, and an additive unique index. All cases assert `upgrade_authorized=false`, explicit researcher approval, preservation of original database bytes, and suppression of private identifiers.

This is a conservative preservation check, not a complete formal comparison of all CHECK constraints, triggers, collation implementations, or applications of arbitrary SQL expressions. Rebuilt indexes with semantically equivalent but textually different partial predicates or index-expression definitions may require manual review. Do not weaken the gate or label a result a safe upgrade based solely on existing row hashes.

Workflow Builder's existing typed/saved QC review flows and approval barriers are unchanged; this offline database diagnostic is not a workflow execution node. Full CI, 1.1/1.6 migration resolution, independent biological and saved-workflow acceptance, real Windows MSI/CAB clean-install/upgrade/rollback, installed GUI testing, and researcher signoff are separate release gates.
