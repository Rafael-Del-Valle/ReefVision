# 1.6 offline scientific constraint-conflict preservation

**Status: development safeguard, release HOLD.** Before a native Windows upgrade or
integration of 1.1 and 1.6 migration histories, inspect **independent offline
SQLite copies**. No migration, schema repair, user database write, automatic
researcher approval, or Workflow Builder node is introduced here.

SQLite exposes primary keys, NOT NULL constraints and unique indexes through
`PRAGMA table_xinfo` and `PRAGMA index_list`, but those APIs omit the
`ON CONFLICT` behavior declared on original constraints. Two databases may have
identical saved observations and index metadata even though future duplicate
biological sample imports differ: default ABORT rejects the insert, IGNORE
silently skips it, and REPLACE deletes the conflicting row before inserting
the new record. Changing a reviewer or scientific identifier policy can
therefore invalidate future provenance without changing historical checksums.

The 1.6 read-only preservation verifier now retains original column-level
policy clauses, original table-level PRIMARY KEY/UNIQUE/CHECK constraint
identities and the complete conflict-clause order. It reports
`changed_constraint_conflict_policy` with mandatory HOLD if any protected
existing rule is changed, removed, moved or reinterpreted. Added columns and
new default-policy constraints remain compatible; a newly explicit conflict
policy requires independent review, even when semantically redundant. Private
schema declarations, field identifiers, and original research values are
never printed in diagnostics.

Regressions exercise real SQLite inline and table-level UNIQUE/PRIMARY KEY,
NOT NULL, swapped policies on two unique fields, preserved policies with
additive columns, read-only bytes and explicit human approval. These are
**standalone offline migration preflight** checks, not a new biological
analysis; existing typed executable saved QC Workflow Builder, run lineage,
retry semantics and approval gates must still pass their separate CI tests.

**Outstanding release gates:** independent 1.1/1.6 Alembic revision 0038
reconciliation, complete exact-head backend/frontend/E2E, representative
biological and saved-workflow checks, real Windows MSI/CAB installation,
upgrade/rollback, installed GUI, and explicit researcher authorization.

## Native Windows/Linux regression metadata

SQLite can assign different `sqlite_autoindex` names and `PRAGMA index_list`
positions to identical PRIMARY KEY and UNIQUE key definitions when their
`ON CONFLICT` policies differ. The regression therefore compares effective
index contracts (uniqueness, origin, partial status, indexed key order,
collation, and sort direction) using `PRAGMA index_xinfo`, not generated names
or enumeration order. This prevents a false test failure without weakening the
verifier's explicit conflict-policy HOLD decision. The same tests execute on
Linux and native Windows.
