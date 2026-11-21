# ReefPose Phase 3 scientific evaluation validation

Validated on 2026-11-12 from branch `feature/reefpose-core`. All evaluation
inputs used for engineering validation were synthetic. These results do not
establish biological accuracy, cross-species validity, or publication fitness.

## Phase 2C recovered baseline

The unreported historical-checkpoint compatibility commit was recovered as
`0cd4f568`. Independent review found that a historical v1 hash could authorize
new `required` or symmetry fields. A negative checkpoint regression test was
observed failing, the parser was changed to accept stripped historical hashes
only when those fields are absent, and the focused checkpoint/schema/data suite
passed (26 tests). The fix is commit `4938a250`.

## Delivered Phase 3 vertical slice

- Framework-neutral, stable-landmark-ID scoring for Euclidean localization
  error, configurable PCK, matched-landmark NME with explicit coverage,
  per-landmark metrics, visibility precision/recall, confidence Brier score,
  expected calibration error, confidence-threshold curves, and conditional
  OKS.
- OKS is omitted with a warning unless positive reference area and explicit
  positive per-landmark sigmas are available.
- Immutable project-scoped evaluation runs bind the model checkpoint checksum,
  held-out dataset manifest checksum, exact anatomy schema identity, truth and
  normalization policies, configuration, predictions, metrics, warnings,
  measured inference time, and a canonical result checksum.
- Training and validation/model-selection dataset IDs and manifest hashes are
  rejected as leakage. The evaluator independently verifies the dataset
  manifest, each item snapshot and verified-pose fingerprint, and the current
  source-video bytes before inference. Schema mismatches, mutated checkpoints,
  changed source videos, invalid normalization, and incomplete datasets fail
  closed.
- ReefVision schema content hashes and native ReefPose anatomy integrity hashes
  are validated as separate identities. Native Torch imports are lazy, so API
  startup remains available when the optional runtime is not installed.
- Confidence calibration includes confident visibility false positives, and
  persisted provenance records ReefVision, Python, Torch, CUDA, requested
  device, and the device actually resolved by the predictor.
- JSON and per-landmark CSV exports are available through typed API routes.
- Model Hub filters selectable held-out datasets by exact schema and excludes
  recorded training/validation sources, launches native evaluation, displays
  PCK/NME/error/coverage/runtime/warnings, and links both exports.
- Migration `0039_pose_evaluation_runs.py` upgraded, downgraded to 0038, and
  upgraded again on an isolated SQLite database.

## Automated validation

- Ruff format check: passed (663 backend files).
- Backend Ruff lint: passed. The repository-wide check still reports 15
  unrelated pre-existing findings across acceptance/validation scripts, and
  the repository-wide format check identifies 12 unrelated files; none were
  modified in this milestone.
- mypy: passed (427 source files).
- Focused metric, service/API, compatibility, and migration tests: passed.
- Frontend Prettier and TypeScript checks: passed.
- Frontend Vitest: 94 files, 499 tests passed.
- Production Vite build: passed; the existing large-chunk advisory remains.
- Full non-optional backend suite: 1,430 passed, 34 skipped in 724.29 seconds.
  The run used a short Windows temp root and pinned `PYTHONPATH` to this
  worktree. Seven previously observed failures were reproduced as Windows path
  length errors under the default temp root; the bootstrap failure was an
  editable-install path resolving to the sibling ReefVision worktree. The 30
  affected tests pass under the corrected setup.
- The separate `test_pose_interoperability_runtime.py` module remains excluded
  because its pinned optional SLEAP runtime is unavailable. No dependency was
  installed or changed.

## RTX 3090 engineering evidence

The native Phase 3 evaluation integration ran one synthetic frame through a
real ReefPose-S checkpoint on CUDA, synchronized timing, persisted the
scientific result, and re-read its metrics.

- Device: NVIDIA GeForce RTX 3090
- Test runtime: PyTorch 2.5.1+cu121, CUDA 12.1
- Inference latency: 150.5444 ms/image (cold, single synthetic frame)
- Throughput: 6.6426 images/s (cold, single synthetic frame)
- Peak allocated CUDA memory: 9,822,208 bytes
- Stable visible landmarks matched: 2 / 2
- Evaluation result SHA-256:
  `d6bdaa1a6b1002cde1de5b5b33d9a67cb0216057d39f24dd11be704bc71ce2cc`

The requested `C:\AI-Projects\venvs\reefpose` PyTorch 2.11.0+cu128 runtime
could not currently load because Windows Application Control blocked
`torch\lib\shm.dll` (WinError 4551). No dependency was changed or reinstalled.
The earlier Phase 2C CUDA evidence remains the validation record for that exact
runtime configuration.

## GUI evidence

The Model Hub evaluation interaction is covered by a real React component test
that selects only the unused compatible dataset, invokes the typed POST
contract, displays persisted metrics and runtime, and verifies the CSV action.
The full frontend suite and production build pass. This slice was not exercised
through native Tauri or a new browser end-to-end acceptance fixture, so no such
claim is made.

## Remaining limitations

- Evaluation execution is synchronous. Larger datasets need a persisted,
  cancellable background job with progress and batched inference.
- Only native ReefPose checkpoints are accepted. Provider-neutral Ultralytics
  and SLEAP comparison requires strict stable-ID schema adapters.
- Model comparison is currently performed from the persisted run list; a
  dedicated distribution/chart comparison view is not yet implemented.
- The workflow node registry does not yet expose the evaluation operation.
- No real biological dataset, inter-annotator baseline, calibrated OKS sigmas,
  or scientific acceptance threshold has been supplied.
- Multi-animal pose identity metrics, anatomical measurements, and behavior
  cycle analysis remain subsequent Phase 3 slices.

## Recommended next milestone

Implement asynchronous provider-neutral evaluation and a Workflow Builder
`Evaluate Pose Model` node, including progress/cancellation, multi-checkpoint
comparison plots, error-example review, and real held-out biological fixtures.
Then extend the existing video tracker with pose-aware association and IDF1
before adding calibrated anatomical measurements and rule-based cycle counts.
