# ReefVision 1.6 — bulk QC immutable evidence response guard

## Scientific integrity gap

A bulk QC action changes review bookkeeping, not the underlying biological
evidence. The 1.6 UI already required a researcher to confirm the complete
selected evidence and checked the response queue, action, item IDs, resulting
review states, and changed count. However, an HTTP 200 could still carry the
right item ID and review state with the wrong **project, source image, dataset
version, input checksum, score, class/model evidence, QC signals or reason**.
Acknowledging that response would discard the original idempotency UUID even
though the result was not proven to describe the approved evidence.

## Change

`ReviewQueueBulkTriage` now snapshots immutable review-item evidence at
submission, alongside the original queue, navigation epoch and request UUID.
It compares the returned items against that original evidence snapshot on
every response, including identical retries. Only bookkeeping state fields
(`review_state`, `updated_at`, `started_at`, `completed_at`,
`returned_at`, `skip_reason`) may change as part of triage. Source
identity, project/dataset scope, rank, scoring, normalized signals, class/model
provenance and original creation time must not change.

A mismatched response is treated as **uncertain** rather than success:
retain the exact original request/UUID and evidence snapshot, block conflicting
bulk actions and navigation, do not show success or invalidate caches, and
offer an explicit identical retry or reviewed discard. The existing
browser/native close guards remain active. The retry uses the same API
payload, never silently creates a new review action.

This change also repairs a missing JSX closing brace in the uncertain-response
alert, which prevented the frontend formatter/parser from running at the
preceding 1.6 head.

## Regression coverage

`ReviewQueueBulkTriage.test.tsx` exercises seven HTTP-success but
scientifically mismatched responses (foreign project, different image, dataset
version, checksum, priority score, class evidence and reason summary), verifies
no premature success/cache invalidation, and confirms identical payload/UUID
replay and successful recovery. Existing action-state and count regressions
remain in place.

## Boundaries and acceptance

This is a **frontend response-integrity check**, not server-side optimistic
concurrency control. It does not claim that biological observations have been
verified, that a network timeout implies a failed server transaction, or that
window-close guards provide durable crash recovery. Standalone QC service and
saved executable `qc_review_queue` Workflow Builder node, typed outputs,
persisted graph/run provenance, retries and explicit researcher review gates
remain unchanged. No migration, weights, research assets or version branches
are changed.

Release HOLD until exact-head frontend and backend CI, scientific sample
acceptance, independent 1.1/1.6 Alembic revision-0038 reconciliation, and
native Windows MSI/CAB installed-GUI/upgrade/rollback checks pass.
