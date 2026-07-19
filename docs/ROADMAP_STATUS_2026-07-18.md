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
| 4 | Coral measurements | 98–100% | 80–90% | Calibration, geometry, contained-polyp density, filtered counts, TLE, surface-area models, summaries, revision history, immutable snapshots, CSV/NumPy exports, and manual-reference validation with bias/MAE/RMSE/MAPE and tolerance checks are implemented. Release readiness still requires comparison with representative manually measured coral data and packaged-desktop acceptance. |
| 5 | Classification | 90–95% | 55–65% | Immutable crop datasets, six-class and binary-state modes, explicit minimum-crop preprocessing, exports, scratch and local-pretrained training, trusted classifier registration/import, crop inference proposals, probability retention, image labels, accept/reject correction, revision history, audit events, and a desktop workspace are implemented. Real training/inference performance, calibration, migration, restart, and packaged-app tests remain. |
| 6 | Video and fish tracking | 90–95% | 50–60% | Managed video import/playback, checksum deduplication, sparse manual tracks, interpolation, ByteTrack/BoT-SORT jobs, editable generated tracks, calibration, trajectories, speed, activity, zone occupancy, nearest-neighbor distance, school spread, heatmaps, and CSV/MOT/JSON exports are implemented. Real detector tracking, identity-switch analysis, performance testing, and packaged-app validation remain. |
| 7 | Active learning | 60–70% | 40–50% | Priority-plus-diversity selection, project and dataset scopes, configurable batches, per-group limits, reviewed-image exclusion, checksums, explanations, regeneration, API coverage, and Review Queue desktop controls exist. Embedding novelty, ensemble disagreement, retraining cycles, and real coral validation remain. |
| 8 | Advanced providers and Prompt Assist | 30–40% | 20–30% | Provider registry, capability checks, model catalog, Smart Mask/assist foundations, optional nnU-Net, and several task-aware model paths exist. Real acceptance across SAM-style prompting and advanced catalog providers remains incomplete. |
| 9 | Project interoperability | 55–65% | 40–50% | Immutable dataset versions, YOLO detection/segmentation exports, semantic-mask exports, classification crop exports, coral CSV/NumPy exports, video CSV/MOT/JSON exports, backups, manifests, checksums, and provenance exist. Broader COCO/CVAT/LabelMe/Roboflow exchange and portable full-project archives remain. |
| 10 | Fusion and node editor | 0–5% | 0% | Model/task metadata provides groundwork, but the visual graph editor, typed nodes, execution engine, workflow templates, and multi-model GPU coordination are future work. |

## End-to-end scientific workflows

### Coral segmentation and measurement

**Import → annotate masks and polyps → freeze dataset → train/register segmenter → infer → review → calibrate → measure → validate → summarize/export**

- **Implementation:** 90–95%
- **Release readiness:** 70–80%

### Coral crop classification

**Freeze reviewed boxes → preview/remove undersized crops → export → train/import classifier → register → infer → accept/reject class corrections**

- **Implementation:** 90–95%
- **Release readiness:** 55–65%

### Fish tracking and behavior

**Import managed video → play → run detector/tracker or create manual tracks → correct trajectories → calibrate → analyze → export**

- **Implementation:** 90–95%
- **Release readiness:** 50–60%

The largest remaining issue is no longer missing Phase 4–6 workflow code. It is executable acceptance across real models, migrations, restart persistence, representative coral/video data, and the packaged Windows application.

## Highest-value next work

1. Restore or replace the GitHub Actions execution path so backend, frontend, and Windows jobs actually start and produce logs.
2. Run Alembic upgrades and downgrades through revisions `0020`, `0021`, and `0022` on a disposable database.
3. Train a one-epoch six-class classifier and a one-epoch binary open/closed classifier from immutable coral crops.
4. Register both classifiers, run crop inference, accept/reject predictions, and verify revision/audit persistence after restart.
5. Run a detector with ByteTrack and BoT-SORT on representative fish videos; quantify track continuity and identity switches against manual references.
6. Validate Phase 4 measurements against manually measured coral examples and publish expected error bounds.
7. Build and smoke-test the packaged Windows application with all three new workspaces.

## Current overall estimate

- **Strong image-annotation and dataset application:** 92–96%
- **Coral segmentation, classification, and measurement application:** 85–92%
- **Fish video tracking and behavior application:** 80–90% implemented
- **Local Roboflow-like ML platform:** 65–75%
- **Full long-term ReefVision vision:** 55–65%

The full long-term percentage remains lower because complete active-learning retraining automation, broad interoperability, advanced prompt providers, and the fusion/node editor are still major independent products rather than minor finishing tasks.
