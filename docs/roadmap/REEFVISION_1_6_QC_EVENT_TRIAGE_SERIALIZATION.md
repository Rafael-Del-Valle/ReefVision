# ReefVision 1.6 — serialized QC assignment and comment append

**Branch:** `develop/reefvision-1.6` (draft PR #77; issue #76). **Release status: HOLD.**

## Prior scope audit and gap

ReefVision already has class controls, persisted per-user/project layer visibility,
dense-editor object navigation, standalone QC, audit comments and assignments,
bulk triage, and typed executable saved Workflow Builder graphs that produce
immutable queue references with dimensionless priority scores and mandatory
researcher review. Earlier tracks must not be merged or duplicated here.

The existing immediate SQLite writer barrier was called by single-item and bulk
triage, but comment/assignment creation still read queue scope, history and
idempotency keys *before* claiming the writer turn. Two local reviewers could
make decisions against different snapshots or encounter writer contention only
at append time. This increment shares the barrier with coordination events,
before any database state read. A competing SQLite writer returns a retryable
409; a service entered with an explicit stale read transaction fails closed.
A retry uses the same client request UUID, and existing audit keys prevent a
duplicate. No event, queue state or scientific observation is auto-approved.

## Acceptance contract

`test_review_queue_event_contention_16.py` exercises both a standalone queue
and a persisted, executable `project_source -> qc_review_queue` workflow.
A first session claims the exact review-triage lock, the concurrent assignment
gets 409 with no event, then the same request succeeds once after release and
idempotent replay returns the original event ID. A second case explicitly
creates an old SQLite read snapshot, requires rejection before append, and
verifies recovery of a single comment with pending researcher review.

No schema or API contract changes are required. Current saved workflow graphs,
typed outputs, units, review gates, original images, annotation provenance,
immutable datasets and reviewer-history rows are preserved.

## Verification limits and release gate

The exact-head GitHub Actions backend pytest, Ruff, mypy, migrations,
frontend unit/E2E/build and native-Windows checks must finish successfully.
A SQLite-only local reproduction cannot substitute for those repository
regressions. Independently reconcile the conflicting 1.1/1.6 Alembic 0038
lineages before integration; perform native installed-MSI clean-install,
upgrade/rollback, installed-GUI and representative biological acceptance and
obtain researcher approval before any release.

No merge, tag, release, deployment, pretrained-weight download or user-asset
deletion is authorized.
