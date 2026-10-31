# ReefVision 1.6 — QC draft-discard approval navigation isolation

Development-only Track D change coordinated through issue #76 and draft PR #77.

## Scope and overlap audit

Existing 1.6 code already provides project/item-isolated unsent QC drafts,
append-only reviewer events, explicit discard confirmation, UUID-preserving
uncertain-event retries, and saved executable `project_source -> qc_review_queue`
Workflow Builder integration. Earlier versions already own the general editor,
annotation storage, and workflow runtime. No duplicate scientific subsystem,
migration, or workflow node is appropriate for a display-only consent fix.

## Confirmed gap

The coordination panel previously stored close-without-saving consent using
only the queue/item key. When a researcher requested to discard a note for
item A, navigated to item B, and returned to A without editing anything, the
old confirmation reappeared and could be accepted without a new decision.
That is unsafe even though the draft text was restored correctly: returning
to a prior item is not continuing the same approval context.

## Change

Close-without-saving consent is now scoped to the queue/item **and navigation
epoch**. A -> B -> A invalidates the old confirmation, including when B is
another item of the same queue or the same item ID in another queue. The
original unsent draft remains available; clicking Close again requires a fresh
explicit decision. Editing the draft continues to invalidate consent as
before. No backend event is created, updated, deleted or auto-approved.

## Regression contract

The parameterized React component regression covers both cross-item and
cross-queue A -> B -> A navigation, with no intervening edits. It verifies
restoration of the original biological note, absence of stale confirmation,
fresh confirmation requirement, cancel behavior and zero audit-event API calls.

Existing standalone QC APIs and saved Workflow Builder QC graph execution
remain authoritative for typed review-queue references, dimensionless priority
scores, provenance, retry behavior and explicit researcher approval. This UI
consent fix does not change graph inputs/outputs, saved runs or units.

## Acceptance status

Do not claim release readiness from source inspection alone. Require exact-head
frontend Prettier, TypeScript, Vitest, Playwright and production build; backend
Ruff, mypy, pytest and migration checks; independent 1.1/1.6 Alembic revision
0038 reconciliation; native Windows MSI upgrade/rollback and installed-GUI
review; representative biological-data acceptance. No merge, tag, release,
deployment, pretrained weights or research-asset deletion.
