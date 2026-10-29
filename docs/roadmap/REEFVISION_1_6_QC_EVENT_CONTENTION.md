# ReefVision 1.6 — manual QC coordination concurrency acceptance

**Scope:** 1.6 only, isolated draft PR #77, coordinated in issue #76.
**Release decision:** HOLD. No migration, cross-version merge, or automatic scientific approval.

## Audited existing scope

Main already supplies class creation/reassignment, per-user/project class visibility,
QC scoring, and persisted typed Workflow Builder. The 1.6 branch already supplies
standalone and executable saved-workflow QC queues, manual bulk triage, comments,
assignments, provenance checks, deterministic queue identity and retryable bulk
SQLite writer contention. This iteration does not duplicate those features.

## Gap closed

Manual comment/assignment creation could surface a raw SQLite lock error if
another local process locked the database during the initial scope read or the
event append. Additionally, its commit handler treated *all* SQLAlchemy
integrity errors as candidate idempotent retries, obscuring unrelated database
constraint failures as ordinary reviewer conflicts.

The event API now rolls back on real SQLite BUSY/LOCKED errors and returns a
retryable HTTP 409 instructing the caller to reuse the **same event request ID**.
Unrelated operational errors still propagate. The service's integrity-error
handler now replays only a real SQLite UNIQUE collision on
`(review_queue_item_id, client_request_id)`, after verifying that the prior
event matches the project, queue, actor, event type, comment and assignee.
Unrelated UNIQUE, foreign-key and NOT NULL errors roll back and propagate.

## Regression contract

`test_review_queue_event_contention_16.py` covers both independently created
queues and queues produced by the executable, persisted
`project_source -> qc_review_queue` Workflow Builder graph. For each it
tests both SQLite IMMEDIATE (writer blocked) and EXCLUSIVE (read blocked)
transactions, HTTP 409, no partial audit or assignment, retry with the same
request UUID, exactly one durable event, and no annotation verification.
Separate real SQLite constraint fixtures cover the exact collision key and
unrelated UNIQUE, NOT NULL and foreign-key errors. A commit-time injected
unrelated integrity failure must propagate without persisting a reviewer
event; retrying after removal must succeed exactly once.

The Windows MSI build's focused backend preflight includes the new test file.
This is a **test gate**, not evidence of successful native installation.

## Outstanding acceptance

- Exact-head CI: Ruff, mypy, backend pytest, frontend checks and Playwright.
- Native Windows multi-process SQLite tests, MSI clean install/upgrade/rollback,
  and interactive installed-GUI acceptance.
- Representative biological-data review, privacy and researcher-approval checks.
- Resolve the independent 1.1/1.6 Alembic revision-0038 conflict safely after
  upstream integration; do not rewrite already-applied installed migrations.

No user assets, checkpoints, or scientific observations are changed.
