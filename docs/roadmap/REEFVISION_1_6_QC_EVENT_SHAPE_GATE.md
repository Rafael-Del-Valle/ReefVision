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
