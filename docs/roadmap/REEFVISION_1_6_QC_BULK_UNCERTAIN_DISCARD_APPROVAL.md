# ReefVision 1.6 — explicit approval for uncertain bulk QC discard

## Scope and rationale
A bulk QC request may commit successfully even when the desktop loses its HTTP response. The client retains the exact queue, item selection, actor, action and UUID so that retry is idempotent. Previously, the **Discard and refresh** control removed that UUID in one click, allowing an accidental new submission with a new UUID. This can misrepresent reviewer history or create a duplicate audit event.

## Behavior
- First click **Review discard risk** exposes the risk; the UUID and exact retry remain available and no server mutation is made.
- A separate **Discard and refresh** click explicitly removes only the currently scoped local uncertain request and refreshes that queue's items and audit-event history. It does not delete server records or verify observations.
- Approval is tied to the original request UUID, queue and navigation epoch. A→B→A navigation invalidates it, even if the original retry is still available.
- Retrying the identical request invalidates discard approval. New uncertain outcomes also invalidate it.
- The existing standalone bulk API and saved executable `qc_review_queue` Workflow Builder node are unchanged. Typed review-queue references, provenance, idempotent replay and researcher review remain mandatory.

## Regression and acceptance
`ReviewQueueBulkTriage.test.tsx` tests two-step approval, retained exact retry, no mutation during risk review, queue-specific refresh, and navigation invalidation. These tests must pass in CI alongside TypeScript, Prettier, full Vitest, Playwright, backend tests and saved Workflow Builder regressions. This UI safety control does **not** replace durable recovery across app restarts, event-log reconciliation or Windows installed-GUI testing.

## Release gate
Hold 1.6 until exact-head CI, independent Alembic 1.1/1.6 revision-0038 reconciliation, Windows MSI upgrade/rollback and installed GUI, representative scientific data, and researcher approval. No merge, release, pretrained-weight download or asset deletion is authorized.
