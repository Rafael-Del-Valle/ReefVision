# ReefVision 1.6 — NUL-safe QC review evidence (Track D)

## Scoped audit and defect

The existing local 1.6 API already provides standalone QC review, comments,
assignments and bulk review, shared by persisted executable Workflow Builder
queues with typed, dimensionless priority outputs and explicit researcher-review
gates. Earlier 1.0–1.5 work is preserved. No duplicate workflow node is needed.

SQLite stores embedded NUL characters in TEXT, but its `LENGTH(text)` stops
counting at the first NUL. A restored actor, assignee or comment with a short
prefix, NUL and long invisible suffix could bypass the earlier overlength
historical-evidence guard. Fresh local API requests also accepted NUL in
reviewer labels or skip reasons even though those fields are meant for readable
audit evidence. This is a correctness and provenance gap, not evidence that a
particular research database contains malicious records.

## Implementation contract

- Reject NUL in new manual comment/assignment actor, assignee and comment;
  individual-review actor/skip reason; and bulk-review actor/skip reason, with
  422 validation before writing an audit or consuming an idempotency key.
- Reject imported or restored NUL-containing actor/comment/assignee anywhere
  in the *complete* item history before any paged read, manual append,
  individual review transition, bulk triage or keyed bulk replay. Return a
  privacy-preserving 409; do not display corrupted audit text or change data.
- Keep ordinary Unicode and legitimate existing events, source annotations,
  accepted datasets, workflow runs, unit metadata and reviewer-history rows
  unchanged. No migration, network upload, pretrained weights or asset edits.

## Tests and release gate

`test_review_queue_nul_evidence_16.py` verifies the SQLite LENGTH bypass
explicitly, then exercises all three event fields across standalone and real
saved executable Workflow Builder queues. It checks out-of-page 409, no extra
audit records or partial bulk update, explicit fixture-only restoration and
idempotent manual/bulk recovery with pending researcher review. Separate API
cases cover all manual, single-item and bulk input fields.

Passing a synthetically backed regression does **not** validate biological
truth or authorize a 1.6 release. Remaining HOLD gates include complete
exact-head lint/type/backend/frontend/E2E/migration CI, independent 1.1/1.6
Alembic-0038 reconciliation, representative biological and saved-workflow
acceptance, genuine Windows MSI/CAB installation, installed GUI and
upgrade/rollback tests, and explicit researcher approval.
