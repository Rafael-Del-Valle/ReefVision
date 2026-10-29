# ReefVision 1.6 — SQLite read-lock safety for manual QC triage

## Gap and implementation

The existing bulk-QC service handles SQLite `BUSY`/`LOCKED` errors raised
during `session.commit()`, but a second local process can hold an exclusive
SQLite lock **before** the API's initial queue lookup. That earlier
`OperationalError` bypassed the commit handler and could become an HTTP 500.

The bulk-review API boundary now rolls back its session on an operational
failure and converts **only** actual SQLite `SQLITE_BUSY` or `SQLITE_LOCKED`
(primary or extended codes) to a controlled HTTP 409 retry response.
Unrelated database failures propagate; the response never claims that
scientific annotations were accepted or verified.

The preexisting commit-time handler remains in place. No database migration,
review-state algorithm, or scientific priority formula was changed.

## Regression contract

`apps/api/reefvision/tests/test_review_queue_bulk_sqlite_contention_16.py`
exercises both SQLite lock modes:

- `BEGIN IMMEDIATE`: reads are permitted but a bulk write is blocked.
- `BEGIN EXCLUSIVE`: even the initial queue read is blocked.

Both cases run against **standalone review queues** and queues produced by a
**persisted executable Workflow Builder graph** (`project_source →
qc_review_queue`). The workflow case asserts a persisted
`review_queue_reference` artifact with a **dimensionless** priority score
and `requires_researcher_review` status.

Each test uses an independent SQLite connection to hold the lock, expects
HTTP 409 without partial reviewer events or state changes, releases the lock,
retries the **same** request UUID, and verifies one event per item, no
duplicate event on replay, and no automatic annotation verification.
The test creates only disposable pytest research data.

Targeted validation:

```sh
python -m ruff check apps/api/reefvision/api/routes/review_queues.py apps/api/reefvision/tests/test_review_queue_bulk_sqlite_contention_16.py
python -m ruff format --check apps/api/reefvision/api/routes/review_queues.py apps/api/reefvision/tests/test_review_queue_bulk_sqlite_contention_16.py
python -m pytest apps/api/reefvision/tests/test_review_queue_bulk_sqlite_contention_16.py -q
```

## Boundaries and release decision

This guards **local manual QC retry semantics**, not multi-user authorization
or automated biological acceptance. It does not reconcile the independent
1.1/1.6 Alembic revision-0038 conflict. CI, migration compatibility,
representative scientific data, native Windows MSI upgrade/rollback and
installed interactive GUI acceptance remain required before release.
No pretrained models, external services, or user research assets are involved.
