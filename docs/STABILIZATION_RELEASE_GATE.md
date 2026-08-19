# ReefVision 1.0 full-platform release gate

**Status:** full 1.0 development reopened; release freeze applies only after feature-complete acceptance

**Integration branch:** `feat/1.0-full-platform`

**Draft PR:** `#29`

**Original stabilization baseline:** `f52a90afeffda0f59df93c9dc5998f22a99b53c1`

## Purpose

ReefVision 1.0 is the complete scientific computer-vision platform. Capabilities that were previously described as later-phase or 2.0 work are now required for the initial 1.0 release. The release must therefore demonstrate not only the original image annotation and detection journey, but also segmentation, classification, Prompt Assist, active learning, video tracking and behavior analysis, depth/RGB-D measurements, scientific interchange, fusion workflows, provider lifecycle, recovery, and a reliable Windows desktop package.

Production development is intentionally reopened on `feat/1.0-full-platform`. Provenance, immutable dataset and workflow revisions, review-before-accept behavior, calibration warnings, safe model loading, and all release-validation gates remain mandatory while features are completed.

No capability may be called release-ready from source inspection alone. Each gate below requires executable evidence.

## Required order

### Gate 1 — complete automated validation

Run from the repository root on Windows:

```powershell
.\scripts\run-release-validation.ps1
```

Required results:

- Ruff lint passes.
- Ruff format check passes.
- Strict mypy passes.
- Complete backend pytest passes.
- Alembic upgrades to head, downgrades through the supported boundary, downgrades to base, and re-upgrades to head.
- Frontend lockfile validation and `npm ci` pass.
- Prettier, TypeScript, Vitest, production build, and Playwright pass.
- Rust formatting and `cargo check` pass.
- Tauri MSI packaging and packaged API-sidecar smoke pass.

The generated JSON summary and every individual log under `.artifacts/release-validation-*` are release evidence. A failed gate remains failed even when a later gate succeeds.

### Gate 2 — core image annotation and scientific measurement

The deterministic coral journey must cover:

1. Create an octocoral project.
2. Import representative PNG/TIFF images.
3. Confirm thumbnails, dimensions, source IDs, and checksums.
4. Create and edit boxes, polygons, brush/raster masks, and assisted masks.
5. Confirm undo/redo, instance labels, review states, and persistence after restart.
6. Calculate calibrated area, perimeter, centroid, density, TLE, and supported surface-area approximations.
7. Preserve the calibration source, assumptions, units, and warnings with every scientific result.
8. Create an immutable group-aware dataset version.
9. Re-open the project after API restart and confirm all IDs, revisions, and managed files remain valid.

The focused test remains `test_stabilization_coral_journey.py`, supplemented by mask conversion and measurement validation tests. Synthetic data does not replace a manual installed-app journey with representative coral imagery.

### Gate 3 — detection, segmentation, and classification

All three primary supervised task families must work end-to-end.

**Detection**

- create/freeze a compatible dataset;
- train a supported detector;
- inspect metrics and checkpoints;
- register the resulting model;
- run inference;
- review, correct, accept, and reject predictions;
- compare model output against reviewed ground truth.

**Instance and semantic segmentation**

- create editable mask datasets;
- train at least one native/supported segmentation provider;
- exercise SAM-family assisted annotation;
- run segmentation inference and review;
- evaluate IoU/Dice plus thin-structure/boundary behavior;
- demonstrate nnU-Net integration when its external environment is configured.

**Classification**

- create independent label sets for image/region/mask/fragment targets;
- support single- and multi-label scientific questions;
- freeze reviewed classification snapshots;
- train/register supported classifiers;
- run predictions and bulk review;
- compare competing model outputs;
- export joined scientific assignments to CSV and NumPy.

### Gate 4 — Prompt Assist and provider lifecycle

Validate all enabled 1.0 assist-provider paths that can be executed in the release environment.

Required behavior:

- positive/negative point prompts;
- box prompts;
- brush/refinement interaction where supported;
- provider/model readiness and health reporting;
- safe local model registration and checksum verification;
- sidecars constrained to configured localhost endpoints;
- explicit model/provider provenance on generated predictions;
- no silent automatic acceptance of generated labels.

For real multi-model consensus, use a manually reviewed subset with stable image IDs and ground-truth masks. Record model/provider versions, prompts, thresholds, request counts, failures, latency, and API cost when applicable. Compare consensus against individual branches using precision/recall, mask IoU/Dice, thin-structure retention, class/state false positives and false negatives, and human correction time.

Provider agreement is not ground truth.

### Gate 5 — active learning cycle

Run a complete active-learning cycle using immutable data/model provenance.

Required evidence:

1. generate/reuse embeddings for the candidate pool;
2. create review batches using uncertainty/confidence strategies;
3. exercise diversity strategies including k-center/farthest-point or clustering;
4. exercise at least one combined uncertainty/diversity strategy;
5. exercise ensemble disagreement when multiple prediction sets exist;
6. apply group/fragment limits and class-balance settings;
7. allow explicit manual priority/exclusion without losing provenance;
8. review selected samples;
9. promote reviewed samples into a new immutable dataset version;
10. retrain/evaluate a candidate model and preserve cycle history.

Given the same candidate set, seed, configuration, and embeddings, deterministic selectors must reproduce the same ranking.

### Gate 6 — video, tracking, and behavior analysis

Use representative fish or other marine-organism footage.

Required evidence:

