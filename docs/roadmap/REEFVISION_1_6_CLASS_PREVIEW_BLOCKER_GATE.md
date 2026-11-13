# ReefVision 1.6 — class-operation preview blocker gate

## Verified gap and scope

The class management panel accepted a server preview with status `previewed` as sufficient to enable **Run reassign** and **Run Reassign and Delete**, even when the same plan carried protected blocking records, explicit blockers or failures. This was misleading alongside the visible scientific-risk warning. The backend retains checksum and reference validation, but the desktop must not invite execution of a blocked plan.

## Implemented contract

For both actions, the displayed preview is still tied to the exact project, class, target, audit notes and selection revision. A matching preview is **displayed** even when blocked so that the scientist can inspect the reasons. Execution is independently enabled only when the preview reports no blocking records, no blockers and no failures, with each expected evidence array present. Otherwise a visible message requires the issues to be resolved and a new preview. The mutation handler checks the same gate, not only the disabled button. Protected historical records and compatibility warnings that are not blockers remain visible and do not automatically prohibit a safe reassignment.

## Regression and boundaries

Six browser-component cases check three independent block signals across both operation types, requiring the preview to remain visible, Run disabled and zero execution HTTP requests. Existing positive checked-execution and stale-input regressions remain in place; simplified mock plans now include the required evidence arrays. No data migration or new workflow node is needed: the existing standalone and saved executable QC Workflow Builder retains typed outputs, persistent runs, provenance, retries and human review requirements. This UI safety check does not convert an unreviewed plan into a scientific result.

Release remains **HOLD** until exact-head lint/type/frontend/backend/E2E, migration reconciliation, representative biological saved-workflow and Windows MSI/installed-GUI upgrade/rollback gates pass.
