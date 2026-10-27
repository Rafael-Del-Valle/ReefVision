# ReefVision 1.6 review events

Review queue items now support comments, assignment and unassignment
events. The events are append-only and include a request UUID for retries.

The endpoints operate on the same queue identifiers produced by the
standalone QC service and the saved Workflow Builder.

Migration 0038 adds the event table. The feature is still under review.

## 2026-10-27 — Bulk QC provenance preflight (Track D)

The standalone comment/assignment endpoint already refused reviewer events whose
stored project or queue did not match their review item. The bulk triage
endpoint lacked the equivalent check for **new unkeyed** batches and **new
idempotency keys**. It could therefore append a new manual state-transition
event to an item with corrupted reviewer provenance.

Bulk triage now checks existing event scope for **all selected items** before
state changes, registry creation, or audit-event inserts. An inconsistent
event fails closed with HTTP 409; no partial batch is committed. The check is
limited to selected items so unaffected sibling items remain usable. Existing
valid keyed retries and legacy UUIDv5 audit records remain supported.

Parameterized standalone API regressions exercise both corrupted project and
queue references with and without a request UUID, prove no partial writes,
preserve researcher-review gating, and confirm recovery after **test-only**
restoration. The existing saved executable `qc_review_queue` graph regression
also attempts a manual bulk triage against a corrupted queue and verifies its
typed review-required artifact cannot be used to bypass the guard. No
scientific annotations, user assets, migrations, or workflow node contracts
are changed.

This is development evidence, **not** release acceptance. Exact-head CI,
cross-version Alembic 0038 reconciliation, native Windows MSI upgrade/rollback,
installed-GUI testing, and representative scientific acceptance remain open.
