# ReefVision 1.6 — biological identity bound to class-operation approval

## Audited gap

A saved Class Manager **Reassign** or **Reassign and Delete** preview checks exact record IDs, protected records, warnings, blockers and impacts. Previously, its SHA-256 checksum did not cover the *meaning* of either class. A name, scientific-name or biological-state edit after review left the same checksum and could cause the approved reassignment of observations or QC references into a biologically different category. The separate simple **Merge** endpoint already has 1.6 source/target identity checks; this closes the analogous persisted-preview gap without duplicating Merge.

## Implemented contract

- The preview checksum now includes source and target IDs, class names, numeric indices, scientific names, biological states, active flags and archive timestamps, alongside the existing record-ID groups and compatibility impacts. Full class snapshots already persist for researcher review.
- Before any writes, execute independently recalculates the plan and checksum. A changed biological identity returns HTTP 409 and marks the persisted operation `failed` / `preview_stale`; researcher must create and approve a new preview.
- Old pending previews created before this checksum expansion intentionally require re-preview. Historical records are neither rewritten nor migrated. No schema migration is needed.
- Existing blockers for mask annotations, mask history, image-level classifications, protected history and compatibility warnings remain unchanged.

## Verification and boundaries

Real-database API regressions cover source/target, name/scientific-name/state and Reassign/Reassign and Delete (12 combinations). Each asserts that a same-inventory semantic change yields 409, that annotations, predictions, QC and queue decisions remain linked to their original source, that the source/target persist and that the stale result is recorded. Existing tests separately cover an unchanged successful approved operation.

Manual metadata reassignment remains behind explicit researcher review; it is not a new inference, measurement or scientific analysis node. The already implemented typed executable QC Workflow Builder, saved-run provenance and approval gates are preserved, not bypassed or copied. Cross-process concurrency between final validation and transaction commit is a remaining risk. Full Actions, cross-version Alembic 0038 reconciliation, representative science and installed Windows GUI/MSI validation are independent release gates.
