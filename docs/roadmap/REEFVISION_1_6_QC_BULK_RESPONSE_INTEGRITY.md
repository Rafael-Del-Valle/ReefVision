# ReefVision 1.6 — bulk QC response integrity and exact retry

## Scientific integrity gap

A bulk review mutation can reach the local API even when the response is lost, malformed, or refers to a different queue or action. Treating a mismatched response as success would show a false review-completion banner and discard the researcher's original idempotency UUID. A response that drops the explicit `requires_researcher_review` flag must not be treated as biological verification.

## Fail-closed behavior

The existing bulk QC mutation now checks the returned queue ID, action and explicit researcher-review requirement against the submitted immutable request. Any mismatch is an **uncertain outcome**, not a confirmed failure or success. The UI retains the exact queue, selected item IDs, actor, action and original UUID; the researcher can retry the identical request. It does not display a success banner or invalidate the queue based on the mismatched response. A later valid idempotent replay may report zero changed rows, which is legitimate.

The backend's append-only QC events, user-scoped visibility settings and executable saved `qc_review_queue` Workflow Builder node are unchanged. This validation is strictly a client-side integrity gate; it never verifies scientific annotations automatically or silently reissues a new UUID.

## Regression and release gates

`ReviewQueueBulkTriage.test.tsx` parameterizes mismatched queue, action and researcher-review gate responses. Each regression asserts no false success, no premature cache refresh, and byte-for-byte identical API arguments on retry, followed by a valid response and audit-event refresh. Existing standalone and saved-workflow tests remain mandatory. This does not establish Windows installed-GUI, MSI upgrade/rollback, cross-version Alembic migration reconciliation or real biological-data acceptance. Release remains **HOLD** pending full exact-head CI and researcher approval.
