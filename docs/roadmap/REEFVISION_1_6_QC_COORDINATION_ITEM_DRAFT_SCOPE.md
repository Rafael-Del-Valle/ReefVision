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
