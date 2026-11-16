# ReefVision 1.6 — frozen QC confidence-filter scientific contract

The standalone **dataset-version review queue** and typed, saved
`project_source → dataset_version_source → qc_review_queue` graph operate
on an immutable annotation snapshot. This snapshot does **not** include
pending model-prediction proposals or their confidence values.

Previously, setting `review_below_confidence` on a frozen version silently
filtered out every image and committed a `complete` queue with zero items.
That could misleadingly imply biological review had finished, although
no observation had been examined.

New version-scoped queues reject that parameter **before** any queue insertion
or review-state change. Workflow Builder also reports
`unsupported_frozen_qc_confidence_filter` on the QC node at graph-planning
time. A project-only queue still supports confidence filtering of pending,
unreviewed model proposals. Remove the confidence filter to rank the frozen
version's annotated images.

Regression coverage targets standalone atomic rejection, unaffected live
project filtering, saved typed graph-plan rejection, and successful persisted,
checksummed, dimensionless, human-pending frozen workflow execution.

**Limits:** This is not biological verification, model evaluation, or migration
reconciliation. Historical queues, researcher decisions, and saved runs remain
unchanged. No pretrained downloads, remote services, or new measurements.
Actual Windows MSI/CAB installation, upgrade/rollback, representative
biological acceptance, and independent 1.1/1.6 Alembic-0038 reconciliation
remain release blockers.
