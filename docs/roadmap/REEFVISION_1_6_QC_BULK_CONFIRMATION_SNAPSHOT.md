# ReefVision 1.6 — QC bulk confirmation bound to visible evidence

Track D / master issue #76; isolated draft PR #77. Development-only.

## Gap audited

The existing 1.6 manual bulk QC endpoint is atomic, idempotent and explicitly
researcher-gated; standalone and persisted typed Workflow Builder QC queue
execution already exist. The dashboard's selection is restricted to currently
eligible items, but a background query refresh can change an item's review
state **after** the researcher confirms the action. Previously the confirmation
booleans remained true even if the selected count, image identity or item state
changed, allowing a different bulk action scope than the one reviewed.

## Change

Bind both manual triage and individual-inspection confirmations to a local
snapshot containing queue ID, requested action, selected item IDs, image IDs,
rank positions, review states, source input checksums, QC scores, highest QC
severity, and item update timestamps. Even when item IDs and eligibility stay
unchanged, a background scientific-evidence refresh requires new confirmation. A changed snapshot immediately unchecks the
controls and disables submission; changing away and back also clears old
confirmation tokens. The researcher must reconfirm the currently visible
eligible items. This is a UI safety guard, not an authorization substitute:
server-side state validation, idempotency, append-only reviewer audit history,
and the separate explicit human review gates remain authoritative.

## Regression and acceptance

Component tests simulate an in-place background item refresh while two skip
items remain eligible, then a completion candidate becoming ineligible and
returning. Both cases require fresh confirmation and forbid implicit API calls. Four
parameterized completion regressions additionally simulate checksum, score,
severity and timestamp changes without altering the selected item IDs or review
state. Returning to an earlier snapshot cannot restore approval.
The existing explicit confirmed-completion and same-request-ID retry tests
remain in place. No new scientific workflow node is appropriate for this
manual UI confirmation: the existing executable `qc_review_queue` node,
typed dimensionless score artifact, saved graphs/runs, provenance and review
gates are unchanged.

The previous head `c2682782` failed frontend Prettier on a single checkbox
callback; backend CI passed. The exact formatter change is included with this
evidence-refresh hardening. No native GUI or Windows MSI acceptance is claimed.

Release HOLD until exact-head frontend formatting/type/Vitest/E2E/build,
backend CI, migration lineage integration, native Windows MSI upgrade/rollback,
installed-GUI and representative biological-data acceptance are verified.
No merge, release, paid hosting, pretrained weights or user-data deletion.

## Full-row evidence integrity follow-up (2026-10-31)

A partial import or corrected review-queue response may change biological
reason text, class evidence, model IDs, related QC issue IDs, normalized
signals, score components, or dataset provenance **without** changing the
score, input checksum, item state, or update timestamp. The previous narrow
fingerprint could therefore leave a prior manual approval checked against a
different evidence row.

The bulk triage confirmation now fingerprints the complete server-provided
selected review-item record, together with queue, action, reviewer label and
skip rationale. Any changed selected field invalidates both confirmation
checkboxes immediately. A subsequent return to old evidence cannot revive
approval because the existing confirmation-reset effect remains. Full-row
comparison is deliberately conservative: harmless representation changes can
require reconfirmation, but must never silently preserve approval of changed
scientific evidence.

Seven additional parameterized frontend regressions exercise changed biological
reason, class IDs, model IDs, linked issue IDs, normalized signal, score
breakdown and dataset provenance while keeping IDs, state, score, checksum and
timestamp unchanged. Each must disable submission, clear both approvals, and
avoid API calls; restoring the original row must not revive approval.

This is an **existing standalone manual QC UI safeguard**, not a new analysis
feature. The pre-existing executable, typed, persisted `qc_review_queue`
Workflow Builder node and API are unchanged. This does not establish scientific
verification or crash-safe persistence. Release remains on HOLD pending
exact-head frontend/backend/Workflow Builder checks, cross-version migration
reconciliation, installed Windows MSI/GUI and representative scientific data.
