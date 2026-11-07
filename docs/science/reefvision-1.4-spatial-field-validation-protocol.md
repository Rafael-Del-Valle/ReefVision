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

## Quantitative repeatability and uncertainty acceptance design

Use a preregistered, independently measured reference set rather than choosing thresholds after inspecting ReefVision outputs. Include at least three shape classes (smooth, highly branched, and partially occluded), three physical size classes, and repeated reconstructions from separate image acquisitions. Keep the same specimens in both the standalone and persisted-workflow arms; do not treat repeated views or branches from one specimen as independent biological replicates.

For each reference measurement, record the reference value, reference method and uncertainty, ReefVision estimate, signed error, absolute error, relative error (only for nonzero references), and whether the declared scale-only interval covers the reference. Report bias and MAE with specimen-level resampling; cluster bootstrap by specimen, not by vertex, face, frame, or branch. Report interval coverage separately from calibration-only coverage, since the latter intentionally excludes segmentation, reconstruction and reference uncertainty. Never call a scale-only interval a 95% confidence interval.

For repeated operators and acquisitions, use a crossed design when feasible and explicitly document missing cells. Separate within-operator repeatability, between-operator reproducibility, acquisition variability, and reconstruction variability. A high correlation between measurements does not establish agreement. For longitudinal change, report paired differences and specimen-clustered uncertainty; do not infer growth from a nonzero difference when calibration or registration review is incomplete.

Before testing, define numerical tolerances by quantity and precision (e.g., absolute tolerance near zero and relative tolerance for larger magnitudes), reference-standard uncertainty, and biological acceptance thresholds with a domain reviewer. Reject nonfinite outputs, negative uncertainty widths, lower bounds above estimates, and any graph replay that changes the saved provenance or reviewer state. Store the preregistration identifier, fixture hashes, reviewer sign-off, and any deviations alongside the exact-head run evidence.

## Release evidence register

Record per-gate: test fixture identifier, reference method, exact commit SHA, Actions run/job URL, platform, result, reviewer and date. Backend unit/API tests, frontend interactive preview tests, persisted workflow tests, migration roundtrips, Windows MSI/CAB packaging, installed-GUI import and preview, and local GPU acceptance are **separate gates**. GitHub Actions success cannot substitute for an installed Windows GUI/GPU test or independent scientific review. Keep versions 1.4 and 1.5 unreleased until all applicable gates have explicit passing evidence.

## Field specimen evidence capture and decision matrix

For each independent specimen, preserve a stable project-scoped specimen ID and separate acquisition/observation IDs. Record acquisition UTC time, operator, camera and lens, calibration artifact ID and physical reference uncertainty, reconstruction software/version, raw source file SHA-256, original format, coordinate frame and units, acquisition conditions (visibility, occlusion, lighting), and reference measurement method. Link any reconstructed mesh or point cloud to the immutable raw acquisitions; never infer an anatomical branch measurement from a surface-edge path.

Use an explicit review record for each proposed longitudinal match: source and target observation IDs, proposed organism identity, registration method and transform provenance, reviewer ID, decision (accepted/rejected/needs-review), decision UTC time, rationale, and source/target geometry fingerprints. An automated similarity score or a supplied transform cannot populate an accepted decision. Any changed geometry fingerprint, calibration reference, or coordinate-frame definition invalidates the earlier match for downstream verified comparisons until a new human review is recorded.

| Scenario | Required standalone behavior | Required saved-workflow behavior |
| --- | --- | --- |
| Same geometry in OBJ, ASCII PLY and GLB | Comparable geometry within documented precision, distinct source hashes and format provenance | Persist/replay matching numeric quantities and source-specific hashes |
| PLY point cloud without faces | Extents only; no fabricated surface area, enclosed volume or anatomical centerline | Preserve unavailable quantities and explicit QC after reload |
| Missing or unreviewed calibration | Withhold physical-unit claims or label caller-supplied values unverified | Retain calibration evidence and unverified status in persisted artifact |
| Mutated source bytes or stored filename metadata | Reject compromised asset before preview/measurement | Reject replay instead of silently substituting a new asset |
| Reidentification with stale source/target fingerprint | Reject or withhold accepted match | Never inherit previously accepted identity from stale evidence |
| Repeated views from one specimen | Treat as dependent measurements, not additional biological replicates | Preserve specimen clustering keys in export and analysis metadata |

Acceptance requires a second reviewer to reconcile disagreements against the raw evidence, with the original decisions retained in the audit trail. The matrix describes **required behavior**, not claims that all cases are implemented or validated. Every row needs a traceable test identifier, independent expected outcome, exact commit and Actions evidence, and installed-GUI observation where applicable before its release gate can be marked complete.

## Calibration sensitivity and dimensional-consistency challenge

For fixed geometry with positive scale `s` meters/source-unit, independently calculate the scaling exponents: lengths and extents scale as `s`, surface area as `s²`, and conditional enclosed volume as `s³`. For a bounded calibration interval `[s_low, s_high]` with `0 < s_low <= s <= s_high`, compare the reported *scale-only* quantity interval against independently computed `[q_raw * s_low^p, q_raw * s_high^p]` for each nonnegative raw quantity and exponent `p`. Do not apply this shortcut to signed volumes, coordinate offsets, registration residuals, or derived statistics that mix dimensions; specify their propagation rules separately.

Use two calibration standards spanning the same specimen, including a deliberately conflicting pair, to test that nonuniform scale and disagreement are flagged rather than averaged into false precision. Challenge zero/negative scale, inverted bounds, missing units, calibration tied to another acquisition, and changed calibration metadata after a saved graph is created. Standalone results and reloaded executable graphs must agree on values, physical units, provenance, QC state, and rejection behavior. Preserve raw source-unit measurements even when a physical-unit claim is withheld.

Separate uncertainty contributions in the validation record: scale-standard measurement, camera/reconstruction, manual landmark or endpoint placement, and temporal registration. Only the first contribution is represented by a scale-only interval. For paired longitudinal observations, do not assume calibration errors are independent: record whether the same standard, instrument and calibration session were reused and evaluate correlated versus independent-error sensitivity. Require reviewer sign-off before interpreting physical-unit changes as biological change.
