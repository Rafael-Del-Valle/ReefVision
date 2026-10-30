# ReefVision 1.6 — single-item QC mutation scope isolation

## Audit and defect

The 1.6 Review Queue dashboard already supports manually confirmed single-item start, completion, skip and return, reviewer coordination, bulk triage, and a saved executable `project_source -> qc_review_queue` Workflow Builder graph. The queue-generation/regeneration path already captures project, dataset and navigation epoch. Single-item actions did not: their mutation success callbacks invalidated whichever `selectedQueueId` was current when the asynchronous API call completed. A researcher switching Project A -> Project B during a slow write could invalidate B instead of A. The reviewer label was also read from mutable component state rather than being bound to the originating action. A delayed quick-review completion callback could dismiss a newer project's modal.

## Change

- Each single-item action now carries the original project/dataset/navigation epoch, queue ID, item ID and trimmed self-reported reviewer label as a single immutable request snapshot.
- API calls use the captured item and reviewer, not the currently displayed actor. Successful writes invalidate only the originating queue's item and event caches, including after project navigation; they never mutate another project's queue.
- A quick-review completion closes the dialog only if its original navigation epoch and queue still match. The original human confirmation remains mandatory, and QC completion does **not** verify biological annotations or model predictions.
- The existing typed, saved executable QC Workflow Builder node, its provenance, retry rules and researcher-review gate remain unchanged. This UI-only safety fix adds no workflow node, schema migration, model download or scientific-data mutation.

## Regression and acceptance

`apps/web/src/features/review-queues/ReviewQueueDashboard.scope.test.tsx` adds deferred API regressions for (1) completing a start operation after A -> B navigation and checking only A's item/event cache invalidation with the original reviewer identity; and (2) completing A's quick-review mutation after B's dialog opens, without dismissing B's dialog. Existing standalone single-item confirmation and saved-workflow QC regressions remain required.

**Release HOLD:** Exact-head frontend Prettier/TypeScript/Vitest/E2E and backend CI must pass. Native installed Windows GUI, MSI upgrade/rollback, representative biological-data acceptance and independent 1.1/1.6 Alembic revision-0038 reconciliation remain separate blockers. Do not infer Windows or scientific acceptance from synthetic frontend tests.
