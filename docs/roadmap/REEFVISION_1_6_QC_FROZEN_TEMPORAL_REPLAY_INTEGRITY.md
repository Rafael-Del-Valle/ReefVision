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


## Frozen prediction evidence and selection replay (2026-11-25)

The frozen dataset QC context intentionally supplies no prediction rows. A v3
saved version-scoped queue must therefore have an empty prediction model ID
list for every item and an explicit null confidence filter, including when
the queue contains no items. A re-signed queue with an invented model
reference is not valid even if every prediction-derived signal is zero.
This does not prohibit preserved model provenance on reviewed annotations.
Live project queues and historical v2 snapshots retain their existing
contracts. The existing prediction-signal guard enforces zero model-derived
signals when no prediction models are present.

Regression coverage includes synthetic populated and empty snapshots, the
live-project positive control, and the existing standalone/saved executable
frozen QC parity and rollback/retry test expanded to reject invented model
references. Researcher review, dimensional units, original observations and
saved graph identity remain unchanged. This is not migration reconciliation
or installed Windows acceptance.


## Prediction-free count disagreement (2026-11-25)

The existing count-gap formula is absolute annotation/proposal count difference
divided by the maximum of the two counts and one. When there are no prediction
references, the proposal count is zero, so the only possible saved values are
zero (no annotations) or one (some annotations). Fractional gaps are still
possible with actual prediction references. This check applies to live and
frozen v3 snapshots without changing historical v2 or the scoring formula.
A value of one in a prediction-free queue is not evidence of poor model accuracy.
Regression checks cover re-signed weighted scores, both valid endpoints,
prediction-present controls, and standalone/saved frozen QC retry parity.

## Complete frozen image coverage (2026-11-25)

Frozen v3 QC queues disallow prediction-confidence selection. The original
dataset context enumerates every immutable version image, including images
without annotations. On saved-node replay, the independently validated
dataset manifest and typed dataset source now require complete image coverage
in addition to correct membership and split labels. A re-signed queue cannot
omit a coral observation (or claim an empty queue) while retaining a completed
review reference. Live queues and historical pre-v3 subset semantics remain
unchanged. The disposable regression verifies standalone coverage, saved
workflow rejection after re-signing the empty queue and output, and rollback
to the original pending researcher-review state. No research data or workflow
artifact is rewritten by the guard.

## Frozen annotation census replay (2026-11-25)

V3 saved frozen QC retries now reconcile detection class references, the
cohort-wide rare-class priority and the binary prediction-free count gap
against the independently validated immutable manifest census. Mask-only
observations remain excluded from the existing v3 detection scoring formula;
live classes and live predictions are not consulted. Re-signing the queue
and output cannot substitute a taxon or falsify these annotation-derived
signals. Standalone generation and saved graph regression cover parity,
re-signed class substitution, rare-class priority, an incorrect count-gap
endpoint, refusal and rollback to pending researcher review. No new scoring
version, migration or automatic biological approval is introduced.

## Frozen review status and biological grouping (2026-11-25)

The original image annotation status and biological group key are also part
of the authenticated frozen manifest. A re-signed v3 saved queue cannot
flip its binary unreviewed-state or missing-group priority while preserving
its aggregate score, even when the researcher assigns zero weight to those
signals. The replay checks use the same reviewed-status and Unicode-aware
blank-group semantics as standalone generation, never mutable live image
metadata or the queue's current researcher review decision. Two additional
standalone/saved graph regressions compare raw signals, flip each binary flag,
re-sign both the queue and output, require refusal, then roll back and replay
the original pending-review evidence. Historical pre-v3 queues are unchanged.
