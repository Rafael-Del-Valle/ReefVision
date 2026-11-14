# Track C scientific acceptance protocol (development only)

This is a **test plan**, not evidence that ReefVision 1.4 or 1.5 is validated or release-ready. Run it against a pinned branch SHA, record the test fixture hashes, and attach review evidence to issue #76. No simulated result is a field validation.

## 1.4: 3D geometry and longitudinal studies

| Gate | Reproducible acceptance experiment | Required evidence |
| --- | --- | --- |
| Import | Load known-good and malformed OBJ, ASCII PLY and GLB 2.0 fixtures; include point-only PLY, excessive vertex/face counts, malformed indices and truncated input. | Deterministic parse outcomes, byte hashes, bounds checks and error messages; no network or remote model downloads. |
| Interactive preview | Inspect a calibrated, branched coral fixture, a point cloud and a disconnected mesh; exercise rotate, zoom, selection and reload in an installed Windows build. | Screenshots or recordings tied to build SHA and a human reviewer; rendering is not proof of biological identity. |
| Surface area | Compare a closed cube and two planar triangles against independently calculated metric areas at multiple unit scales. | Numerical tolerance, calibration method, units, mesh-topology QC and scale-only uncertainty interval. |
| Dimensions | Compare a rectangular prism against independently measured axes and diagonal after rotation and scaling. | Coordinate-frame provenance; do not label an axis-aligned bounding box an anatomical axis. |
| Branch length | Use independently traced synthetic centerlines and expert-traced coral branches with documented junction/tip definitions. | Agreement, topology sensitivity and calibration uncertainty; **surface edge path length is not validated anatomical branch length**. |
| Registration | Use known rigid transforms, mismatched coordinate frames and corrupted correspondence evidence. | RMS, transform validation, registration provenance and explicit unverified status until reviewed. |
| Identity and change | Compare the same specimen at two dates and two deliberately different specimens with blinded human reviewers. | Reviewer identity, decision timestamps, source asset IDs and hashes, disagreement handling, no automatic verified reidentification. |
| Longitudinal QC | Replay legacy observations missing face/patch counts, missing intervals, zero-area geometry, offset timestamps and forged metadata. | No invented zero measurements; contradictory topology rejected; normalized elapsed time; direct/API/saved-graph artifact parity. |
| Condition | Compare predeclared expert condition categories with held-out specimens and repeat reviewers. | Confusion matrix, inter-reviewer agreement, uncertainty and failure analysis; avoid treating geometry change as health without validation. |
| Model benchmarks | Run frozen held-out assets across pinned model/checkpoint versions and device profiles. | Dataset splits, inference time, accuracy by class/species, confidence intervals and explicit local-only checkpoint handling. |

For every relevant analysis, exercise (a) the standalone endpoint, (b) the typed Workflow Builder node, and (c) a persisted graph loaded and executed again after a fresh process start. Compare output payloads and provenance hashes, including negative/error paths. A graph planner accepting a node is **not** sufficient evidence of executable parity.

## Deterministic 1.4 reference fixtures and negative controls

Use independent reference calculations, not ReefVision's own output, as the oracle. Fixture generation must be deterministic, local, versioned, and hash-logged. Preserve source coordinates and calibration separately; never silently rescale imported geometry.

| Fixture | Independent expected value | Required negative control |
| --- | --- | --- |
| Closed cube with side 2 coordinate units and a declared 0.01 m/unit calibration | Surface area = 0.0024 m²; axis-aligned extents = 0.02 m on each axis; diagonal = sqrt(3) × 0.02 m. The 12 triangles must not be counted as 12 independent surface patches. | Omit calibration: reject metric claims or mark them explicitly uncalibrated. |
| One planar 3–4–5 right triangle, with 1 m/unit calibration | Area = 6 m²; no enclosed volume. | Duplicate the triangle with opposite winding: flag overlapping/ambiguous surface rather than claiming validated coral tissue area. |
| Two disconnected planar triangles, each with area 6 coordinate-units² | Total surface area = 12 coordinate-units²; two edge-connected components, assuming no shared vertices or edges. | Join them at a single vertex only: do not silently treat vertex contact as an edge-connected patch. |
| Two observations with identical source geometry and scale, one hour apart | Zero geometric area change and elapsed time = 1/24 day after UTC normalization. | Give observations different specimen identifiers without verified reidentification: no verified biological growth claim. |
| Rigidly translated/rotated cube with known 4×4 transform | Surface area invariant; aligned coordinate positions recover the reference within declared numeric tolerance. | Reflection, non-rigid scaling, singular transform and changed source hash must not be accepted as verified rigid registration. |

For uncertainty acceptance, supply an explicit positive scale interval `[s_min, s_max]` and independently compute the surface-area interval using `A_raw × s_min²` and `A_raw × s_max²`. This is **scale-only** uncertainty: it excludes segmentation, registration, occlusion, mesh reconstruction and biological sampling errors. A malformed interval, a nominal measurement outside its interval, or an interval attached to an absent nominal measurement must be rejected; absent legacy uncertainty must remain unknown, not zero.

For each fixture, capture the input file SHA-256, calibration source and units, source and target observation IDs, code commit, numeric tolerance, standalone response, typed node response, serialized workflow definition, fresh-process replay response, saved artifact hash, and reviewer disposition. Run the negative control through all three execution paths and assert equivalent failure classifications; compare scientifically meaningful fields rather than volatile database IDs or timestamps. Keep automatic QC and provisional identity separate from human verification.

## 1.5: experimental and field science

Before implementing or claiming acceptance, define independent experimental units, randomization blocks, repeated measures, missingness, covariates and planned contrasts. Reject pseudoreplication (for example, treating multiple fragments sharing a treatment tank as independent tank replicates). Verify ICC model, rater structure and single-versus-mean estimands; Bland–Altman bias and limits of agreement must identify paired units and repeated-measure assumptions. Check multiplicity and model diagnostics, report effect sizes and uncertainty, and include power/sensitivity simulations under explicitly stated assumptions.

For field inference, mosaics, drift checks, plugins, multimodal fusion, surveys, scientific figures and reusable study packages, require offline reproducibility, typed persisted workflow replay, data/source licensing, reviewer signoff and deterministic failure behavior. A model prediction or automated QC result must never silently become human-verified evidence.

## Release gate and evidence ledger

Record for each gate: commit SHA; fixture and model hashes; exact-head Actions run URL; backend, frontend, migration, E2E and scientific results; Windows MSI/CAB packaging outcome; **installed** GUI/GPU observations; reviewer and date; outstanding limitations. Passing CI or producing an installer is not equivalent to installing and testing it. Until every applicable gate has actual evidence, keep both versions marked **HOLD**. Never promote local user-trained checkpoints, calibration evidence or provisional biological identities into a release automatically.
