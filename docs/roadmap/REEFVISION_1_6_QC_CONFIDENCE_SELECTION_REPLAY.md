# ReefVision 1.6 — frozen confidence-selection QC replay

## Audited existing behavior

The standalone review-queue generator selects pending model predictions with
`confidence <= review_below_confidence` when a threshold is supplied. An image
without any selected pending prediction is omitted from that queue. The saved
`qc_review_queue` Workflow Builder node already preserves the threshold,
scoring weights, immutable item evidence, persisted graph/run provenance,
researcher review gate and idempotent replay. This change extends that existing
validator; it does not introduce a duplicate node or recompute live predictions.

## Reproducibility invariant

For new `qc-review-queue-v3` snapshots only, a saved confidence-filtered queue
must have **at least one selected pending proposal per item**. The persisted
`low_mean_confidence` signal is `1 - mean(selected confidences)`; therefore
`low_mean_confidence >= 1 - review_below_confidence` within a small floating
point tolerance. A re-signed checksum cannot authorize an image with zero
selected proposals or a selected mean confidence above the configured cutoff.
No interpretation as calibrated probability, ground truth or biological
verification is implied.

This is intentionally a frozen-evidence check: a workflow retry never looks up
new live model predictions, edits a researcher's comments/assignments/review
state, or rewrites a prior queue. Historical unversioned and v2 queues keep
their compatibility behavior.

## Regression and acceptance boundary

`test_workflow_review_queue_integrity_16.py` exercises a valid thresholded
saved snapshot, a re-signed snapshot with no selected proposals, and a re-signed
snapshot whose selected mean confidence exceeds the original cutoff. It also
checks that pending researcher coordination state survives validation failure.
Existing API and saved-graph Workflow Builder regressions remain in place.

Full acceptance still requires exact-head Ruff, mypy, pytest, migration and
frontend/E2E CI, scientific representative-image checks, independent
cross-version Alembic revision-0038 reconciliation, and Windows MSI/CAB
upgrade/rollback and installed-GUI testing. No merge, release, model download,
hosting, or research-asset deletion is authorized by this change.
