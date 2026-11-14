# ReefPose Scientific Evaluation Design

## Intent

Add the first Phase 3 scientific vertical slice: reproducible evaluation of a registered ReefPose checkpoint against a distinct immutable, scientist-verified pose dataset. The result must quantify localization, visibility, confidence calibration, and runtime without treating successful execution as biological validation.

## Scope

- Pure, independently testable pose metrics: Euclidean error, configurable PCK, NME, per-landmark summaries, visibility precision/recall, confidence Brier score/ECE/threshold analysis, and OKS only when explicit sigmas and a valid reference area are supplied.
- Persisted evaluation runs bound to model checksum, held-out dataset manifest checksum, schema identity, configuration, software/runtime metadata, predictions, metrics, warnings, and integrity hash.
- Leakage safeguards: the evaluation dataset must differ from the model's recorded training dataset and manifest, and its anatomy schema must exactly match the checkpoint registration.
- Actual native ReefPose inference over the frozen source video frames, with measured latency and throughput.
- JSON and CSV export, list/detail API, and a Model Hub action/result view.

## Non-goals

- No scientific accuracy claim from synthetic fixtures.
- No automatic checkpoint download.
- No new annotation or dataset subsystem.
- No partial multi-animal identity tracker or behavior detector in this slice. Existing video tracking evaluation remains the basis for later IDF1 work.
- No cross-provider metric execution until their pose schema and output identity contracts can satisfy the same strict evaluator.

## Approach

The selected approach is a small domain metrics module plus an application service using the existing immutable pose datasets, video storage, ReefPose predictor, model registry, and API conventions. A new evaluation-run table stores immutable results. This is preferred over embedding metrics in training runs because held-out evaluation may compare checkpoints after training, and over storing results only in model metadata because multiple datasets/configurations must remain independently reproducible.

## Scientific rules

- Visible reference landmarks contribute to localization metrics. Missing predictions count as incorrect for PCK and are represented explicitly, but do not fabricate a Euclidean distance.
- NME requires a positive declared normalization length. The default service normalization is the diagonal of the verified animal bounding box; runs lacking a valid normalization are rejected rather than silently normalized by image size.
- OKS is omitted with a warning unless every evaluated landmark has a positive sigma and the reference instance has positive area.
- Confidence calibration treats reference-visible/prediction-within-threshold as the binary correctness target and includes absent predictions at confidence zero.
- Stable landmark IDs are the primary join key. Names and order are not used to reconcile incompatible schemas.
- Evaluation dataset identity and content hashes are rechecked at execution time.

## Compatibility

The change adds migration `0039_pose_evaluation_runs.py` and typed API contracts. Existing Phase 1–2C models, datasets, Ultralytics/SLEAP providers, workflows, and annotations are unchanged. Evaluation results are additive and project-scoped.

## Remaining roadmap

The next slices should add provider-neutral pose adapters and asynchronous/cancellable batch evaluation, then multi-animal pose identity association/IDF1, followed by calibrated anatomical measurements and rule-based cycle detection.
