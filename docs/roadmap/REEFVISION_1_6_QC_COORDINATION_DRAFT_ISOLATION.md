# ReefVision 1.6 — QC coordination draft isolation

## Audited scope and gap

The 1.6 review coordination panel already provides append-only local comments,
reviewer assignment, self-reported actor labels, pagination, and exact-request-ID
retries for uncertain SQLite/API outcomes. Existing saved `qc_review_queue`
Workflow Builder nodes preserve typed queue references and require researcher
review. This change does not duplicate those features or modify workflow graphs.

A delayed successful comment or assignment response previously cleared its input
unconditionally. If a researcher had begun another comment or changed the next
assignee while the first request was pending, that newer draft was silently lost.
A retry after an uncertain response could likewise erase edits made while waiting.
This is a UI data-loss problem, not an approval or scientific-scoring change.

## Behavior

- Every comment/assignee edit increments its own in-memory revision.
- Submission snapshots the original event payload, UUID, and field revisions.
- Retry reuses the exact original payload and UUID; it does **not** silently
  replace the submitted evidence with the newer unsent draft.
- A success clears only the submitted field when its revision is unchanged.
  Later edits, including an edit-and-revert to identical text, remain intact.
- Successful mutations still invalidate only the original queue/item event
  history. No annotation is verified, accepted, deleted, or auto-approved.

## Acceptance

`ReviewQueueCoordinationPanel.test.tsx` covers delayed successful comment
submission while a newer comment is being drafted, and uncertain assignment
retry with the same UUID while a different assignee is typed. The original
comment/assignment and original actor are still sent to the API. Tests must
pass under frontend lint/format, TypeScript, Vitest and E2E checks; interactive
installed Windows GUI acceptance remains outstanding.

No schema migration or new Workflow Builder node is required because the
change only protects unsubmitted local form state. Existing typed workflow
inputs/outputs, persisted runs, provenance, retry and review-gate semantics
remain unchanged. Do not infer 1.6 release readiness from these tests alone.
