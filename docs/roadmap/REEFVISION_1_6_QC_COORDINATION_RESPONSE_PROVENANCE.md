# ReefVision 1.6 — QC coordination response provenance

## Audited gap

The append-only QC event API returns an event with queue ID, item ID, client request UUID, actor, event type, comment and assignee. The coordination panel previously treated any resolved HTTP response as success, even if the response belonged to another queue or reviewer, and could clear an unsent biological note or reviewer assignment. This was a frontend integrity gap, not a missing backend audit-event or Workflow Builder feature.

## Fail-closed behavior

For comment, assign and unassign, the panel now validates the returned queue, item, idempotency UUID, event type, actor and normalized comment/assignee against the immutable submitted request. A malformed or mismatched response is an **uncertain outcome**: preserve the original request and UUID for identical retry, retain unsent drafts, and do not refresh audit history as if a success were confirmed. Valid idempotent replays still clear only the matching draft, subject to existing navigation-epoch and edit-revision protections. This does not grant scientific verification or authenticated identity.

## Regression and boundaries

`ReviewQueueCoordinationPanel.test.tsx` now uses realistic scoped server responses instead of empty-object success stubs, and covers six mismatched comment response fields plus an assignment recipient mismatch. It checks draft retention, no premature audit-cache invalidation and identical retry arguments followed by valid recovery. The backend's append-only QC event registry, class visibility persistence and executable saved `qc_review_queue` Workflow Builder with typed outputs, provenance, retries and human-review gates are unchanged. No migration or new workflow node is appropriate for this UI response validation.

**Release HOLD:** exact-head frontend/backend CI and saved-workflow regressions, independent 1.1/1.6 Alembic 0038 reconciliation, native Windows MSI upgrade/rollback and installed GUI, and representative biological-data acceptance remain mandatory. No auto-merge, tag, release, deployment, pretrained-weight download or research-asset deletion.