- import managed video with media metadata;
- launch detector-backed ByteTrack and BoT-SORT paths where supported;
- persist stable track identities and observations;
- add/edit/delete/restore manual observations;
- split, merge, reassign, and archive tracks without corrupting history;
- evaluate tracking against reviewed ground truth;
- calibrate distance-per-pixel when physical motion units are claimed;
- calculate trajectories, distance, speed, acceleration, turning, occupancy, zone use, heatmaps, wall distance, and schooling metrics where mathematically applicable;
- clearly distinguish pixel-relative results from calibrated physical results;
- render annotated, trajectory, and heatmap video outputs;
- export scientific track/behavior data and reopen it without losing identity/provenance.

### Gate 7 — depth and RGB-D scientific analysis

Required evidence:

- generate monocular relative-depth maps with an enabled provider;
- import or create metric depth where calibration permits;
- retain provider/model/checksum provenance for every depth map;
- compute mask depth statistics and depth-aware area/centroid outputs;
- block or warn on unsupported physical interpretations of relative depth;
- combine aligned masks and depth maps inside a fusion workflow;
- confirm misaligned dimensions or incompatible sources fail explicitly;
- exercise any enabled RGB-D training/inference path with deterministic data alignment.

### Gate 8 — fusion workflow graph

The visual node editor is a release-defining 1.0 capability.

Required evidence:

- drag/create supported nodes and connect typed ports;
- reject cycles, missing required ports, incompatible artifact types, and incompatible model tasks;
- synchronize the visual graph with typed JSON without data loss;
- save the graph as a persisted workflow;
- save immutable revisions with checksums;
- launch a pinned revision from the desktop UI;
- execute detection/segmentation/classification/tracking/measurement/behavior/active-learning/depth/export stages where configured;
- preserve artifact lineage and cache keys;
- show live run status;
- recover from a failed node without rewriting successful upstream artifacts;
- retry partial runs with optional compatible cache reuse;
- preview cleanup before any file removal;
- quarantine selected managed outputs reversibly and restore them safely.

Measurement nodes must call the same production scientific measurement services used by the direct APIs. Behavior nodes must call the full video behavior engine. Active-learning nodes must call the production selector registry rather than metadata-only placeholders.

### Gate 9 — external interchange and scientific exports

Use `scripts/validate-external-interchange.ps1` plus real consumer applications where practical.

Required formats/workflows include the supported COCO detection/instance/panoptic, CVAT, LabelMe, Roboflow COCO, and Roboflow YOLO paths, plus ReefVision scientific CSV/JSON/NumPy exports exposed by measurement/classification/video systems.

Required checks:

- preview before mutating imports;
- explicit class mapping/conflict behavior;
- filename/source-ID matching and dimension checks;
- box, polygon, raster/RLE and panoptic geometry where supported;
- source IDs and manifest/checksum preservation;
- round-trip geometry fidelity within defined tolerances;
- import/export into real external consumers for acceptance testing;
- credentials supplied only through environment variables;
- no secret values in reports or archives.

### Gate 10 — primary journey and expert workflow UX

The standard user should not need to understand internal graph execution to complete ordinary work, while expert users retain the workflow editor.

The normal path should remain obvious:

```text
Create project
→ Import media
→ Define or confirm classes/tasks
→ Annotate/review
→ Create immutable dataset
→ Train or select model
→ Evaluate
→ Predict and correct
→ Measure/analyze
→ Export/report
```

Acceptance criteria:

- one obvious primary action per standard screen;
- advanced JSON available but not required for normal work;
- consistent language for project, dataset, model, prediction, review, workflow, and export;
- clear readiness/error states for local providers and sidecars;
- expert workflow controls remain accessible;
- long-running jobs expose progress, cancellation where safe, terminal state, and actionable failure messages.

### Gate 11 — Windows MSI and clean-machine acceptance

Run:

```powershell
.\scripts\run-complete-release-validation.ps1 -PerformMachineInstall
```

Required evidence:

- MSI is produced for the intended target triple.
- Administrative extraction succeeds.
- Payload contains the desktop executable and `reefvision-api.exe`.
- Hash inventory is recorded.
- Installed application launches against a clean per-user data directory.
- API becomes healthy on loopback.
- A representative image project can be created, saved, closed, and reopened.
- At least one configured local model/provider can be exercised from the packaged application.
- A representative workflow can be saved and queued from the packaged UI.
- Silent uninstall succeeds without deleting the managed user-data directory.
- Path-length, sidecar discovery, model-storage, and multi-CAB/MSI behavior are tested on a clean Windows machine.

Signing is a separate release-policy decision. A signed candidate should also use `-RequireMsiSignature` and `-ExpectedPublisher`.

### Gate 12 — feature-complete release freeze and final regression

Only after Gates 1–11 have executable evidence:

1. mark the capability registry feature-complete for every required 1.0 capability;
2. re-enable a strict production feature freeze;
3. permit only defects, tests, documentation, release engineering, and explicitly reviewed exceptions;
4. run the full automated suite, all scientific acceptance suites, provider acceptance, interoperability, Windows packaging, and clean-machine smoke again from the release commit;
5. record the exact commit SHA, environment versions, GPU/provider versions, validation report paths, and manual observations;
6. tag 1.0 only from a commit for which every mandatory gate is passing or has a documented explicitly accepted external limitation.

## Current GitHub Actions limitation

GitHub Actions runs for the 1.0 PR are currently completing with **no recorded job steps** across Linux and Windows jobs. Those runs are not usable code diagnostics and must not be interpreted as test failures or passes. Investigate the repository/account runner or Actions provisioning state separately.

Until Actions can execute job steps, the authoritative executable validation environment remains the Windows checkout at:

```text
C:\Users\rafae\Documents\ReefVision\reefvision
```

Do not mark any gate passed from source inspection alone. Store the command, commit SHA, environment versions, output report, and manual observations for every pass.
