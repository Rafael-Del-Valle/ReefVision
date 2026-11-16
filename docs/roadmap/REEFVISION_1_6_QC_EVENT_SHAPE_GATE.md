# ReefVision 1.6 — fail-closed QC action-evidence integrity

Saved QC histories and executable Workflow Builder review-queue nodes already
bind actions to projects, queues, items and idempotent request keys. A genuine
gap remained for inconsistent event action fields after an external migration,
database import or manual SQL repair. A forged assignment with no assignee,
an unassignment retaining an assignee, a missing review comment, or an unknown
event type can satisfy foreign keys while misleading current-assignment
reporting.

The server now inspects the **entire item history**, including entries outside
a requested page, and blocks both reading a compromised history and appending
further manual reviewer events with HTTP 409. The error contains no private
actors, event IDs, comments or research filenames. The check accepts existing
server-generated triage types and preserves historical skip reasons. It does
not modify an event or automatically confirm any biological observation.

Coverage includes standalone QC queues and typed, persisted, executable saved
Workflow Builder QC queues. No extra workflow node, data-type change, database
migration, pretrained model, media download or user-science mutation is added.

Regression: `test_review_queue_event_shape_16.py` alters disposable event
records, verifies first and out-of-page reads and independent appends fail
closed, checks history was not extended, then verifies normal history after
test-only restoration; the separate comment case tests blank text.

This integrity check does not prove a fully self-consistent event is
authentic, replace the offline migration-preservation gates, or authorize an
upgrade or release. Full backend/frontend/E2E CI, 1.1/1.6 Alembic-0038
reconciliation, researcher-reviewed biological/saved-workflow acceptance and
native Windows MSI/CAB installed-GUI/upgrade/rollback evidence remain HOLD.

## Cross-entry-point bulk triage integrity

The previous action-shape guard ran on standalone manual event endpoints but
not on the bulk triage service. A corrupted prior event could therefore be
followed by a new bulk action or even be accepted through a previously keyed
bulk replay. Both paths now invoke the same full-history read-only validator
before mutating queue state or returning a successful idempotent acknowledgement.

The database-backed regression matrix covers keyed and unkeyed bulk requests,
standalone queues, saved executable Workflow Builder queues, all-or-nothing
item state, private reviewer-label non-disclosure, request-key nonreservation,
and safe replay after test-only repair. A separate replay regression changes
an existing triage record and verifies that its previously registered request
key does not bypass the guard. No automatic scientific review is introduced.


## Bulk transition reason/actor integrity

The shared read-only full-item guard rejects imported bulk `triage_skip`
events with absent or whitespace-only reasons, non-skip triage events carrying
an unauthorized comment, and event actor labels that are blank. It handles
tabs and newlines as well as spaces; SQLite's default one-argument TRIM does not.
Both standalone and persisted, executed QC Workflow Builder queues enforce
these rules before paged history reads, new coordination events, bulk updates
and keyed replay. New disposable database regressions exercise all four
triage actions, malformed skip reasons, forged comments, blank actors, off-page
history, unchanged scientific state and no-op replay only after test-only
restoration. No event is silently repaired or scientifically approved.

## Single-item triage must honor the same audit guard

The individual `/review-queue-items/{item_id}/start|skip|return|complete`
routes previously wrote manual state transitions without the provenance and
full-history action-integrity checks already enforced by the event and bulk
routes. An imported malformed event or reassigned foreign-queue event could be
followed by a seemingly successful single-item review transition. All four
single-item paths now reuse the existing validation before any state change or
append-only event write, for both standalone queues and persisted, executable
Workflow Builder QC queues. An invalid history returns HTTP 409, leaves review
state and observations untouched, and never auto-confirms biological labels.

Regression: `test_review_queue_single_item_history_guard_16.py` checks each
single-item action against off-page corrupted action evidence (including a
previous skip), tests provenance reassignment to a different real queue, and
verifies recovery only after restoring the disposable fixture. It also checks
saved-workflow and standalone parity, unchanged annotations and review gates.
No migration, new workflow node, new model provider or researcher asset change.
