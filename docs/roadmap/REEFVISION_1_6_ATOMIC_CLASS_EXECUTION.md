# ReefVision 1.6 — atomic researcher-approved class reassignment

Status: implementation on isolated `develop/reefvision-1.6`; not a
release-ready or installed-GUI validation claim.

## Audited gap

The prior Reassign and Reassign-and-Delete implementations recomputed a
researcher-approved scientific preview, then **committed** an operation with
status `running` before updating annotations, pending model predictions, QC
issues, review-queue class references and (where safe) deleting the source class.
That commit released the SQLite writer lock. Another local worker could observe
a partly executed operation or start an overlapping edit after validation, and
two requests could each read `previewed` before either marked the operation
running. Earlier preview checksums protect scientific evidence but cannot by
themselves serialize execution.

## Bounded implementation

Execution now uses one conditional database write to claim the exact
`previewed` operation before rebuilding its evidence. The write lock is held
through fresh source/target class reads, scientific reference inventory,
checksum validation, mutable-record changes, annotation-history creation and
the final transaction commit. No intermediate `running` commit is published.
If a different writer already claimed or completed that preview, the
conditional write affects zero rows and the attempt returns HTTP 409 without
rewriting biological records. The conditional claim does **not** record an
execution start time: an identity change discovered after the first class read
but before the SQLite writer lock is acquired invalidates the approval under
the lock, and stale/blocked previews are rejected with a null `started_at`.
A successful mutation records its start time immediately after all locked
scientific evidence checks pass. On stale evidence or blocked delete, the
operation's existing failed-result provenance is committed without applying
scientific changes; on in-transaction errors, work is rolled back and the
failure path records the attempted mutation start time only while the
preview remains unclaimed. A failed transaction releases the SQLite writer
lock; the failure-state write now conditionally claims status `previewed`
again, so it cannot overwrite a newer worker's successful completion if that
worker obtained the lock first. The original failure still propagates; the
winning execution's scientific records and provenance remain authoritative.

The lock and race guarantee here concern **local SQLite writer
serialization**, not external filesystem changes, model artifacts or a future
non-SQLite deployment. The local identity remains a consistency label rather
than cryptographic authentication. Historical completed operations and
immutable dataset/model class maps are untouched. Existing direct class APIs,
typed executable QC Workflow Builder and saved-run/researcher-review semantics
are preserved; class-metadata edits are not a new analytical workflow node.

## Regression contract

`apps/api/reefvision/tests/test_class_reassignment.py` checks:

1. A second SQLite connection cannot observe an intermediate committed
   `running` state or partially reassigned annotation while the first
   request is creating history and applying a reviewed class change; after
   completion, the same records appear atomically.
2. A competing writer completing the preview between the first request's
   initial read and its claim makes the first request reject with HTTP 409,
   preserving the annotation and avoiding duplicate reassignment history.
3. For both Reassign and Reassign-and-Delete, an intervening second-connection
   edit to the target class biological state after the first class read but
   before its writer claim causes a stale approval (HTTP 409), without
   reclassifying annotations or predictions. No scientific execution start
   timestamp is recorded for a rejected preview.
4. For both Reassign and Reassign-and-Delete, a synthetic QC reference
   rewrite failure after annotation/prediction edits triggers a complete
   transaction rollback: source-class biological evidence, QC memberships,
   review references, annotation revisions and append-only history remain
   unchanged. The attempted execution receives a `rolled_back` record.
5. A real second local execution may complete after a first failed executor
   releases its lock but before the first records its rollback. The final
   failure-status compare-and-set must not overwrite the second executor's
   `completed` status, biological updates, QC references or scientific history.

These are deterministic synthetic database tests, not representative
biological acceptance. All original annotations, masks, image labels,
frozen-dataset provenance, approved QC events and saved workflows remain
scientifically protected by their existing separate safeguards.

## Release evidence still required

Exact-head Ruff, mypy, backend pytest, frontend and Playwright E2E,
non-destructive migration/backwards-compatibility validation, independent
1.1/1.6 Alembic-0038 integration, representative coral saved-workflow
review, Windows MSI/CAB install/upgrade/rollback and interactive installed-GUI
acceptance. A Linux GitHub Actions pass is not Windows installed-GUI evidence.
No branch merge, tag, deployment, pretrained model download or deletion of
research assets is authorized.
