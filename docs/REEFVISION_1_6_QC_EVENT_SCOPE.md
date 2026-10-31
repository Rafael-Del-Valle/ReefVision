# ReefVision 1.6 — QC coordination event scope isolation

Status: **implemented on isolated 1.6 development branch; NOT release-ready**.

## Failure mode and contract

A local reviewer may submit a comment or assignment, then navigate to a different
queue/item while the request is pending. A reused coordination panel must not send
the original request to the newly displayed item, clear a new draft when the old
response arrives, show the old item's uncertain retry under a different item, or
invalidate the new item's review-history cache. Returning A → B → A is a new
navigation and must not reactivate a stale response.

Each event request now captures its originating queue ID, item ID, navigation
epoch, immutable payload, and edit revisions. The mutation uses the captured
IDs, never mutable props, for the API request and cache invalidation. Draft
clearing and uncertain retry presentation are permitted only for the same
queue/item/navigation epoch, reviewer identity and unchanged draft revision.
An uncertain retry keeps the original request UUID and payload, supporting
server-side idempotency; a failed request from a previous scope is not silently
replayed against a new item. Researchers can inspect event history before
resubmitting after navigation.

The normal dashboard already remounts coordination panels with a queue/item
React key; this additional boundary protects direct reuse and future embedded
views without relying on the parent implementation.

## Regression coverage

- Delayed comment from queue A / item A resolves after rendering queue B /
  item B: the request and cache invalidation remain on A, B's draft is
  preserved, and a subsequent B comment targets B.
- A → B → A with a pending event: the old success does not erase the
  current draft even when its text happens to match the original.
- Existing regressions continue to cover reviewer-label changes, uncertain
  retry identity, draft edits and edit-then-revert behavior.

## Scientific and release boundaries

These changes only affect human QC coordination. They do not approve model
predictions, alter biological annotations, change scoring, modify database
schema, or add a new analysis node. Existing typed, executable, saved
`qc_review_queue` Workflow Builder integration and researcher review gates
remain unchanged. Complete CI, representative biological-data acceptance,
cross-version Alembic revision reconciliation, and native Windows installed
GUI/MSI upgrade/rollback testing remain required before 1.6 release approval.
