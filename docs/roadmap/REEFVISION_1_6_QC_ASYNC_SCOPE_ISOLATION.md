# ReefVision 1.6 — Asynchronous QC queue scope isolation

## Audit and gap

The existing 1.6 review dashboard already provides scoped queue queries, manual bulk triage, reviewer coordination, typed persisted `qc_review_queue` Workflow Builder runs, and explicit researcher approval. The missing case was an asynchronous standalone **Generate queue** or **Regenerate** response arriving after a researcher navigated from project A to project B (or changed dataset-version scope). The previous success handler used the current component's state to select the returned queue and invalidate the current project's cache. A stale response could therefore clear project B's active queue selection even though the queue ID itself was correctly scoped by `scopedReviewQueueId`.

## Change

Generation and regeneration now carry an immutable request scope (project ID, scope type, dataset-version ID) through the mutation. Generation also snapshots the chosen QC run, weights, and confidence threshold. On completion, only the matching current scope may select the returned queue or open quick review. Invalidation targets the **originating** scope, not the project currently visible. No queue is auto-approved, no scientific observations or existing review decisions are modified, and no new workflow node or migration is needed because this corrects the standalone dashboard's navigation behavior; the existing saved executable QC workflow remains unchanged.

## Regression and acceptance

`ReviewQueueDashboard.scope.test.tsx` now defers both generation and regeneration, navigates to a different project, resolves the original request, and verifies that the new project's queue remains selected and queried. These are frontend regressions, not proof of installed Windows GUI behavior. Full exact-head CI, native Windows installed-GUI navigation, representative biological data, MSI upgrade/rollback, and independent 1.1/1.6 Alembic revision-0038 reconciliation remain release blockers.

**Status: DRAFT / HOLD.** No merge, tag, release, deployment, cloud hosting, pretrained-weight download, or research-asset deletion.
