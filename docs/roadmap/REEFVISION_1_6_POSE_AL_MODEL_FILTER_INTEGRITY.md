# ReefVision 1.6 — saved pose Active Learning model-filter integrity

## Audited overlap and gap

ReefVision already has native local pose training/inference, temporal association,
pose Active Learning, frozen training datasets, typed executable Workflow Builder
graphs, saved runs, artifact checksums, and explicit scientist review gates.
Those capabilities were preserved; no duplicate workflow operation, migration,
external model, hosted inference, or automatic approval is introduced here.

The existing `pose_active_learning` Workflow Builder adapter previously filtered
an explicit `model_ids` parameter using `isinstance(value, str) and value`.
Malformed elements (including numbers, booleans and empty strings) disappeared
silently. A non-list parameter silently selected automatic models instead.
Repeated identifiers also survived adapter parsing and were deduplicated by
the round service. This made the executed source-model cohort differ from
the researcher's saved graph without an explicit error.

## Preservation contract

* Omitted or JSON-null `model_ids` and an empty list retain their established
  automatic locally registered model-discovery behavior.
* A nonempty explicit list must contain **unique, nonblank strings**. Its order
  and values are passed unchanged to `PoseActiveLearningRoundCreateRequest`
  and the existing project-scoped model validation. No trimming or fallback
  can change the intended cohort.
* The adapter rejects malformed explicit filters **before reading track state
  or creating a round**, so a failed workflow cannot silently substitute an
  unapproved source model.
* Successful rounds still use the existing typed
  `pose_active_learning_round` artifact, run provenance, persistent
  association inputs, selection SHA-256, and downstream researcher review.
  Model identities are identifiers, not measurements; pose coordinates and
  time-series quantities retain their existing unit contracts.

## Regression and release gates

`test_workflow_pose_al_model_filter_16.py` checks nine malformed explicit
filters at the standalone adapter boundary and saves/executes a real
`project_source → project_video_source → registered_model_source →
pose_inference → pose_temporal_association → pose_active_learning →
pose_active_learning_review_gate` graph with a malformed filter. The run must
fail without creating a pose Active Learning round or recording human approval.
The existing positive saved-pose-workflow tests remain backward-compatibility
controls.

These repository tests still require exact-commit CI verification. Full
release acceptance remains blocked on 1.1/1.6 Alembic-0038 reconciliation,
representative scientific source data, backend/frontend/E2E checks,
native Windows MSI/CAB installed-GUI clean install and upgrade/rollback,
and explicit researcher approval. Never silently repair or rewrite an
already-applied migration or researcher-controlled asset.
