# ReefVision 1.2 — Connected, individually measured coral branches

Status: **approved for the 1.2 development scope; specification only** (2026-10-22).
Branch: `develop/reefvision-1.2` / draft PR #74.
Implementation, training, release qualification and representative scientific acceptance are **not yet complete**.

## Scientific objective

For each annotated colony, identify every visible centerline segment **between a terminal endpoint and a junction, or between two junctions**, assign it an individual branch/segment ID and measure it independently. Preserve one connected colony-level topology while retaining an auditable measurement for every unique segment. In this specification, "branch" means a graph edge (not necessarily an entire biological branch arising from the primary stem). Distinguish that definition explicitly in the UI, data dictionary and exports.

A connected graph is a **quality constraint**, not proof that every real branch was detected. Assess missed branches and spurious branches separately against reviewed ground truth.

## Required representation and behavior

1. **One verified colony mask → one colony centerline graph.** Reuse existing `skeletonization.py`, graph node/edge schemas, calibration and immutable skeleton-analysis revisions. Do not replace the current manual single-centerline implementation until backward-compatible reading/migration is tested.
2. **Individual persistent segment records.** Store stable scoped IDs, ordered centerline pixel coordinates, source/target junction IDs, raw/calibrated length, analysis/model/annotation/calibration revisions, and review status. Use per-branch provenance and exportable identifiers. A junction is shared topology; it contributes no artificial connection length.
3. **Connectivity contract.** Except for an initial root segment, a new manually drawn branch must attach to an existing node or point on a segment. Attachment in the middle of a segment creates an explicit junction and splits that segment into independently measurable edges. Support endpoint snapping within a *configurable and visibly reviewed* image-pixel tolerance; no invisible bridges or inferred real-world lengths.
4. **Disconnected candidate policy.** Reject approval of an unconnected network for a single colony unless a reviewer explicitly resolves it (repair confirmed tissue connection, mark a separate colony, or flag an occlusion/unknown connection as incomplete). Never silently connect across water/background or quietly discard unmatched segments. Keep disconnected hypotheses for review with their original coordinates, gaps, reasons and counts.
5. **No lost/double-counted lengths.** Report every unique retained graph edge once. The colony's total linear extension is the sum of its unique reviewed edge lengths; report per-edge length independently. Compare the graph to the underlying verified mask, display uncovered thin structures, gaps, overlapping/repeated paths and anomalous short spurs; do not claim perfect biological length recovery from connectivity alone. Never sum full overlapping root-to-tip paths as though they were disjoint branches.
6. **Branch editing.** Create, split, reconnect, merge, reshape and delete branch segments with undo/redo. Recompute graph constraints and lengths after each revision. Preserve IDs for unchanged segments and record supersession lineage for affected segments; avoid silently reassigning identity on reruns.
7. **Calibration and units.** Use existing scalar mm/px calibration or valid reference-plane homography where supported. Return pixel-only values if physical calibration is absent, label planar/2D limitations and retain calibration provenance. Do not infer metric 3D length from monocular 2D masks or an unvalidated relative depth model.
8. **Multiple colonies.** A second disconnected real colony is not automatically part of the first. Give each colony a separate graph and organism/colony identity. Handle cropped, broken or occluded specimens as review-required exceptions rather than manufacturing geometry.
9. **Longitudinal biology.** Persist reviewed branch measurements linked to organism/colony identity and image timepoints; support comparison of individual branch growth only when branch identity is explicitly matched or verified. Do not turn images or branches into independent experimental replicates.
10. **Exports.** CSV/JSON with `project_id`, `colony_id`, `image_id`, `analysis_id`, `branch_id`, parent/successor links, junction endpoints, pixel length, physical length/unit, calibration source, review status, algorithm/checkpoint identity, source mask revision and QC flags. Include colony-level unique-edge TLE and coverage summary.

## Deployable computer vision pipeline

- A user-registered/trained instance-segmentation model predicts colony masks on local images; predictions remain **proposals**, distinct from reviewed masks.
- Run the existing deterministic skeletonization, junction clustering, branch-graph construction and optional spur pruning over the proposed or verified mask. This **does not require a separate learned branch model**. Existing graph edge IDs are per-analysis and need persistent biological identity matching for longitudinal use.
- Add a reusable, versioned **branch extraction/measurement inference task**, callable from image analysis and Workflow Builder, which emits a typed candidate graph plus individual branch measurements, QC/provenance, and an explicit human acceptance step.
- Allow a future dedicated, trainable branch-keypoint/centerline model with its own checkpoint, held-out validation, audited promotion and rollback **only when warranted**; do not imply the initial skeletonization algorithm is itself a trained model or that every auto-generated branch is accurate.
- Local/offline execution, reproducibility metadata, safe model registry compatibility, and no automatic promotion to verified research measurements.

## Acceptance criteria / tests (required before 1.2 can claim this feature)

- Single straight branch, Y/T/fork junctions, tree with multiple generations and shared base: correct independent edge count, junction attachment and unique-edge summed TLE.
- New branch attaches at an interior segment point: segment splits without duplicate measurement of the shared length.
- A disconnected drawn/predicted line is blocked from scientific acceptance, shown for review and **never** auto-bridged; separate colonies remain separate.
- Occluded branch, crossing projections, tiny spurs, gaps, crop boundaries and broken masks receive correct review/uncertainty flags, not fabricated connectivity.
- Manual edits are non-destructive, undoable and persist across reload/export; revisions preserve audit trail and affected-ID lineage.
- Calibration known-distance and homography fixtures give correct units, branch lengths and limitations; uncalibrated input remains pixel-only.
- Deployment integration tests: local registered segmentation checkpoint → mask proposals → graph predictions → reviewed branch records → CSV/JSON and Workflow Builder, including no-checkpoint and failed-inference cases.
- Compare branch-count, junction detection, centerline/length errors, false positives and missing-branch coverage against scientist-annotated images with colony-level held-out splits. Do not claim validated biological completeness without this.
- Full backend/frontend/GUI/Windows acceptance remains mandatory; do not merge, tag or publish without owner authorization.

## Version coordination

This is part of **1.2 Phase 3 (derived biological metrics)** and its verification/export/longitudinal phases. It **supersedes the suggestion to implement connected multi-branch centerlines in 1.1**; it does not remove existing 1.1 scientific foundation work. Track in draft PR #74 and 1.0–2.0 coordination issue #76. 2.1 stereovision can later consume these branch IDs for independently validated 3D lengths, but does not block 1.2's 2D measurements.
