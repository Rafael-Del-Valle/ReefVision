# ReefVision 1.6 — consistent QC event-history reads

**Branch:** `develop/reefvision-1.6` (draft PR #77). **Status:** release HOLD.
**Coordination:** issue #76. This change is not a migration or review approval.

## Audited existing behavior and the gap

The established 1.6 QC API already provides append-only comments, assignment
history, manual triage, idempotent event keys, saved executable
`project_source -> qc_review_queue` Workflow Builder runs, typed
`review_queue_reference` output, immutable provenance and explicit
researcher review gates. It also detects mismatched event provenance and
handles SQLite contention. Those capabilities remain intact.

The event-history GET response is composed from separate SQLite reads:
queue/item provenance, event total, paginated events and latest assignment.
Under the sqlite3 driver's legacy implicit-transaction behavior, one request
could observe the count before another editor committed an unassignment,
then return the new event or assignee afterward. That makes a scientifically
misleading review-audit response even though every individual SQL query was
valid.

## Change and guarantees

The history-read service establishes an explicit SQLite read transaction
before the first queue/provenance SELECT if a driver transaction is not
already active. All subsequent reads for that HTTP request use one SQLite
snapshot, including the latest assignment and out-of-range pages. Existing
active transactions are respected; no writing transaction, schema migration,
stamping, automatic scientific approval, network service or new workflow
node is introduced. A later independent request observes newly committed
reviewer evidence.

`test_review_queue_event_contention_16.py` adds deterministic SQLite WAL
interleaving tests for **both** standalone and saved/executable Workflow
Builder queues. A second connection commits a reviewer unassignment after
the first event count but before the event-page fetch. The first response
must retain the prior count, original event, old assignee and researcher
review requirement. A subsequent response must show both events and no
assignee, while the queue items remain pending.

## Acceptance and blockers

Run the two new cases and the existing QC event-contention suite using
pytest, together with Ruff, mypy, full backend/frontend and Windows checks.
The branch's independently unresolved Alembic 1.1/1.6 revision-0038 collision
still blocks integration. Representative biological-data validation, native
Windows MSI/CAB install and upgrade/rollback, installed-GUI validation and
researcher approval are required before any 1.6 release decision.

No existing annotation, review, model, workflow artifact or user media is
rewritten by this read-only change.


## Equal-timestamp reviewer event ordering

A second audited gap affects two legitimate append-only reviewer actions with
identical persisted timestamps. The historical UUID-based tie-breaker could
sort a later `unassign` before an earlier `assign`, incorrectly displaying
an active assignee. Local SQLite reads now use the event table's insertion
rowid as the deterministic tie-breaker for both ascending pages and the
latest assignment lookup; the existing UUID fallback remains for other SQL
backends. No event timestamps, UUIDs, existing rows or scientific decisions
are rewritten. This is a read-order correction, not a new permanent event
sequence; SQLite VACUUM can renumber rowids in tables lacking an integer
primary key, so a future schema migration is needed for durable tie ordering
across such maintenance.

A new deterministic test inserts two equal-time events with deliberately
reversed UUID order, verifies chronological pages and unassigned summary,
and checks that item review state stays pending. It runs for standalone and
saved, successfully executed Workflow Builder QC queues.


## Clock-rollback chronology hardening (2026-11-15)

**Existing capability audited:** append-only QC comments/assignments and triage,
consistent SQLite read snapshots, idempotent coordination writes and the typed
executable saved `project_source -> qc_review_queue` Workflow Builder path.
Those functions already exist in 1.6; no new, duplicate workflow node is
needed for this read-only history correctness check.

An equal-timestamp rowid *tie-breaker* is insufficient when the local system
clock moves backwards (for example after offline fieldwork or clock
synchronization). The later `unassign` can then have an earlier timestamp
than the preceding `assign`; ordering primarily by the timestamp shows the
wrong event last and incorrectly reports an active assignee. This is a genuine
review provenance error, not evidence that the scientific annotations changed.

On SQLite, both chronological history pagination and the current-assignee
query now order by the actual **append rowid**, rather than wall-clock time
with rowid used only for ties. Returned timestamps are retained unchanged for
scientific audit, and every event, completion, reviewer decision, workflow run,
typed artifact, saved graph and explicit researcher review gate remains intact.
Other database engines retain their existing timestamp/UUID ordering pending
a coordinated durable cross-backend sequence migration. SQLite `VACUUM`
may renumber the implicit rowid, so this change does **not** claim permanent
sequence identities or resolve that known limitation.

The extended parameterized SQLite regression inserts assignment then
unassignment with reversed UUID ordering and either identical timestamps or
a full-day backward clock correction. It checks first/second pages, latest
assignee and pending human-review state for both standalone API queues and
persisted, executed Workflow Builder queues. No online service, model
downloads, DB migration, automatic approval or original scientific-asset
change is introduced.

**Release HOLD:** complete exact-head lint/type/backend/frontend/E2E,
representative biological and saved-workflow acceptance, reconciliation of
the independent 1.1/1.6 Alembic-0038 histories, real Windows MSI/CAB
installation/upgrade/rollback and installed-GUI acceptance remain required.
