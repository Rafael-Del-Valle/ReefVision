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
| GLB coordinate extrema at nanoscale (decoded Z max 0 vs declared 1e-9, and a genuine binary32 Z max near 1e-9) | Reject false exporter extrema despite tiny absolute differences; accept true extrema within relative float32 textual rounding | API and saved typed Workflow Builder graphs reject mismatched source bounds without artifacts and replay valid unverified measurements with stable source and artifact hashes |
| Point cloud with known extrema and sparse sampling | Independent axis extents; no inferred watertight surface | Distinguish observed envelope from reconstructed surface and warn about sampling limitations |

Test extreme but finite coordinates, malformed indices, nonfinite values, adversarial file sizes, unsupported binary PLY, invalid GLB chunks, and source metadata tampering. Bound memory, vertex/face counts, and parse time. A preview is not evidence of a validated reconstruction.

For ASCII PLY point-cloud coordinates, preserve the declaration's floating-point width when reporting a rejected source token: `float`/`float32` underflow is a binary32 range failure, while `double`/`float64` tokens below binary64 resolution have a distinct precision-underflow failure. Test both signs of an unrepresentably small nonzero decimal through the project API and a saved executable typed graph; both must reject the input with no measurement artifact. A zero produced by parsing is not evidence of a physical zero. Retain separately tested valid subnormal and exact-zero behavior. Neither diagnostic establishes physical uncertainty.

For ASCII PLY **point-cloud** previews, also test distinct nonzero decimal XYZ values that collide after binary64 parsing: for example, `1` and `1.00000000000000001` are different source locations but both become Python `1.0`. Reject these within an axis before the application reports duplicate points or an apparently zero span. Textually different but numerically equivalent values such as `1.0` and `+1e0` must remain accepted. Exercise both signs, the standalone API, saved typed-graph failure without a measurement artifact, and two deterministic replays of accepted inputs. This protects source-decimal distinctions within the same imported cloud; it does not certify positional precision, instrument accuracy or cross-file registration.

For ASCII PLY **triangle meshes**, apply the same source-decimal collision gate independently to the X, Y, and Z coordinate streams before calculating surface area, dimensions, topology or boundary paths. Different decimal tokens such as `1` and `1.00000000000000001` must not become indistinguishable binary64 vertex locations and fabricate a degenerate patch. Equivalent decimal spellings such as `1.0` and `+1e0` remain valid. Cover positive and negative collisions and declared `float`/`double` widths through standalone import/measurement and a saved executable typed mesh graph; invalid geometry must produce no measurement artifact. Replay valid graphs twice with identical values, hashes and explicitly unverified calibration/registration. This is a source-integrity bound, not a guarantee of mesh reconstruction or anatomical accuracy.

### Point-cloud maximum-gap preview controls

The typed `point_cloud_preview` Workflow Builder node registry must expose both `preserve_largest_axis_gap_boundaries_in_preview` and `preserve_largest_axis_gap_boundary_loci_in_preview` with `false` defaults, matching the standalone request schema and saved-graph runtime. Test each option using 600-point synthetic XYZ and ASCII PLY inputs through the project API, persisted graph planning, two independent saved-graph executions, and SHA-256-identical replay artifacts. The first option protects at least one source row for each projected coordinate endpoint of all equally largest gaps; the second protects a source row for every distinct three-dimensional XYZ locus at those endpoints. Reject over-budget requests explicitly rather than suggesting complete preservation. Even when all distinct boundary locations are displayed, the 512-point preview may omit repeated acquisition rows; maintain separate omission warnings and do not interpret projected gaps or preview sampling as tissue loss, scan completeness, calibrated anatomical length, or verified identity.

### Colored PLY preview fidelity (not biological-condition assessment)

When imported ASCII PLY rows supply `uchar`/`uint8` RGB, audit distinct observed
(XYZ, RGB) pairs separately from XYZ loci. A complete XYZ preview can still
discard a rare observed color at a repeatedly acquired coordinate. Report
the total and displayed distinct XYZ/RGB pairs, their displayed fraction,
the number of XYZ loci with more than one observed RGB, and a SHA-256 over
displayed original row indices, coordinates and colors. Warn separately
when an XYZ locus has multiple RGB observations and when display decimation
omits a distinct XYZ/RGB pair. Uncolored PLY and inline XYZ must report
unavailable RGB diagnostics, **not** perfect color coverage.

