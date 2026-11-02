# ReefVision 1.6 — frozen QC temporal provenance on saved-workflow retries

## Existing scope and scientific gap

The existing 1.6 QC generator and executable Workflow Builder `qc_review_queue`
node already support project-scoped and immutable dataset-version review queues.
The generator correctly treats `recent_import` and `stale_review_state`
as unavailable (both zero) for frozen dataset versions: dataset-version items
do not snapshot image import/edit timestamps. Live project queues can still
use the original image chronology.

The v3 saved-queue validator previously checked numeric normalization and
the item evidence digest but did not enforce the **dataset-specific zero
temporal-signal contract**. A re-signed snapshot could therefore assign
nonzero priority to a fabricated frozen import/edit chronology while keeping
the other evidence, score and review state consistent.

## Implementation and test contract

For **v3 dataset-version queues only**, the saved-queue integrity validator
rejects any nonzero raw `recent_import` or `stale_review_state` signal.
It runs on the existing Workflow Builder idempotent replay path before
returning an artifact; it does not query mutable live images or rewrite
researcher decisions. The existing v3 normalized-signal and score checks
continue to apply. Live project queues and historical v2 snapshots retain
their original semantics.

`test_workflow_review_queue_frozen_temporal_integrity_16.py` covers:

- A coherent frozen v3 snapshot and two independently re-signed temporal
  fabrications with zero-weight signals, proving the new check is not merely
  the existing score/digest validator.
- Standalone versus executable saved
  `project_source → dataset_version_source → qc_review_queue` parity for
  real persisted frozen evidence, including typed inputs and saved output.
- A re-signed saved-workflow queue with fabricated frozen chronology,
  rejection on retry, database rollback, successful replay of the original
  queue, and preservation of the mandatory researcher-review state.

These are **priority signals**, not validated environmental measurements,
biological observations or ground truth. No new Workflow Builder node,
migration, pretrained model, cloud dependency or automatic scientific
approval is introduced.

## Release hold

Exact-head CI, representative biological-data review, independent 1.1/1.6
Alembic revision-0038 reconciliation, Windows MSI/CAB upgrade/rollback,
installed-GUI and hardware validation remain required. Do not merge or
release based solely on this integrity regression.
