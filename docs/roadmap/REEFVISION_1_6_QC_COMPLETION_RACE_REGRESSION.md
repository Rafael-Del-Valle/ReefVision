# ReefVision 1.6 — completed QC provenance versus interrupted-create races

## Scope and overlap audit

The existing 1.6 executable `qc_review_queue` Workflow Builder adapter already binds typed project/dataset sources, persists a dimensionless review-queue reference, verifies immutable evidence, and requires researcher review. Existing deterministic queue IDs and SQLite collision handling cover incomplete-node retries; this increment does **not** add a duplicate node, migration, auto-approval path, or change earlier-version implementations.

## CI failure and correction

At isolated 1.6 head `a4fb5c231c352c0d0cad2c997e70a84f533a9ea8`, Actions run `41492802797` passed frontend validation and backend Ruff/mypy but reported **3 failed, 1,643 passed, 32 skipped** backend tests. The three failures were in the stable-identity, two-process race, and SQLite writer-contention regressions. They simulated an interrupted initial queue creation by deleting a previously completed node's queue and output binding while incorrectly leaving its status as `succeeded`.

The completed-node invariant introduced in the previous iteration correctly rejects that state **before** queue insertion. The regressions now distinguish two cases:

1. **Completed, damaged evidence:** the stable-identity test first verifies that a completed node with a missing output binding and damaged queue ownership fails closed, without attempting a replacement.
2. **Genuinely incomplete retry:** the race/contention fixtures explicitly set the synthetic node to `running` before removing its queue/output. Deterministic UUID primary-key collision, real multi-process SQLite races, busy/locked writer handling, unrelated constraint propagation, and preservation of independent researcher review remain under test.

The stable-identity fixture restores its original `succeeded` status and saved output binding before asserting exact replay of the original immutable scientific queue. No scientific annotation is marked verified by these tests.

## Verification and release limits

All changes are confined to three existing backend regression files plus this documentation. Exact-head GitHub Actions must confirm the amended tests; remote file read-back verifies what was pushed, **not** execution. Local repository pytest/Ruff and native Windows MSI/CAB/installed-GUI validation remain unavailable while the local environment cannot resolve GitHub DNS. Independently resolve the 1.1/1.6 Alembic revision-0038 collision before integration. Keep draft PR #77 and release HOLD until full scientific, migration, frontend/backend/E2E, and Windows acceptance evidence exists.
