# ReefVision roadmap status — July 18, 2026

## How to read these estimates

Two percentages are used because ReefVision now has several substantial workflows implemented in code but not yet fully accepted in the packaged Windows application.

- **Implementation** estimates how much of the planned code and user workflow exists.
- **Release readiness** estimates how much has completed automated tests, real-model smoke tests, restart persistence checks, and installed-desktop validation.

These are engineering estimates, not automatically calculated metrics.

## Current phase status

| Phase | Scope | Implementation | Release readiness | Current position |
|---|---|---:|---:|---|
| 1 | Multitask foundation | 98–100% | 85–90% | Desktop foundation, projects, images, classes, models, jobs, migrations, backups, diagnostics, and annotation architecture are present. Remaining risk is primarily full packaged-desktop regression validation. |
| 2 | Editable mask annotations | 95–98% | 80–90% | Revisioned polygon and raster masks, editing, storage, visibility, audit events, immutable snapshots, and exports exist. Remaining work is final usability hardening and installed-app acceptance on large projects. |
| 3 | Segmentation datasets, training, and inference | 85–90% | 60–70% | YOLO instance-segmentation export, training, registration, inference, polygon proposals, and review are implemented. nnU-Net semantic training, registration, raster inference, and review are also implemented. Real one-epoch provider runs, full regression tests, and packaged-app acceptance remain. |
| 4 | Coral measurements | 90–95% | 75–85% | Calibration, area, perimeter, centroid, bounds, contained-box density, filtered counts, total linear extension, surface-area models, project summaries, CSV, NumPy bundles, revision history, and immutable dataset snapshots exist. Scientific comparison against manual coral measurements and broader UI acceptance remain. |
| 5 | Classification | 10–15% | 5–10% | General class and model metadata can support classification later, but there is no complete image- or annotation-classification dataset, training, inference, and correction workflow yet. |
| 6 | Video and fish tracking | 20–25% | 10–15% | Video extraction jobs, video records, sparse track records, keyframes, and interpolation metadata exist. Playback, annotation UI, detector-to-tracker execution, identity correction, movement analytics, and export remain. |
| 7 | Active learning | 60–70% | 40–50% | Priority-plus-diversity selection, project and dataset scopes, configurable batches, per-group limits, reviewed-image exclusion, checksums, explanations, regeneration, API coverage, and Review Queue desktop controls exist. Embedding novelty, ensemble disagreement, retraining cycles, and real coral validation remain. |
| 8 | Advanced providers and Prompt Assist | 30–40% | 20–30% | Provider registry, capability checks, model catalog, Smart Mask/assist foundations, optional nnU-Net, and several task-aware model paths exist. Real acceptance across SAM-style prompting and advanced catalog providers remains incomplete. |
| 9 | Project interoperability | 45–55% | 35–45% | Immutable dataset versions, YOLO detection/segmentation exports, semantic-mask exports, CSV/NumPy measurement exports, backups, manifests, checksums, and provenance exist. Broader COCO/CVAT/LabelMe/Roboflow exchange and portable full-project archives remain. |
| 10 | Fusion and node editor | 0–5% | 0% | Model/task metadata provides groundwork, but the visual graph editor, typed nodes, execution engine, workflow templates, and multi-model GPU coordination are future work. |

## End-to-end scientific workflow

The core ReefVision loop is now substantially present in code:

**Import → annotate → create immutable dataset → train → register model → infer → review predictions → measure coral → summarize/export**

Estimated status for this core loop:

- **Implementation:** 80–85%
- **Release readiness:** 60–70%

The largest remaining issue is no longer basic annotation capability. It is completing executable acceptance across real YOLO segmentation, real nnU-Net semantic segmentation, Windows packaging, restart persistence, and representative coral datasets.

## Highest-value next work

1. Restore or replace the GitHub Actions execution path so backend, frontend, and Windows jobs actually start and produce logs.
2. Run the Phase 3 acceptance harness with a small real segmentation dataset.
3. Complete a real nnU-Net one-epoch smoke run, model registration, raster inference, proposal review, and restart check.
4. Validate Phase 4 measurements against manually measured coral examples and document expected error.
5. Run the active-learning selector on a real project, inspect redundancy and class/group coverage, and tune the default diversity weight.
6. Build the first complete classification workflow before expanding video tracking or the node editor.

## Current overall estimate

- **Strong image-annotation and dataset application:** 90–95%
- **Coral segmentation and measurement application:** 75–85%
- **Local Roboflow-like ML platform:** 50–60%
- **Full long-term ReefVision vision:** 40–50%

The full long-term percentage remains lower because classification, complete fish tracking, retraining automation, broad interoperability, and the fusion/node editor are still major independent products rather than minor finishing tasks.
