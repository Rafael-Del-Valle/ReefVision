# ReefVision 1.6 — QC coordination close safety

## Audited gap

The existing 1.6 coordination panel preserves reviewer comments and assignments per
queue/item while mounted, and retains an uncertain event's original UUID for an
idempotent retry. However, the **Close coordination** button previously unmounted
the panel without warning when it contained an unsent biological note, an unsent
assignment, a pending append-only audit event, or a failed event whose delivery
was uncertain. Unmounting loses ephemeral drafts and uncertain retry metadata.
A later manual resubmission with a fresh UUID can duplicate an event that the
server already received.

This is a UI-only safety boundary. The existing append-only QC API and executable
saved `project_source -> qc_review_queue` Workflow Builder graph already provide
typed queue references, dimensionless QC scores, persisted provenance and explicit
researcher review; no new scientific node, units, or migration is appropriate.

## Change

- **Close coordination** is disabled while a QC event is pending or its outcome
  is uncertain. The panel tells the researcher to finish the request or explicitly
  resolve the uncertain result first. Retrying uses the existing immutable UUID,
  actor, payload and queue/item target.
- When a comment or assignee draft is unsent, closing requires a second explicit
  **Close without saving drafts** action. **Continue editing** preserves both
  drafts. This does not create or approve a biological observation.
- The confirmation is bound to the exact queue/item key. A confirmation for
  item A never appears for item B; returning to A preserves A's unsent text.
- The existing explicit **Discard failed action** is still available. It warns
  that the request may have been delivered; discarding it does not cancel an
  already-committed server event.

## Regression contract

React component regressions cover explicit draft-discard confirmation without
an API mutation, exact UUID reuse after an uncertain network outcome, and
isolation of the confirmation across A-to-B-to-A navigation. Existing saved
Workflow Builder and standalone QC tests must remain green.

## Limits / release hold

This guard covers the panel's own Close button. It cannot prevent a browser
reload, a parent workspace unmount, an application crash, or OS shutdown.
Drafts and uncertain UUIDs remain ephemeral component state. Researcher-facing
recovery across process restarts requires a separate privacy-reviewed durable
local outbox design with expiration and an explicit consent/retention policy;
this change does **not** silently persist research notes or create a new account
identity. It also does not turn self-reported reviewer labels into authenticated
accounts.

No local frontend test or installed Windows GUI pass is claimed until executed.
The independent 1.1/1.6 Alembic revision-0038 collision, Windows MSI
upgrade/rollback, scientific data acceptance and full release matrix remain
blocked. No merge, release, weights download or user asset changes.
