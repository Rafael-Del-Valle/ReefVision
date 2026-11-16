# ReefVision 1.1 / 1.6 Alembic lineage collision — reconciliation contract

Status: **BLOCKED / design and acceptance checklist only**. This document is not a migration, an authorization to alter a research database, or proof of release readiness. Track D owns the 1.6 branch; integration must be coordinated with Tracks A/E under issue #76 before code is shared.

## Verified source-level collision (2026-11-11)

| Branch | Revision | Parent | Creates |
| --- | --- | --- | --- |
| `develop/reefvision-1.1` | `0038` (`0038_scientific_data.py`) | `0037` | `scientific_records`, `environmental_cache_entries` |
| `develop/reefvision-1.1` | `0039` (`0039_computed_metrics.py`) | `0038` | `computed_metric_definitions`, `computed_metric_results` |
| `develop/reefvision-1.6` | `0038` (`0038_review_queue_item_events.py`) | `0037` | `review_queue_item_events`, two history indexes |
| `develop/reefvision-1.6` | `0039` (`0039_review_queue_triage_event_types.py`) | `0038` | QC event-type changes |
| `develop/reefvision-1.6` | `0040` (`0040_review_queue_complete_event.py`) | `0039` | QC completion changes |
| `develop/reefvision-1.6` | `0041` (`0041_review_queue_bulk_request_registry.py`) | `0040` | `review_queue_bulk_requests` |

Both branches independently assign the same revision identifiers to different DDL. A version stamp alone cannot identify which schema was applied. **Do not** resolve by `alembic stamp`, renaming only the migration filename, auto-merging unmerged branches, or running a downgrade on populated research data.

## Safe integration design (requires review before implementation)

1. Retain both original migration files and recorded branch history as provenance. Choose unique *new* revision identifiers for a reviewed integrated migration graph; do not retroactively assert that a historical `0038` means the other branch's DDL ran.
2. On a **copy** of the database, classify actual schema and row evidence before any write: legacy `0037`; complete 1.1 scientific lineage; complete 1.6 QC lineage; already-combined compatible schema; partial/ambiguous/corrupt schema. Compare columns, FK delete policies, unique constraints, indexes, Alembic rows and representative content hashes, not just table presence.
3. Build explicit data-preserving forward paths for *each verified lineage*, with an atomic transaction or independently tested SQLite recovery strategy. Only create missing tables/constraints when classification proves they are absent and compatible. Preserve original row UUIDs, scientific payloads, review event order, QC client request IDs, Workflow Builder graph/run IDs, provenance hashes and foreign-key relationships.
4. Fail closed on ambiguous/mixed schemas, multiple Alembic heads, partial DDL, unexpected views or missing lineage metadata. Require an immutable backup, researcher approval and a documented recovery plan; no automatic stamp/drop/rebuild of user tables.
5. After integration, keep the 1.6 desktop `migration_lineage_guard.py` and `review_event_topology_16.py` protections until an independently reviewed compatibility replacement is tested. Do not relax them simply to allow a merge.

## Required executable acceptance matrix

- Fresh install from base and from `0037`, including no-data repeat startup.
- Populated 1.1 scientific-only at `0038` and `0039`: retain scientific records, cache entries, computed definitions/results and linked workflow runs.
- Populated 1.6 QC-only at each `0038`–`0041`: retain event IDs, client request idempotency, reviewer comments, assignments, completion, bulk-request registry, and saved executable `qc_review_queue` graphs/runs.
- Valid already-combined schema, if encountered: detect and preserve it without duplicate DDL.
- Negative cases: missing/duplicate/multiple stamps, mixed partial DDL, wrong foreign-key delete policies, altered indexes/unique constraints, orphaned links, interrupted migration and injected failure halfway through upgrade.
- For each positive case: compare pre/post exact rows, schema signatures, content hashes, FK integrity, no unexpected deletions, and **second-run idempotence**; validate a standalone QC action and a saved typed Workflow Builder execution with researcher review still required.
- On Windows: test MSI fresh install, upgrade and rollback against copied populated databases, followed by installed-GUI class visibility, review queue and saved-workflow acceptance. Never exercise migration experiments on the researcher's only database.

## Current evidence boundary

