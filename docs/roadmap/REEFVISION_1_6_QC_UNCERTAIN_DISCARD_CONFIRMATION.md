# ReefVision 1.6 — uncertain QC audit-event discard confirmation

**Status:** implementation on isolated `develop/reefvision-1.6`; release HOLD pending CI and native acceptance.

## Audited gap

The existing QC coordination panel preserves the original idempotency UUID after
an uncertain network failure and offers an exact-payload retry. However, its
**Discard failed action** control immediately erased the UUID without a warning.
The request may already have reached the local server, so submitting the same
biological observation with a fresh UUID could create a duplicate audit event.

## Implementation

Discarding an uncertain request now requires a separate, explicit confirmation
that warns that abandoning the retry does **not** undo a server-side event.
Canceling preserves the original UUID, actor, payload, destination and retry.
The confirmation is bound to the queue, item, UUID and navigation epoch, so an
A → B → A navigation cannot reuse stale consent. Confirming removes only the
matching UUID from the local pending-request map, leaves the researcher's
unsent note untouched and makes no server-side delete or mutation. Retrying
invalidates the pending discard warning.

## Verification contract

- React regression: canceling discard retains the UUID and exact retry payload.
- React regression: item navigation invalidates confirmation; explicit renewed
  confirmation removes only the pending local retry, without sending an event.
- Existing standalone review-event API and typed, saved, executable QC Workflow
  Builder nodes are unchanged: review gates, dimensionless scores, source
  checksums, provenance and idempotent replay remain enforced by the backend.
  This UI safety guard requires no migration or new scientific workflow node.
- CI formatting repair: apply the exact Prettier diff from run 41177336074 to
  the preceding draft-discard edit regression.

**Limitations:** no durable recovery across application restart; reviewer labels
remain self-reported; an abandoned uncertain request may have reached the
server. Exact-head lint/type/Vitest/E2E, saved-workflow/backend tests,
independent 1.1/1.6 Alembic revision-0038 reconciliation, native Windows
MSI upgrade/rollback, installed-GUI checks and biological-data acceptance
remain required. No automatic approval, merge, release, deployment, model
download or deletion of research assets.
