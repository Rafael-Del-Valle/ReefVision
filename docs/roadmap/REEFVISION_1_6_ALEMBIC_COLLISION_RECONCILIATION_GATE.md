# ReefVision 1.6 — Alembic 0038 collision: reviewed reconciliation gate

Status: **BLOCKED / DO NOT AUTO-MIGRATE**. Coordination: issue #76; draft PR #77.
This is a verification plan, not an assertion that either lineage has been reconciled.

## Evidence and scope
The 1.1 branch contains `0038_scientific_data.py` while the isolated 1.6 branch contains `0038_review_queue_item_events.py`. A matching `alembic_version` value is insufficient to distinguish them. Preserve the existing class visibility, QC event history, saved Workflow Builder runs, and scientific records. Do not copy a migration from an unmerged version branch into this branch or change a production revision stamp.

The read-only `scripts/inspect_sqlite_lineage_16.py` captures: committed Alembic stamps, relevant table/column/index/FK evidence, schema DDL SHA-256, SQLite header metadata, integrity findings and FK violations. It explicitly returns `classification=requires_researcher_review`. The diagnostic fingerprint is structural, not a record-content checksum or proof of migration lineage.

## Mutable SQLite sidecars (1.6 strict inspector)

The legacy read-only Alembic inventory already warns about `-wal`, `-shm`
and `-journal` files. The more detailed comparison inspector now reports
`sqlite_sidecar_presence` for each input (primary and reference) and sets
`sqlite_sidecar_consistent_snapshot_required` if any such sidecar was seen
before or after inspection. This is a conservative condition, not proof that
the sidecar contains uncommitted data. Its schema DDL hash remains structural;
a matching schema and revision does **not** override snapshot warnings.

The optional `--fail-on-integrity-error` and `--fail-on-lineage-collision`
gates reject **either** database with a detected sidecar (exit 2 and an
unchanged, read-only review report). Non-strict inspection still reads
committed WAL data instead of treating the main database file as the only
valid image. A database with no visible sidecars is **not** proven immutable
or backed up; reviewers must still verify a consistent offline snapshot
before attempting reconciliation.

Regression contract: run
`pytest scripts/tests/test_sqlite_lineage_mutable_sidecars_16.py` on the
exact candidate head. The tests exercise a live WAL with a pinned old reader,
both comparison input positions, a live rollback journal, a canonical
sidecar-free copy, confidentiality, review classification, strict exit
statuses and unchanged main database/WAL bytes. SQLite shared-memory
reader locks can change without implying biological-data modification.

## Required independently reviewed reconciliation
1. Collect exact SHA and parent/child revision graph of **both** migrations and all successors from their own version branches. Compare DDL, indexes, FK constraints, defaults, data backfills and downgrade behavior. Identify all overlapping object names.
2. Inventory representative *copies* of pre-0038, 1.1-0038, 1.6-0038, and post-0038 databases, including SQLite WAL mode, user/project class visibility, QC audit events, saved workflow graphs/runs and scientific records. Retain original bytes and record checksums. Never test migrations against the only copy of a research database.
3. Run the inspector against copies **before and after** every proposed upgrade/downgrade. Treat malformed stamps, missing keys, FK mismatch and quick-check failures as a hold, not as zero errors.
4. Design an **additive, uniquely identified** revision lineage/merge strategy with the owning 1.1 track. A branch-specific `0038` cannot safely be reinterpreted from its stamp alone. For any ambiguous source database, require explicit researcher identification/approval and verified schema/data preconditions before mutation. No silent stamp rewrite.
5. Test migrations from every supported baseline, including both collision variants, on disposable database copies. Assert preserved scientific observations, annotation geometry, tank/fragment experimental units, reviewer identity, append-only QC events, assignment/comment history, saved graph definitions, run provenance and explicit review gates. Test interrupted migration, repeat application, rollback or documented no-downgrade policy, and WAL checkpoints.
6. Run backend Ruff/mypy/pytest and migrations, frontend TypeScript/Vitest/Playwright/build, saved and standalone `qc_review_queue` workflow regressions, and representative scientific acceptance on the **exact candidate head**.
7. Validate Windows MSI/CAB clean install, update/upgrade, rollback, launch commands and installed GUI with a backed-up database. Record installer checksum and hardware/test environment. Do not mark release-ready from CI alone.

## Exit criteria
Document the approved cross-track migration graph, a reproducible fixture matrix with before/after checksums and evidence, exact-head CI and local Windows results, explicit residual risks, and researcher approval in issue #76 and PR #77. Until then, **1.6 release HOLD; 1.7 and revised 1.8 remain isolated**. No merge, tag, release, paid hosting, model-weight download or research-asset deletion is authorized.