Source files and branch divergence were inspected through the GitHub connector on 2026-11-11. Local Git clone failed with `Could not resolve host: github.com`; this document has **not** been validated by repository pytest, Ruff, mypy, CI or native Windows acceptance. No cross-version migration or branch merge is authorized here.

## Coherent read-only evidence under concurrent local WAL activity (2026-11-15)

The lightweight `scripts/inspect-alembic-lineage.py` now opens one explicit read transaction **before** SQLite integrity, Alembic stamp, scientific/QC table inventory, and row-count checks. Python's `with sqlite3.connect(...)` alone does not pin a snapshot for successive read statements. A second local writer could otherwise commit an environmental schema migration between integrity checks and stamp/table reads, producing a report assembled from different committed versions. The inspector still opens `mode=ro`, sets `query_only`, checks WAL/SHM/journal sidecars, emits `upgrade_authorized: false`, and never performs a migration.

A deterministic disposable-WAL regression injects a separate writer's 0039→0042 schema/stamp commit immediately after the first integrity probe. The in-progress read-only inspection must report only the original 0039 schema and stamp, while a subsequent inspection observes the complete 0042 schema. The biological sentinel is preserved. This proves consistency *within* one inspection, not immutability of a live WAL database; active-sidecar warnings continue to require a consistent external snapshot and researcher approval before any upgrade.


## Opt-in read-only 0038 structural evidence (2026-11-16)

The existing inspector at scripts/inspect-alembic-lineage.py can now check
two **source-audited** table contracts for the colliding revision-0038
branches without modifying an SQLite research database. Run against a
separately verified, quiescent copy, never the only working database:

    python scripts/inspect-alembic-lineage.py RESEARCH-COPY.sqlite --verify-structural-contracts --fail-on-warning

The optional flag checks scientific_records (1.1) and
review_queue_item_events (1.6) against their independently inspected
migration-source column sets, non-null fields, primary key, foreign-key
targets/delete policies and required index/UNIQUE column sets. The JSON
structural_contracts field reports only matches, mismatch, or absent for
these **fixed known table names**. A mismatch emits
lineage_table_contract_mismatch_<known-table> and fails strict mode.
No column contents, review notes, trigger SQL, raw index names or row IDs
are disclosed by this new structural check.

This is an **opt-in diagnostic**, not an integrated migration. Without the
flag, existing historical inspector behavior is preserved and
structural_contracts is empty. Positive shape matches alone cannot
distinguish independently applied revision IDs or prove that all recorded
rows, CHECK constraints, column type affinities, workflow references,
0039 computed metrics, 0040/0042 environmental extensions or 0041 QC
registry are compatible. These remain separate acceptance gates. The
inspector still sets upgrade_authorized: false, and 0038 still carries
the explicit reconciliation warning even when the table shape matches.

Ten disposable populated-database regressions cover positive controls,
missing/extra/generated columns, wrong FK delete policies, missing
indexes/UNIQUE and nullable reviewer attribution; a strict CLI regression
checks JSON redaction, exit code and unchanged database bytes. Full exact-head
backend CI and Windows installed-GUI acceptance must be checked separately.

## Unique-index semantics beyond column names (2026-11-16)

The optional 0038 structural audit now checks SQLite `PRAGMA index_xinfo`
for every UNIQUE key, including the primary key. In addition to matching
the expected columns and rejecting partial or extra UNIQUE indexes, it
requires the migration's ordinary ascending, BINARY-collated key semantics.
`PRAGMA index_info` alone hides collation and sort flags: a restored
review-event UNIQUE constraint on the expected columns but with
`client_request_id COLLATE NOCASE` would silently collapse distinct
case-sensitive reviewer idempotency tokens, while a DESC constraint would
not match the migration's declared key order. Both are flagged as
`lineage_table_contract_mismatch_review_queue_item_events` without
revealing request values, researcher identities, or SQL definitions.

Disposable regression scenarios retain valid uniqueness and unrelated
nonunique lookup indexes, and reject NOCASE, DESC, and combined changes
to the reviewer request-key UNIQUE. Repeated read-only strict inspection
must preserve review and biological sentinel rows and database bytes.
This check does **not** validate arbitrary CHECK clauses, SQLite type
affinities, row-level provenance, or compatibility with the 1.1 migration
branch; no upgrade is authorized.
