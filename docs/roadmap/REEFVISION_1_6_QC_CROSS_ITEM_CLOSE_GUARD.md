# ReefVision 1.6 — QC coordination close safety across review items

## Scope and overlap audit

The 1.6 branch already implements project-scoped class visibility, QC review
events, bulk triage, dense-object viewport culling, onboarding, desktop
commands and the executable saved `qc_review_queue` Workflow Builder node.
This increment does not duplicate those features or introduce a new scientific
workflow node. It addresses an existing UI lifecycle gap in the manual QC
coordination panel.

## Failure and correction

The panel preserves unsent reviewer comments, assignments and uncertain event
requests separately for each queue/item during navigation. Previously, the
**Close coordination** button examined only the currently displayed item's
draft and uncertain event. Closing while viewing item B could silently unmount
the panel and lose item A's biological notes or original retry UUID.

The close guard now:

- Requires explicit discard confirmation if **any** visited item has an unsent
  comment or assignment, including hidden items.
- Blocks closing while **any** visited item has an uncertain event request,
  preserving its original idempotency UUID until the researcher returns to
  that item and retries or explicitly abandons the request.
- Keeps the existing navigation-epoch and edit invalidation safeguards for
  discard approval. It never treats an HTTP response as biological approval.
- Makes no API, database, project, workflow, or scientific-record mutation.
  Drafts remain memory-only: application reload/crash recovery is **not**
  implemented or claimed.

## Verification contract

Frontend regression cases cover both hidden comments and hidden assignment
drafts (A → B → close), cancellation, explicit discard and no accidental API
writes. Another case covers an uncertain event on A while B is visible,
disabled closing, identical UUID retry and continued protection of A's
remaining draft after retry success.

Existing saved-workflow/standalone QC API tests remain required as release
regression gates; the underlying executable typed `qc_review_queue` node,
persisted graphs/runs, provenance, retries and explicit researcher-review
gate are unchanged by this UI-only guard. This change needs no migration.

**Release HOLD:** exact-head TypeScript, Prettier, Vitest, E2E and backend
checks; cross-version Alembic 0038 reconciliation; native Windows MSI
upgrade/rollback and installed-GUI acceptance; representative biological-data
checks and researcher approval. Do not merge, tag or release on this evidence
alone.
