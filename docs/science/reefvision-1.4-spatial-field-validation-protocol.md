# ReefVision 1.4 — spatial field validation protocol (provisional)

**Status:** research validation plan, not a claim of completed validation or release readiness.
**Scope:** OBJ/ASCII PLY/GLB triangular surfaces, ASCII PLY point clouds, spatial measurement, longitudinal identity, and saved Workflow Builder replay.

## Evidence and custody

Assign a project ID, specimen ID, observation ID, UTC collection timestamp, operator, sensor/camera, acquisition geometry, and coordinate reference for each acquisition. Retain original imported bytes locally, calculate a SHA-256 of those bytes, and record source format, byte length, acquisition notes, and all reconstruction parameters. A matching hash demonstrates byte consistency only; it does not verify specimen identity, geometry, or calibration. Preserve raw and derived assets as distinct immutable versions. Do not upload user-trained checkpoints or original research imagery to CI.

## Independent calibration

Record physical scale standard, units, standard uncertainty, measurement method, operator, date, and whether the standard is visible in the source acquisition. Measure at least three independently positioned distances across the reconstructed scene and compare with physical references. Evaluate nonuniform scale, camera distortion, registration residuals, occlusion, and reconstruction bias separately. The existing scale-only uncertainty bounds are *not* full measurement confidence intervals. Until an authorized human reviews the scale standard and reconstruction, retain `caller_supplied_unverified` and do not imply calibrated biological growth.

## Geometry acceptance fixtures

| Fixture | Independent reference | Required standalone and saved-workflow behavior |
| --- | --- | --- |
| Right triangle with vertices (0,0,0), (3,0,0), (0,2,0) | Area = 3 source-unit²; perimeter = 5 + sqrt(13) source units; bounding diagonal = sqrt(13) source units | Identical measurements for canonical OBJ, reordered vertices and negative OBJ indices |
| Same triangle at 0.01 and 0.02 m/source-unit | Area ratio 4; perimeter and extents ratio 2; dimensionless area/diagonal² = 3/13 | Units, scale-only uncertainty and geometry fingerprint consistent across API and saved artifact |
| Closed tetrahedral surface | Independent analytical surface and signed-volume references | Volume only when watertight and topology permits; no biological volume claim |
| Open, nonmanifold, duplicate-face and zero-area surfaces | Explicit QC expectations | No fabricated enclosed volume, hidden topology failures, or misleading precision |
| Equivalent OBJ, ASCII PLY and GLB meshes | Equal geometric references within declared numerical tolerance | Preserve source-format and byte-provenance distinctions while comparing geometry |
| Point cloud with known extrema and sparse sampling | Independent axis extents; no inferred watertight surface | Distinguish observed envelope from reconstructed surface and warn about sampling limitations |

Test extreme but finite coordinates, malformed indices, nonfinite values, adversarial file sizes, unsupported binary PLY, invalid GLB chunks, and source metadata tampering. Bound memory, vertex/face counts, and parse time. A preview is not evidence of a validated reconstruction.

## Anatomical measurements

A selected surface-edge path is not automatically a coral branch centerline. For anatomical branch length, document branch endpoints, skeletonization or centerline algorithm, branch/junction rules, ambiguity handling, and repeatability across at least two blinded annotators. Report uncertainty from scale, endpoint placement, reconstruction, and repeat segmentation independently. Do not label surface paths as validated branch lengths until an independent specimen reference and repeatability study pass.

## Longitudinal identity and condition

Pair observations only with distinct observation IDs, increasing UTC timestamps, the same provisional specimen/project identity, and immutable geometry fingerprints. Require explicit human review of reidentification evidence and rigid registration. A caller-supplied transform or similarity score is not verified reidentification. Record missing views, tissue condition annotation rubric, reviewer disagreements, and reasons for exclusion. Compare change only after documenting matched coordinate frames, scale compatibility, reconstruction bias, and temporal dependence. Do not interpret geometric differences as growth or mortality without biological validation.

## Workflow Builder parity gate

For every supported analysis: (1) call the standalone API; (2) create a typed graph using the corresponding spatial node; (3) persist the graph; (4) reload and execute it; (5) compare artifact values, units, QC warnings, source hashes, reviewer state and uncertainty provenance; (6) mutate a copied input and confirm stale evidence is rejected; (7) reopen the saved run and confirm the original artifact remains unchanged. Include explicit failure cases for missing calibration, mismatched specimen IDs, invalid timestamps and malformed geometry. A visual-only node or a graph that cannot be replayed does not pass.

## Release evidence register

Record per-gate: test fixture identifier, reference method, exact commit SHA, Actions run/job URL, platform, result, reviewer and date. Backend unit/API tests, frontend interactive preview tests, persisted workflow tests, migration roundtrips, Windows MSI/CAB packaging, installed-GUI import and preview, and local GPU acceptance are **separate gates**. GitHub Actions success cannot substitute for an installed Windows GUI/GPU test or independent scientific review. Keep versions 1.4 and 1.5 unreleased until all applicable gates have explicit passing evidence.