For acceptance, use a 600-row colored PLY fixture with two XYZ locations,
a distinct RGB observation at a row that deterministic 512-row decimation
omits, and retained XYZ extrema. Repeat with optional distinct-XYZ locus
pinning: it must not claim RGB coverage just because both XYZ locations
remain visible. Compare the standalone API result with two runs of a
persisted executable typed `point_cloud_preview` Workflow Builder graph,
including full artifact values, warnings, RGB-display hash, imported-source
hash and artifact SHA-256. All test inputs must retain explicitly unverified
calibration, specimen identity and anatomical interpretation. RGB variation
can reflect light, camera response, reconstruction, acquisition time or
actual appearance; it must not be scored as coral health, bleaching, lesion
extent or tissue survival without separately validated color standards
and human-reviewed biological references.

For loci observed under multiple RGB values, independently report how many of
those XYZ loci retain **every observed color variant** in the preview versus
how many lose at least one variant. The nested `preview_rgb_variant_support`
fields `multi_rgb_xyz_loci_with_complete_preview` and
`multi_rgb_xyz_loci_with_incomplete_preview` must sum to the number of
source XYZ loci with multiple RGB values. Emit
`preview_omits_multi_rgb_locus_variants` only when an observed variant at a
multicolor locus is missing. Verify both omitted rare RGB in a 600-row PLY
and complete retention in a three-row PLY, through standalone analysis and
twice-executed persisted typed Workflow Builder graphs with matching
artifacts and SHA-256 fingerprints. This is acquisition display evidence,
**not** validated colorimetry, bleaching, disease or tissue-loss assessment.

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

## OBJ decimal-collapse source integrity (provisional)

Before accepting OBJ source measurements, challenge coordinates on all three axes
with distinct decimal literals that round to the same binary64 position (for
example, `1` and `1.00000000000000001`). Repeat with homogeneous `v x y z w`
records whose **exact rational** `x/w`, `y/w` or `z/w` values differ but whose
computed floats coincide. Such source collisions must fail in the parser, the
standalone mesh-preview API, and a saved typed Workflow Builder execution without
creating a measurement artifact. Equivalently represented locations (for
example, `1`, `+1e0` and `2/2`) remain legitimate and must replay with identical
measurement payloads and artifact SHA-256 hashes across two executions of the
**same persisted graph**. Preserve separate raw-source bytes and calibration,
coordinate-registration and biological-identity review states; numeric source
integrity alone never verifies a reconstruction or an organism. The dedicated
regressions are in `test_spatial_mesh_obj_numeric_integrity_v14.py`. This
section defines testable behavior, not a field-validation acceptance claim.

### Complete distinct XYZ location retention in bounded previews

The opt-in, strict-boolean `preserve_distinct_xyz_loci_in_preview` control is
available in standalone XYZ and imported ASCII PLY point-cloud analysis and in
the executable typed `point_cloud_preview` Workflow Builder node. For source
clouds with more than 512 acquisition rows, pin the first original source row
for **each distinct XYZ coordinate** before allocating the remaining bounded
preview slots across source indices. When protected rows (including any selected
chords or requested gap boundaries) exceed 512, reject the preview explicitly.
Do not silently sample the protected set, round away distinct loci, or reassign
source indices. The option retains unique source locations, **not** all duplicate
acquisition rows, verified area coverage, independent organisms, or anatomical
structures. Confirm source-index provenance, independent XYZ-versus-row
retention counts, explicit omission QC, strict request validation, and equal
standalone versus twice-replayed saved-workflow artifacts/SHA-256 for both
inline XYZ and imported ASCII PLY. Include a rare locus on an ordinarily
omitted index and a source containing more than 512 unique XYZ locations.
Keep unreviewed calibration, specimen identity, and registration provisional.

### Exact-capacity distinct XYZ retention and source-row endpoint disclosure

Reproduce a source with **513 acquisition rows but exactly 512 distinct XYZ
locations**: rows 0–511 each represent a different location, and the final row
duplicates row 0. A 512-point preview can legitimately display every observed
XYZ location, so the opt-in `preserve_distinct_xyz_loci_in_preview` policy must
**not** reject it simply to retain the duplicate last acquisition row. Preserve
all 512 first-occurrence indices and report
`preview_source_acquisition_endpoint_support` as first-row true and last-row
false, with `preview_omits_acquisition_endpoint_row` QC. Distinguish this raw
acquisition-order endpoint from axis extrema, scan-completeness evidence, and
biological landmarks. Other explicitly protected chord, extrema, or gap-boundary
indices are still hard requirements: reject genuinely oversubscribed unions.

Confirm the same artifact through the standalone XYZ/ASCII PLY API and twice
executing a saved executable typed Workflow Builder graph, including source
indices, provisional calibration and biological identity, full-source geometry
fingerprint, complete QC warnings, and stable artifact SHA-256. Independently
verify that 600 *different* XYZ locations still fail a 512-slot preservation
request with HTTP **400** for a domain budget violation; invalid boolean
request types remain HTTP **422** schema validation errors. These are synthetic
acceptance references, not representative coral, human-review, installed
Windows, or physical GPU validation.

