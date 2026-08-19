# Phase 10 — Executable Workflow Graphs

## Scope

Phase 10 is now an executable scientific ML orchestration layer rather than a planner-only foundation. ReefVision persists immutable graph revisions and executes supported nodes while preserving project, dataset, model, job, review, and artifact provenance.

The workflow system intentionally orchestrates established ReefVision operations instead of executing arbitrary user code.

## Implemented execution model

Workflow graphs support:

- persistent graph definitions, revisions, and deterministic checksums
- persistent workflow runs and per-node run state
- typed input/output artifacts with lineage
- dependency-aware scheduling
- cancellation propagation to linked child jobs
- retry-safe execution and resumable runs
- explicit `waiting_for_review` states for human review gates
- resume after review without rerunning completed upstream nodes
- visual editing with draggable nodes, typed ports, connections, parameter editing, zoom, status overlays, run inspection, and reusable templates

## Data types

The graph type system includes:

- project references
- image collections
- immutable dataset versions
- registered model references
- training results
- classification datasets
- source videos
- existing box and mask annotations
- detection proposals and detection consensus
- mask proposals and mask consensus
- classification predictions and classification consensus
- reviewed boxes, masks, and labels
- measurement tables
- depth artifacts
- video tracks
- active-learning rounds/review handoffs
- model evaluation/comparison artifacts
- project exchange packages

## Executable node families

### Sources

- Current Project
- Project Images
- Immutable Dataset Version
- Registered Model
- Project Video
- Verified Masks

### Training and dataset versioning

- Create Dataset Version
- Detection training/retraining
- Instance-segmentation training/retraining
- Semantic-segmentation training
- Classification dataset materialization
- Classification training
- Register Trained Model

### Inference and auto-labeling

- Detection Inference
- Instance/Semantic Segmentation Inference
- Classification Inference
- Prompt Assist masks
- Relative Depth
- provider-neutral cloud VLM detection/classification with explicit cloud opt-in
- N-of-M detection, classification, and mask consensus

### Human review

- Detection Review Gate
- Mask Review Gate
- Classification Review Gate

Review gates pause a workflow. Predictions remain proposals until a human completes the established ReefVision review path.

### Scientific analysis

- Coral mask measurements
- detection/classification/mask evaluation
- same-dataset Model v1 vs Model v2 comparison
- video tracking
- calibrated metric-depth reconstruction into typed `video_3d_trajectories` artifacts

### Active learning and interchange

- persisted Active Learning acquisition/review handoff
- post-review immutable dataset creation
- Project Exchange export

## Representative templates

The desktop ships reusable graph patterns including:

- GPT + Gemini + Claude 2-of-3 Auto Label
- local detector 2-of-3 consensus
- classification 2-of-3 consensus
- mask 2-of-3 consensus
- detection training and evaluation
- classification training and evaluation
- review → Dataset v2 → retrain → compare Model v1/v2
- committee Active Learning → review → Dataset v2 → retrain
- equal-budget Random vs Committee Active Learning experiment
- detection → SAM/SAM2 → mask review → coral measurements

## Reproducibility and safety

- Graph revisions and execution artifacts are checksummed.
- Dataset creation uses ReefVision's immutable dataset-version contract.
- Training and inference retain dataset/model/checkpoint/settings lineage.
- Cloud VLM execution requires explicit runtime opt-in and does not persist API credentials in workflow artifacts.
- Consensus artifacts retain exact voter provenance and disagreements rather than silently promoting predictions.
- Human review gates never auto-accept model output.
- Parent workflow cancellation propagates to linked child jobs.
- Project Exchange preserves workflow graphs, runs, node runs, and file-backed artifacts with integrity checks.

## ReefVision 1.0 acceptance boundary

The workflow feature is considered software-complete only when the current 1.0 branch passes repository-wide backend/frontend tests, migration validation, packaged Windows acceptance, restart/project round-trip checks, and representative end-to-end scientific workflows. Real checkpoint and biological validation remain required for claims about model or tracking accuracy; synthetic tests establish software behavior, not scientific performance.

The 1.0 release gate must exercise at least these end-to-end journeys:

1. import/annotate/review → immutable dataset → detection training → inference → review → Dataset v2
2. segmentation training/inference → mask review → coral measurements/export
3. classification dataset → training → inference → review/evaluation
4. Active Learning acquisition → human review → immutable feedback dataset → retraining/model comparison
5. video import → detector tracking → track review → behavior/scientific exports
6. detection → Prompt Assist/SAM2 → mask review → measurements
7. local/cloud multi-model consensus with explicit disagreement review
8. depth inference and depth-aware analysis where appropriate calibration/depth inputs exist
9. calibrated video → verified tracks → metric depth → `video_3d_trajectories`
10. Project Exchange export → import as a new project → restart → preserved video calibration and camera intrinsics → remapped tracks, workflows, and artifacts → reproducible calibrated 3D analysis using only imported IDs

## Remaining release validation

### Automated software acceptance

The unified ReefVision 1.0 workflow runs backend lint, formatting, typing, unit and scientific workflow tests, canonical migration round-trip validation, frontend formatting/typing/unit/E2E/build checks, and Windows MSI build plus administrative extraction and packaged-sidecar self-test.

### Scientific, hardware, and clean-machine release evidence

The current implementation still requires execution of the complete gate on functioning CI/Windows runners and representative data. In particular:

- real detection, segmentation, and classification training/inference on representative coral datasets
- real SAM2 and Depth Anything checkpoint acceptance on CPU/CUDA, including unavailable-device/OOM recovery
- real ByteTrack vs BoT-SORT comparison against manually scored fish footage
- Active Learning efficiency comparison at equal annotation budget
- depth/physical-calibration validation with appropriate camera/depth data
- clean Windows install, restart, upgrade/uninstall, and project round-trip acceptance

These are release and scientific-validation requirements; they are no longer deferred product features.
