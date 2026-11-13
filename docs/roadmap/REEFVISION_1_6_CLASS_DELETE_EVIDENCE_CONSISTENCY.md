# ReefVision 1.6 — class deletion evidence consistency

## Audited gap

The earlier class-manager usage gate correctly required an explicit successful usage lookup before exposing **Delete unused**, but it trusted the response's `can_delete` boolean alone. A stale, misrouted, or contradictory response could therefore make a destructive action appear available while its project/class identity, aggregate reference totals, individual counts or deletion blockers disagreed. The API's own deletion checks continue to be authoritative; the user-facing review surface should fail closed independently.

## Implementation

The class-manager panel now enables deletion only after a completed, non-refetching, explicitly opened Usage request whose response matches the current project and class, says `can_delete === true`, has zero total, mutable and immutable references, zero in every itemized count, and an explicitly present empty list of deletion blockers. Missing arrays and inconsistent totals are **not** accepted as positive deletion evidence. Foreign-project or foreign-class usage details are not displayed under this class. Contradictory `can_delete` evidence is shown as an error, without inviting a delete request.

This is a client-side, fail-closed safeguard: the backend must continue independently rechecking current database references when processing DELETE. A consistent response is a UI review gate, **not** a database transaction lock; references can change after a query. No user data, historical class map, annotations, model prediction or frozen research dataset was modified.

## Regression and acceptance scope

Eight parameterized browser-component cases cover a foreign project, foreign class, nonzero aggregate references, hidden mutable and immutable references, positive itemization, active deletion blockers and an absent itemization. All assert that the review inconsistency is visible, Delete remains disabled and no DELETE request is sent. Existing happy-path, 503, stale-query/refetch and blocking-preview tests remain.

No migration or new Workflow Builder node is appropriate for this UI-only safeguard. Existing standalone and saved executable `qc_review_queue` nodes, typed scientific outputs, evidence/provenance, persisted run state, retries and researcher approval are preserved. Release acceptance still requires exact-head lint/type/tests, representative biological saved-workflow runs, independent Alembic 0038 reconciliation and native Windows MSI/installed-GUI/upgrade/rollback validation.