### Direct service RGB row contract

The direct point-cloud measurement service validates optional RGB acquisition
rows even when color-pair preservation is disabled. For each input row, require
exactly three built-in integer channels in the unsigned-byte range 0–255.
Reject booleans, floats, incomplete or surplus triplets, mismatched acquisition
counts and malformed row shapes before publishing any scientific preview.
Test direct service rejection with and without preservation; accept valid
0/255 boundary values. Imported colored ASCII PLY already parses uint8
channels; its standalone API and twice-executed persisted typed Workflow
Builder replay must continue matching complete scientific artifacts and
SHA-256 fingerprints. This proves source-input integrity only, not calibrated
color, coral health, verified specimen identity or independent replicates.

### Bounded preview centroid displacement is not organism movement

The point-cloud preview reports a row-weighted sample centroid alongside the
full-source row-weighted centroid. Compare
`preview_row_centroid_in_source_frame_m` to
`arithmetic_centroid_in_source_frame_m` using
`preview_vs_source_row_centroid_separation_m`, its available scale-only
uncertainty interval, and the dimensionless
`preview_vs_source_row_centroid_separation_fraction_of_bbox_diagonal`.
The normalized fraction is `null` when the full-source bounding-box diagonal
is zero, not a fabricated zero-denominator measurement. Identical complete
samples and coincident-source scans must not report spurious displacement.
When a positive uncertainty interval falls below representable precision,
withhold that interval and retain explicit QC instead of asserting certainty.

Challenge a 600-row synthetic cloud where an ordinarily decimated source row
contains a distinct coordinate. Independently compute each centroid from the
full acquisition row indices and displayed original row indices and compare
their difference, calibration factor, and interval. Verify the direct service,
standalone project API, and **two executions of the same persisted typed
Workflow Builder graph**, including identical complete artifacts and SHA-256
digests. Acquisition rows are not biological replicates; sample-centroid
displacement is neither coral displacement, registration accuracy, surface
coverage, tissue health nor independent scale calibration. This test is
synthetic; field evidence and human review are still required.

### Raw RGB channel-extrema completeness (not biological condition)

For imported colored ASCII PLY point clouds, compare the minimum and maximum
of each validated uint8 red/green/blue channel across **all source rows** with
the displayed 512-point-or-smaller sample. Report both sets of ranges as
`source_rgb_channel_ranges_uint8` and
`preview_rgb_channel_ranges_uint8`, and list missing source extrema in
`preview_omitted_source_rgb_channel_extrema` using explicit labels such as
`red_max`. Emit `preview_omits_rgb_channel_extrema` when the display omits
an observed source-channel limit; do not warn when all limits survive. The
comparison is independent of XYZ geometry coverage, and is available in
standalone point-cloud analysis and saved executable typed Workflow Builder
runs, with complete artifact equality and deterministic SHA-256 replay tests.
Source extrema reveal only bounded sampling of raw sensor observations:
they do **not** measure calibrated reflectance, coral bleaching, disease,
living tissue, illumination quality, or biological identity.

### Complete colored PLY observation preservation in bounded previews

The strict-boolean `preserve_distinct_xyz_rgb_pairs_in_preview` is an opt-in
standalone and executable typed `point_cloud_preview` Workflow Builder control
for **colored ASCII PLY only**. It retains at least one original acquisition row
per distinct observed (XYZ, R, G, B) combination; a repeated acquisition row
may be omitted without losing a distinct color observation. This is separate
from `preserve_distinct_xyz_loci_in_preview`, which preserves geometry but can
omit rare color variants at one XYZ location. Colorless PLY and inline XYZ
sources must reject color-pair preservation requests. A request needing more
than 512 protected rows (including other explicitly pinned indices) must fail
with a domain validation error rather than publish a partial scientific artifact;
nonboolean input fails schema validation.

Use a 600-row two-locus colored PLY reference with one rare RGB observation
placed at a normally omitted index. Assert that ordinary decimation reports
incomplete multi-color support, whereas the pinned preview retains all three
observed XYZ/RGB pairs, removes the color-omission warnings, keeps the same
source geometry/provisional calibration evidence, and yields a different
sample-bound fingerprint. Verify typed registry discovery, the standalone
API, and **two executions of the same persisted typed graph**, comparing
complete measurement payloads and stable artifact SHA-256. Also test an
over-capacity 513-distinct-pair source and exactly 512 distinct color pairs
with a duplicate final acquisition row; the latter must succeed with
explicit endpoint-row omission QC. These diagnostics are about data
visualization and raw sensor observations; **never infer bleaching, tissue
condition, health, biological replicates or verified specimen identity**.
Independent coral references, human adjudication, installed Windows GUI,
GPU and upgrade/rollback release gates remain outstanding.
