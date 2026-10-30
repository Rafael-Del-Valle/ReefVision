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

## Read-only QC history under local SQLite contention

A separate gap affected `GET /review-queues/{queue_id}/items/{item_id}/events`:
when another local process held an EXCLUSIVE SQLite transaction, the
read-only history endpoint propagated the raw lock as a server error.
It now rolls back the read session and returns retryable HTTP 409 **only**
for genuine SQLite BUSY/LOCKED errors. Unrelated database failures still
propagate; no audit record, review state, or scientific annotation is changed.

The same `test_review_queue_event_contention_16.py` suite now exercises this
history-read path against both standalone QC queues and persisted, executable
Workflow Builder QC queues. It verifies the conflict during an EXCLUSIVE
lock, a successful history read after lock release, no synthetic assignments,
unchanged pending review state, and continued researcher-approval requirements.
The independent SQLite reproduction confirms the lock/read/recovery semantics,
but does **not** replace exact-code repository CI or installed Windows GUI tests.

## Outstanding acceptance

- Exact-head CI: Ruff, mypy, backend pytest, frontend checks and Playwright.
- Native Windows multi-process SQLite tests, MSI clean install/upgrade/rollback,
  and interactive installed-GUI acceptance.
- Representative biological-data review, privacy and researcher-approval checks.
- Resolve the independent 1.1/1.6 Alembic revision-0038 conflict safely after
  upstream integration; do not rewrite already-applied installed migrations.

No user assets, checkpoints, or scientific observations are changed.


## 2026-10-29 — Explicit UTC reviewer-history API timestamps

SQLite returns naive datetimes for the existing timezone-aware SQLAlchemy audit
column, even though ReefVision's `utc_now()` writes UTC. The response schema
now treats those legacy naive values as UTC and converts offset-aware values to
UTC before JSON serialization. Standalone review comments, idempotent retries,
and persisted `project_source -> qc_review_queue` Workflow Builder review
histories must expose the same explicit `Z` timestamp. This changes only API
representation, not stored events, annotation verification, saved graph units,
or researcher approval. Added a schema regression for naive and offset-aware
values and API regressions for standalone and saved-workflow QC queues.

At predecessor `9166abbc`, GitHub Actions run `40980891049` passed frontend
and backend lint but failed Ruff format on one blank line in
`test_desktop_runtime_paths.py:156`. The same change set repairs that exact
formatting failure. New-head integrated CI, native Windows installed-GUI/MSI,
representative biological acceptance, and the independent 1.1/1.6 Alembic
revision-0038 conflict remain release blockers. No merge or release.

## 2026-10-29 — Safe large-page review-history reads

A valid but extremely large `page` query can produce a SQLite OFFSET larger
than its signed 64-bit binding range. Previously this raised an uncaught
`OverflowError` and turned a read-only QC history request into HTTP 500.
The event-history service now skips only the impossible page query when the
calculated offset exceeds `2**63 - 1`, while still querying and returning the
true event count and latest reviewer assignment. The maximum representable
offset is still handled normally; ordinary page ordering is unchanged.

The same read-only service powers standalone review queues and saved executable
`project_source -> qc_review_queue` Workflow Builder queues. Added six
parameterized API regressions across both paths, including the signed-64-bit
boundary, one-above-boundary, and a large page with 100 entries per page.
The tests require an empty page, real total/assignment, unchanged pending
review state, and explicit researcher-review status. No migrations, reviewer
events, model approvals, or scientific observations are modified.

An isolated SQLite reproduction confirmed that out-of-range integer OFFSET
parameters raise `OverflowError`, whereas the maximum signed-64-bit OFFSET
returns an empty result. Repository pytest/CI and Windows installed-GUI
acceptance are separate required gates; this reproduction is not full acceptance.
