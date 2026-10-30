# ReefVision 1.6 — per-user visibility mutation isolation

Track D, 2026-10-30. Draft PR #77; master issue #76.

## Audited behavior and gap

The existing local API persists class visibility by project and user. The
previous fix isolates delayed responses by project ID. A different user identity
can still become active for the same project while a preference save/reset is
in flight, so the old user's result must not overwrite the new user's cached
visibility preferences or display a misleading completion/error message.

## Implementation

The mutation records the originating local identity from the existing project
visibility bundle. The cache helper requires both project and user identity
to match before applying a **user preference** result. A missing identity
fails closed. Project defaults remain shared across users, and their cache
updates remain project-scoped. Completion/error messages are suppressed when
the active user identity differs. No server-side authorization, stored
scientific annotations, reviewer decisions or local model data are changed.

## Verification and acceptance

Pure regressions cover mismatched users, unknown identity, and shared project
defaults. The editor regression delays a real mocked preference PUT, changes
the cached identity, resolves the old request and checks that the second
user's bundle remains untouched. The predecessor's frontend CI failed at
Prettier in the previous cross-project integration test; this change also
applies the exact formatter-reported correction.

Release HOLD until exact-head formatting, typecheck, component/E2E and backend
CI pass, with Windows installed-GUI/upgrade-rollback, representative biological
data and independent 1.1/1.6 Alembic 0038 reconciliation still outstanding.
No new Workflow Builder node is appropriate: class visibility is a local
display preference rather than a scientific analysis or derived artifact.
