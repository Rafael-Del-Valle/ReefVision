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
rank positions, review states, source input checksums, QC scores, highest QC\nseverity, and item update timestamps. Even when item IDs and eligibility stay\nunchanged, a background scientific-evidence refresh requires new confirmation. A changed snapshot immediately unchecks the
controls and disables submission; changing away and back also clears old
confirmation tokens. The researcher must reconfirm the currently visible
eligible items. This is a UI safety guard, not an authorization substitute:
server-side state validation, idempotency, append-only reviewer audit history,
and the separate explicit human review gates remain authoritative.

## Regression and acceptance

Component tests simulate an in-place background item refresh while two skip
items remain eligible, then a completion candidate becoming ineligible and
returning. Both cases require fresh confirmation and forbid implicit API calls. Four\nparameterized completion regressions additionally simulate checksum, score,\nseverity and timestamp changes without altering the selected item IDs or review\nstate. Returning to an earlier snapshot cannot restore approval.
The existing explicit confirmed-completion and same-request-ID retry tests
remain in place. No new scientific workflow node is appropriate for this
manual UI confirmation: the existing executable `qc_review_queue` node,
typed dimensionless score artifact, saved graphs/runs, provenance and review
gates are unchanged.

The previous head `c2682782` failed frontend Prettier on a single checkbox\ncallback; backend CI passed. The exact formatter change is included with this\nevidence-refresh hardening. No native GUI or Windows MSI acceptance is claimed.\n\nRelease HOLD until exact-head frontend formatting/type/Vitest/E2E/build,
backend CI, migration lineage integration, native Windows MSI upgrade/rollback,
installed-GUI and representative biological-data acceptance are verified.
No merge, release, paid hosting, pretrained weights or user-data deletion.
