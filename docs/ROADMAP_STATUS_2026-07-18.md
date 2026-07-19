# ReefVision roadmap status — July 18, 2026

## How to read these estimates

Two percentages are used because ReefVision now has several substantial workflows implemented in code but not yet fully accepted in the packaged Windows application.

- **Implementation** estimates how much of the planned code and user workflow exists.
- **Release readiness** estimates how much has completed automated tests, real-model smoke tests, restart persistence checks, scientific acceptance, and installed-desktop validation.

These are engineering estimates, not automatically calculated metrics.

## Current phase status

| Phase | Scope | Implementation | Release readiness | Current position |
|---|---|---:|---:|---|
| 1 | Multitask foundation | 99–100% | 85–90% | Desktop foundation, projects, images, classes, models, jobs, migrations, backups, diagnostics, annotation architecture, and a read-only project-integrity inspector are present. Integrity checks cover managed files, directories, checksums, masks, exports, training artifacts, videos, and stale jobs. Packaged-desktop and restart acceptance remain. |
| 2 | Editable mask annotations | 97–99% | 82–90% | Revisioned polygon and raster masks, editing, storage, visibility, audit events, immutable snapshots, exports, and revision-safe topology cleanup are implemented. Cleanup can remove small islands, retain the largest component, fill holes, and choose four- or eight-neighbor connectivity. Large-project performance and installed-app acceptance remain. |
| 3 | Segmentation datasets, training, inference, and evaluation | 90–94% | 62–72% | YOLO instance-segmentation and nnU-Net semantic workflows are implemented. Quantitative evaluation now includes instance matching, IoU, Dice, pixel precision/recall, per-class results, false positives, and false negatives. Real one-epoch provider runs, boundary metrics, full regression tests, and packaged-app acceptance remain. |
| 4 | Coral measurements | 99–100% | 82–90% | Calibration, geometry, contained-polyp density, filtered counts, TLE, surface-area models, summaries, revision history, immutable snapshots, CSV/NumPy exports, and manual-reference validation are implemented. Validation now includes bias confidence intervals, Bland–Altman limits of agreement, and correlation. Representative scientific data and packaged-desktop acceptance remain. |
| 5 | Classification | 93–96% | 58–68% | Immutable crop datasets, six-class and binary-state modes, minimum-crop preprocessing, exports, training, trusted import, inference proposals, image labels, review, revisions, and audit events are implemented. Evaluation now includes confusion matrices, per-class precision/recall/F1, macro and weighted F1, confidence bins, expected calibration error, and Brier score. Real training/inference and packaged-app tests remain. |
| 6 | Video and fish tracking | 93–96% | 55–65% | Managed video import/playback, ByteTrack/BoT-SORT, editable tracks, calibration, trajectories, zones, heatmaps, and exports are implemented. Behavior analytics now include displacement, tortuosity, acceleration, turning, wall distance, pairwise spacing, school spread, and polarization. Real tracking quality, identity-switch analysis, long-video performance, and packaging remain. |
| 7 | Active learning | 72–80% | 45–55% | Priority-plus-diversity queues remain available, and persisted model-versioned image embeddings now support deterministic cosine-novelty selection, uncertainty/base-score blending, missing-embedding reporting, and per-group limits. Automatic embedding generation, ensemble disagreement, queue integration, and complete retraining cycles remain. |
| 8 | Advanced providers and Prompt Assist | 42–52% | 28–38% | Provider registry, model catalog, Smart Mask, optional nnU-Net, brush/box prompting, explicit positive and negative point prompts, mixed point/brush refinement, session counts, and prompt provenance exist. Real SAM-family acceptance, video propagation, depth providers, and full desktop point interaction remain. |
| 9 | Project interoperability | 65–75% | 45–55% | Immutable YOLO detection/segmentation, semantic-mask, classification, coral measurement, video, backup, and manifest formats exist. COCO instance export now preserves frozen boxes, polygon masks, raster RLE, categories, splits, source IDs, and checksums. COCO import, CVAT, LabelMe, Roboflow exchange, and portable full-project archives remain. |
| 10 | Fusion and node editor | 18–28% | 5–12% | A typed workflow graph schema, node/port catalog, model-task validation, required-input checks, cycle detection, deterministic graph checksums, parallel execution stages, templates, API validation, and desktop JSON planner exist. Graph persistence, visual drag-and-drop editing, execution, caching, artifacts, recovery, and multi-GPU scheduling remain major work. |

## End-to-end scientific workflows

### Coral segmentation and measurement

**Import → annotate masks and polyps → freeze dataset → train/register segmenter → infer → review → evaluate → calibrate → measure → validate → summarize/export**

- **Implementation:** 92–96%
- **Release readiness:** 72–82%

### Coral crop classification

**Freeze reviewed boxes → preview/remove undersized crops → export → train/import classifier → register → infer → evaluate/calibrate → accept/reject class corrections**

- **Implementation:** 93–96%
- **Release readiness:** 58–68%

### Fish tracking and behavior

**Import managed video → play → run detector/tracker or create manual tracks → correct trajectories → calibrate → analyze movement/schooling → export**

- **Implementation:** 93–96%
- **Release readiness:** 55–65%

### Active-learning review

**Generate/store embeddings → combine priority and novelty → apply group limits → review selected images → freeze a new dataset version**

- **Implementation:** 72–80%
- **Release readiness:** 45–55%

### Workflow composition

**Choose a template → configure registered models → connect typed ports → validate → inspect parallel stages**

- **Implementation:** 18–28%
- **Release readiness:** 5–12%

The largest remaining issue is no longer the absence of Phase 1–9 foundations. It is executable acceptance across real models, migrations, restart persistence, representative coral/video data, external interoperability consumers, and the packaged Windows application. Phase 10 still requires a substantial execution and visual-editor product.

## Highest-value next work

1. Restore or replace the GitHub Actions execution path so backend, frontend, migration, and Windows jobs start and produce logs.
2. Run `scripts/all-phases-acceptance.ps1`, including the Alembic `0019 → 0023 → 0019 → head` round trip.
3. Fix every Ruff, formatting, strict-mypy, pytest, TypeScript, Vitest, and production-build failure discovered by that run.
4. Train and evaluate real YOLO/nnU-Net segmenters and six-class/binary classifiers from immutable coral datasets.
5. Validate Phase 4 measurements against manually measured coral examples and publish expected error bounds and agreement limits.
6. Run ByteTrack and BoT-SORT on representative fish videos and quantify localization, track continuity, fragmentation, and identity switches.
7. Add automatic embedding generation and connect embedding novelty directly to active-learning review queues and retraining cycles.
8. Validate real SAM-family positive/negative point prompting and add desktop point interaction.
9. Test COCO exports in external consumers, then add COCO import and class-mapping previews.
10. Persist workflow graphs and build the execution engine before creating the full drag-and-drop node editor.
11. Build and smoke-test the packaged Windows application with all new workspaces.

## Current overall estimate

- **Strong image-annotation and dataset application:** 94–97%
- **Coral segmentation, classification, and measurement application:** 88–94%
- **Fish video tracking and behavior application:** 84–92% implemented
- **Local Roboflow-like ML platform:** 72–80%
- **Full long-term ReefVision vision:** 62–72%

The full long-term percentage remains lower because automatic embedding generation and retraining, broad bidirectional interoperability, real advanced-provider acceptance, workflow persistence/execution, the visual node editor, and multi-GPU coordination are still major independent products rather than small finishing tasks.
