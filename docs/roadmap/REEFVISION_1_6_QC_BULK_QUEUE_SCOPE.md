# ReefVision 1.6 — Bulk QC queue-scoped retries and navigation safety

## Audited gap

The existing bulk QC panel supported idempotent retry UUIDs, explicit manual-review confirmation, evidence-fingerprint invalidation and saved Workflow Builder QC queue nodes. However, its mutation function captured the **currently rendered** queue ID rather than the queue that originated an asynchronous request. A mounted panel reused across queue navigation could therefore send an uncertain retry to a different queue and could invalidate/clear the new queue's state when an earlier response arrived.

## Implementation contract

- Every bulk mutation carries its immutable originating `queueId`, navigation `scopeEpoch`, payload, reviewer label, item IDs and idempotency UUID.
- Uncertain requests are retained **per queue**; A → B → A restores A's exact retry, while B remains independently operable.
- Late successes invalidate **only the originating queue's** item and event caches. They clear the active UI only if the originating navigation epoch is still current.
- A failed request from A never appears as a failure in B. Discarding an uncertain request removes only the matching queue/UUID; it does not delete server-side audit events or annotations.
- Queue switches reset unsent selection, skip reason, approvals and prior success banner. No automatic completion or biological verification occurs.

## Regression and integration

`ReviewQueueBulkTriage.test.tsx` exercises (1) A's uncertain failure, B's independent success and A's byte-identical retry with its original queue and UUID; and (2) A's delayed success after navigation to B, with no B cache invalidation or stale success banner. The standalone bulk endpoint and previously existing executable/saved `qc_review_queue` Workflow Builder node, typed reference outputs, provenance and researcher-review gate remain unchanged. No new migration or workflow node is required for this frontend request-routing correction.

## Acceptance limits

CI must pass formatting, TypeScript, Vitest, Playwright and backend/saved-workflow tests at the exact head. This does not substitute for the 1.1/1.6 Alembic revision-0038 reconciliation, representative biological-data acceptance, Windows MSI upgrade/rollback or installed-GUI testing. No version release, merge, pretrained-model download, cloud upload or asset deletion is authorized.
