# ReefVision 1.6 — QC reviewer-label display integrity

**Scope:** isolated `develop/reefvision-1.6`, draft PR #77; release HOLD.

## Gap and scientific reasoning

Earlier 1.0–1.5 functionality and the existing 1.6 class/visibility,
comment, assignment, bulk triage and typed executable Workflow Builder were
audited before this change. Existing manual-review event validation rejects
blank, oversized and NUL-containing labels, but it did not reject Unicode
bidirectional formatting controls in a self-reported reviewer name. A saved
actor such as `scientist + U+202E + other` can render in a different visual
order from its stored identity, making scientific-review attribution misleading.
The same defect exists in imported/restored review-event history.

## Behavior

- Reject only nine Unicode **directional formatting controls** U+202A–U+202E
  and U+2066–U+2069 in new actor and assignee labels from manual coordination,
  individual triage and bulk triage; return 422 before idempotency-key use.
  Natural Arabic/Hebrew text and comments are not blocked by this rule.
- Detect those characters in **all** restored/imported actor/assignee history
  for selected items, including off-page events. Return a non-disclosing 409
  before history reads, new comments/assignments, single-item/bulk triage or
  keyed replay. Do not normalize, repair, drop or overwrite historical events.
- Preserve scientific images, annotation approval requirements, model weights,
  saved Workflow Builder graphs, typed `review_queue_reference`, dimensionless
  priority scores and full provenance. The self-reported reviewer label remains
  **not an authenticated identity**; this only protects display integrity.

## Verification and release limitation

`test_review_queue_direction_controls_16.py` covers standalone and genuinely
saved executable QC workflow queues, original event replay after fixture-only
restoration, manual/bulk/single fail-closed paths, unchanged pending review and
acceptance of natural RTL names. This source change requires exact-head CI
Ruff, mypy, backend pytest, frontend tests/E2E and migration checks. A synthetic
fixture is not an independent scientific-data validation.

1.6 is not approved for release: independent reconciliation of the conflicting
1.1/1.6 Alembic-0038 histories, representative biological review, genuine
Windows MSI/CAB installation/upgrade/rollback, installed-GUI acceptance and
explicit researcher signoff remain outstanding. Do not auto-merge, publish,
download unapproved pretrained weights or modify user research assets.
