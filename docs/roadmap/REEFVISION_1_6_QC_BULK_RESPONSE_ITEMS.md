# ReefVision 1.6 — Bulk QC response item-identity integrity

## Existing scope and why this is needed

The isolated 1.6 branch already has an atomic, idempotent bulk QC API, an
executable `qc_review_queue` Workflow Builder node, persisted typed
`review_queue_reference` artifacts, researcher-review gates, and
queue-scoped UI retry handling. The earlier frontend response check covered
only queue ID, action, and the review-required flag. An HTTP-success response
with omitted, substituted, duplicated, foreign-queue, or incorrectly
transitioned items could therefore be shown as a successful review action.

## Incremental safety contract

Before acknowledging a bulk triage request, the UI now checks that the
response includes exactly the requested unique item IDs, every item belongs
to the originating queue, every item has the expected resulting state for
`start`, `skip`, `return`, or `complete`, and `changed_count` is an
integer between zero and the number of requested items. A genuine exact
idempotent retry can return `changed_count=0`; this remains valid only
when the full item set and resulting states match.

A mismatched response is treated as **uncertain**, not a confirmed failure
or success. The original UUID and complete payload remain available for an
identical retry; no success banner, selection clearing, or premature
cache invalidation occurs. The server's transaction, append-only events,
scientific records, and researcher-review gate are not changed.

## Verification and boundaries

Frontend regressions cover omitted, substituted, duplicated, foreign-queue,
wrong-state items, negative, excessive, fractional, and non-finite changed
counts, plus identical retry recovery. Existing queue/action/review-gate
and navigation regressions continue to apply. This is client-side
validation of the existing standalone QC API response, not a new analysis
node; the existing saved Workflow Builder QC graph/run tests exercise the
same server-side review queue and remain unchanged.

**Release HOLD:** exact-head CI; independent 1.1/1.6 Alembic revision-0038
reconciliation; representative biological-data acceptance; native Windows
MSI upgrade/rollback and installed-GUI validation. No merge, release,
hosting, model-weight download, or research-asset mutation is authorized.
