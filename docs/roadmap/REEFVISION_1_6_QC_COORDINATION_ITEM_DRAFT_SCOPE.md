# ReefVision 1.6 — QC coordination draft and history isolation

## Audit and defect

The existing review coordination panel already bound submitted comments and assignments
to immutable queue/item IDs, reviewer labels and navigation epochs, and used request
UUIDs for uncertain retries. However, its **unsent** actor label, assignee, comment
and history page were component-wide React state. If an embedding reused the panel
for another review item without remounting it, a note or actor from the previous
biological observation could appear under the next item and be submitted there.
The prior event history page could also show an empty page for the next item.

## Change

- Key unsent actor, assignee, comment and event-history page by the exact
  `[queueId, itemId]` pair; a new item starts with empty drafts and page 1.
- Returning A → B → A restores A's unsent local work rather than silently
  dropping or copying it. These drafts remain ephemeral React state, not persisted
  scientific records or a verified identity system.
- A successful event clears only its originating scoped draft, and only when
  the existing edit-revision, reviewer-revision and navigation-epoch gates permit.
- Existing immutable API submission targets, UUID retry behavior, provenance,
  append-only event history and human review requirements remain unchanged.

## Acceptance and limits

Component regressions verify that notes/actor/assignee never leak to another
item, an item-B submission carries only B's attribution, A's unsent draft is
restored, and history pagination starts at page 1 for B while retaining A's page.
Prior delayed-response and uncertain-retry tests must also remain green.

This is a local UI correctness change, not a new analysis capability. Existing
standalone QC APIs and executable, saved `qc_review_queue` Workflow Builder
nodes remain the canonical scientific operation; no new node, migration or units
are warranted. The source of truth for persisted reviewer events remains the
database. Local UI tests and Windows installed-GUI acceptance are still required
before release; a pushed commit alone is not acceptance evidence.

## 2026-10-31 — Uncertain event retry preservation across navigation

An unresolved comment/assignment request can finish with a network error after the
researcher has moved to another review item. Previously the component retained only
one global failed request and ignored errors outside the current navigation epoch.
This made the original idempotency UUID unavailable on return, risking a duplicate
append-only audit event if the researcher manually resubmitted with a fresh UUID.

- Store the uncertain request and error message by its exact queue/item key, not
  as one panel-wide failure. Late failures remain attached to their source item
  and never appear under another item's reviewer attribution.
- On return, the researcher may retry with the **same UUID, payload, actor and
  target queue/item**, while the UI uses the current navigation epoch solely for
  response handling. Success clears only the matching UUID for that item;
  unrelated uncertain requests remain available.
- The existing explicit **Discard failed action** control removes only the
  current item's retry. This does not imply cancellation or rollback of an
  already-delivered append-only event.
- Added regressions for delayed A-to-B-to-A failures and independent uncertain
  A/B events, including exact replay identity and reviewer attribution.
  These retries remain ephemeral local UI state; closing/remounting the panel
  does not guarantee preservation. The server-side idempotency key remains the
  authoritative duplicate prevention mechanism.

No new scientific analysis, Workflow Builder node or database migration is needed:
the existing standalone append-only QC event API and executable saved QC queue
workflow retain typed provenance and researcher-review gates. Exact-head CI,
Windows installed-GUI and representative biological-data acceptance are still
required before release.
