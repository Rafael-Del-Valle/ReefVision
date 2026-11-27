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
full-source row-weighted centroid. The signed three-axis
`preview_minus_source_row_centroid_offset_m` is computed in the original
coordinate frame as **sample minus full source**, with negative and positive
components showing which direction preview decimation shifts the display
centroid. It is not coral movement, coordinate registration, growth, drift, or
a measured tracking vector. A complete or single-distinct-locus acquisition
must report the zero vector without floating-point sampling artifacts.
Compare
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
their signed X/Y/Z difference, Euclidean magnitude, calibration factor, and
scale-only interval. The signed per-axis
`preview_minus_source_row_centroid_offset_scale_interval_m` is a list of
ascending [lower, upper] bounds, or `null` if no relative scale uncertainty
is supplied. For a negative offset the bounds must reverse the nominal scale
factor ordering; a genuine zero axis remains [0, 0]. If floating-point
resolution would falsely collapse a nonzero uncertainty interval, withhold
the corresponding interval and emit
`preview_centroid_offset_uncertainty_interval_below_numeric_resolution`.
These are **shared scale-only** bounds, not independent X/Y/Z measurement
errors, sampling confidence intervals, or registration uncertainty.
Include a synthetic rare XYZ row that is omitted by uniform decimation
and creates negative/positive signed offsets on distinct axes; reject
any biological movement interpretation. Verify the direct service,
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

### Ordered source XYZ/RGB provenance versus bounded preview evidence

For a colored ASCII PLY point-cloud acquisition, retain
`provenance.source_ordered_xyz_rgb_sha256`, a SHA-256 digest of the **entire
validated, normalized, ordered XYZ and uint8 RGB row sequence**, not just the
at-most-512 displayed points. A colorless XYZ input yields `null`. The digest
must change when an off-preview RGB observation changes even if the displayed
sample indices, geometry fingerprint, and preview-specific XYZ/RGB digest stay
identical. It must not depend on preservation/pinning options. Keep the
independent `source_payload_sha256` for the exact submitted ASCII PLY text:
normalized row fingerprints are not raw sensor-file byte signatures.

Use a synthetic 600-row PLY acquisition, mutate only a red channel at a known
unselected source index, and compare two standalone API responses. Verify the
full-source color fingerprint changes while the preview XYZ/RGB fingerprint
and ordered geometry fingerprint do not. Check a known two-row direct-service
SHA-256 oracle and a colorless negative control. Exercise the fingerprint in
**two executions of the same saved typed Workflow Builder graph**, comparing
complete persisted artifacts and their SHA-256 digests. This is source-evidence
integrity and reproducibility QC only; it cannot validate the original camera
file, absolute color, bleaching, living tissue, specimen identity or
calibration. Real coral scans and independent human review are still required.

### Reproducible ordered XYZ/RGB canonicalization across PLY exporters

The full-source fingerprint now publishes
`provenance.source_ordered_xyz_rgb_canonicalization` as
`ordered_normalized_float64_xyz_uint8_rgb_compact_json_utf8_v1` for colored
point clouds (or `null` for colorless sources). Parse validated ASCII PLY
properties by their **names**, not by column position; normalize finite XYZ
binary64 coordinates (including negative zero), preserve the original row
order and uint8 R/G/B values, then hash the compact UTF-8 JSON array of
ordered six-element `[x,y,z,r,g,b]` rows with SHA-256. This canonicalization
must be stable across exporters using different valid property arrangements,
comments and coordinate property types when the parsed observations are
identical. It is intentionally distinct from `source_payload_sha256`, which
must change when the submitted PLY text changes.

Use a two-row independent oracle with RGB properties interleaved among
reordered XYZ properties and a PLY comment, compared with conventional
XYZ/RGB property order. Assert identical complete ordered XYZ/RGB
fingerprints, preview colors and parsed geometry, but **different raw source
payload fingerprints**. Confirm standalone project API results and two
replays of an executable persisted typed Workflow Builder graph, including
byte-identical measurement artifact payloads and stable artifact SHA-256.
Neither digest proves the submitted text matches an original sensor file,
establishes color calibration or verifies biological condition/identity.
Review, physical calibration and representative coral references remain
release gates.

### Repeated raw XYZ/RGB acquisition observations

For imported colored ASCII PLY, report
`preview_rgb_variant_support.source_repeated_xyz_rgb_observation_rows` as
**total acquisition rows minus distinct normalized (XYZ, R, G, B) pairs**,
with `source_repeated_xyz_rgb_observation_fraction` using the full row count as
denominator. Report `preview_repeated_xyz_rgb_observation_rows` separately,
using displayed rows and displayed distinct pairs. Emit
`source_contains_repeated_xyz_rgb_observations` QC when the full-source
repeated-row count is nonzero, regardless of how the 512-point preview was
sampled. A complete preview may still contain repeated observations, and
preservation of distinct color pairs does not preserve every original row.

Validate on a 600-row two-locus, three-color reference: the source has 597
repeated rows; default display has 510 repeated rows, while opt-in pair
preservation displays the third color and has 509 repeated rows. Independently
check a 513-row acquisition containing exactly 512 distinct pairs (1 repeated
source row, zero repeated displayed rows) and a fully unique three-row
negative control (zero repeated rows and no warning). Check **standalone
project API output and twice-executed persisted typed Workflow Builder
artifacts**, comparing the complete payload and saved SHA-256. These counts
measure exact duplicate coordinate/color *records*, not sampling independence,
repeat measurements, organism abundance, colony condition, color calibration,
or independent biological replication. Do not turn duplicate-row counts into
experimental units; human QC and field reference validation are required.

### Shared trunk and anatomical length accounting

For multiple selected mesh-edge traces, report
`surface_traces_share_geometric_edges` in mesh-level QC when different
traces traverse the same nonzero exact source-coordinate endpoint pair,
regardless of direction or split mesh vertex indices. Do not merge the
traces or change their individual lengths. Absence of this warning does not
exclude partial collinear overlap, near-coincident routes, or biological
ambiguity.

Use a synthetic Y reference with a two-unit trunk and perpendicular three-
and four-unit tip branches. Two complete root-to-tip traces have lengths
five and six units, respectively, but their sum of eleven units double-counts
the trunk. A centerline graph with three unique segments would have total
length nine units. At 0.01 meters/unit these are 0.05 and 0.06 m versus
0.09 m for the graph; none is a verified biological measurement. Reverse one
trace and duplicate its junction and root indices to model an imported
seam. Include a negative control sharing only the junction. Exercise direct
measurement, standalone API and two saved typed mesh-preview graph runs,
including QC, provisional status and stable artifact hashes.

For a future anatomical centerline analysis, define each branch as an
ordered chain between a tip, root or junction, with stable segment IDs and
a source-geometry binding. Count each accepted segment once for total linear
extension; keep root-to-tip distance as a separate metric. Require independent
physical or expert-traced reference lengths and junction assignments, with
blinded reviewers resolving disagreements and recording occluded or ambiguous
branches. Evaluate branch-level detection and length error separately from
specimen-level total-length bias. A shared-edge warning is a QC aid, not an
implemented centerline extraction algorithm or a completed anatomical
validation gate.

### Provisional selected-edge chain decomposition

The exact-endpoint union additionally partitions selected nonzero edges into
maximal geometric chains: start at vertices of degree other than two, follow
degree-two vertices until the next terminal or junction, then consume any
remaining closed cycles. Each exact endpoint pair belongs to one chain only.
The source-coordinate ordering is deterministic across selection reversal,
selection order and split vertex IDs. A loop returning to a junction remains a
closed chain; no root, tip identity or biological branch order is inferred.

Check the partition against independent open-path, Y-junction, closed-cycle,
loop-with-tail and disconnected-crossing references. The sum of chain lengths
must reproduce the deduplicated union within floating-point resolution, with
no invented intersection or lost edges. Retain ordered source waypoints,
edge counts, calibrated lengths, scale-only bounds and per-chain numerical QC.
Missing or underflowed bounds must remain unavailable. Chain bounds share the
same scale calibration and are not independent uncertainty estimates.

The chain result is provisional selected surface geometry, not an extracted
anatomical skeleton. It does not split unequal overlapping segments, join
interior crossings, or resolve biological continuity across occlusions.
Human-reviewed source geometry, anatomical reference lengths and independent
specimen validation remain necessary before reporting total linear extension.

### Selected chain geometry fingerprints and junction context

Each provisional chain exposes `source_chain_geometry_sha256` with
canonicalization `ordered_float64_xyz_compact_json_v1`. Hash the ordered
source XYZ waypoints (binary64 values, signed zero normalized to positive
zero) serialized as compact UTF-8 JSON. The deterministic chain ordering
makes this digest independent of trace selection order, reversal, split
vertex IDs and meter calibration, provided the selected endpoint graph
and chain partition are unchanged. A changed waypoint changes the digest.
Retain the full reconstruction fingerprint and calibration evidence as
separate provenance; the chain digest alone cannot authenticate either.

The two `endpoint_graph_degrees` describe the graph degrees at the first
and last waypoint. A closed cycle returning to a junction can have degree
three or more at both ends; an isolated cycle has degree two at both ends.
These are not root/tip identities or verified anatomical junctions.

Check independent SHA-256 oracles for an open path, isolated cycle and
loop-with-tail, including signed zero, reversed selections, split-index
seams, calibration changes and a moved waypoint. Verify the same digests
and endpoint degrees in standalone and persisted typed mesh preview
workflow artifacts. This fingerprint is not a persistent biological ID,
registration across acquisitions, or evidence of completed human review.


### Unequal collinear selected-edge overlap audit

The exact endpoint-pair union still sums distinct nonzero edges. Its
`unequal_collinear_overlap_pair_count` counts unordered pairs of different
selected geometric edges with positive-length overlap on the same exact
3D source line. Repeated identical edges are already deduplicated and
do not contribute. Endpoint-only contact, parallel offset lines and
noncollinear crossings are excluded. Exact rational arithmetic on the
binary64 source coordinates avoids an implicit spatial tolerance.
A nonzero count triggers `surface_trace_unequal_collinear_edges_overlap`
in both union and preview QC. The original endpoint-pair length and
scale-only interval are **not corrected** for these overlaps; they can
overcount geometry. The separate `collinear_overlap_corrected_union`
reports source and calibrated lengths and scale-only intervals after
merging positive-length intervals on each exact source line. Lengths
are Euclidean binary64 distances summed before rounding. Its QC
withholds underflowed positive lengths or unrepresentable intervals.
Both union methods also surface their numerical QC codes in the preview's
`qc_warnings` so a valid full mesh cannot mask an unavailable trace length
or scale-only interval. Check positive underflow and positive uncertainty
below binary64 resolution; missing uncertainty and an explicitly zero
uncertainty must remain distinct from an unrepresentable interval.
Individual chain warnings also surface once per QC code in preview-level
`qc_warnings`. Validate a mixed network with a positive but underflowed
chain and a representable longer chain: both aggregate union measurements
may remain available, but the short chain length and interval must be null
and the preview must disclose its numeric warning. This is a resolution
qualification, not a biological branch classification.
Each canonical endpoint chain also reports `selected_trace_memberships`:
zero-based original trace indices and ordered, zero-based chain edge offsets.
Check that reversing or reordering selections and split-index seams retain
the same geometric chain fingerprint, while membership indices follow the
submitted selection order. Repeated traversals must not duplicate offsets;
unequal overlapping segments are not exact edge memberships. This evidence
locates the source selections for review, not a persistent organism identity
or verified anatomical branch assignment.
The separate `selected_trace_traversals` records every original nonzero
edge traversal in submitted trace/edge order, including repeats. It binds
the zero-based trace edge offset to the canonical chain edge offset and
reports whether its orientation follows that chain. Coincident consecutive
coordinates have no nonzero edge traversal and are omitted without
renumbering later offsets. Validate reversals, repeated traversals, rotated
closed loops and split-index seams against a directed source-edge scan.
Across all chains the traversal count must equal the number of submitted
nonzero edge steps; the same records must survive saved-workflow replay.
The orientation is a geometric convention, not evidence of growth direction.
For every canonical chain edge, `selected_chain_edge_support` reports the
zero-based edge offset, the number of distinct submitted traces containing
that edge, and the forward and reverse traversal counts. Derive membership
and support from indexed nonzero traversals, not a second geometric scan.
For a trace that follows an edge once and reverses it twice, the directional
counts are one and two, but the distinct-trace count is one. Across chains,
the sum of directional counts must equal the full nonzero traversal count.
Check these counts against an independent scan of the submitted paths,
including reversed and repeated selections, split-index seams, closed
loops, and zero-length steps. Verify standalone and twice-executed saved
typed workflow artifacts and stable hashes. Counts describe selection
support, not independent observers, biological replication, or confidence
in an anatomical branch. No uncertainty reduction is justified by repeats.
The endpoint graph and chain fingerprints remain unchanged; their
lengths need not sum to the corrected union. Do not interpret this result as anatomical total linear
extension. Near-collinear segments require separate registration and
uncertainty review. Check within- and cross-trace overlap, reversed
direction, containment, a disjoint or touching interval, 3D oblique
lines, and standalone versus saved typed workflow evidence.

Independent references: segments [0, 2] and [1, 2] have endpoint-pair
length 3 and corrected length 2 source units. Along direction (1, 2, 3),
intervals [0, 4], [1, 3], [2, 5], [5, 6] and a parallel offset interval
of length 4 have corrected length 10 times sqrt(14), versus 14 times
sqrt(14) before correction. Verify source and calibrated results,
scale-only bounds and saved-workflow replay. This correction is not
an anatomical centerline, biological identity, or completed human review.

### Connected selected-edge component inventory

The exact endpoint union also emits `endpoint_graph_components`, ordered
by the lexicographically smallest source XYZ vertex of each component
(`source_min_vertex_mesh_units`, signed zero normalized). Each component
reports vertex and distinct nonzero edge counts, terminal/junction counts,
cycle rank and zero-based indices into `endpoint_graph_chains`. Every
chain belongs to exactly one component, and component counts sum to the
aggregate endpoint graph. Chain indices refer to the current result only;
the source minimum is not an organism ID or a registration landmark.

Check against an independent submitted-edge partition for disconnected
crossings, mixed-length networks, isolated cycles, junctions and reversed
or repeated selections. Compare standalone preview and saved typed
workflow artifacts, including the existing replay/hash checks. Exact
endpoint connectivity does not weld interior crossings or partial
overlaps. Components may represent disconnected selections of one coral
or multiple corals; they do not establish biological identity, independence,
anatomical branch counts or completed human review. Each component also reports its exact-endpoint source edge length, calibrated
length in meters and scale-only interval. Sum distinct edge distances before
calibration and rounding; do not sum already-rounded chain measurements.
Unequal collinear overlaps can still double-count geometry, including across
components. The separately reported global collinear union is the appropriate
overlap-corrected geometric measure, not an anatomical centerline.

For the two disconnected crossing edges of length two source units each,
a scale of 0.01 m/unit with 10% relative uncertainty yields 0.02 m per
component and bounds [0.018, 0.022] m. Compare against direct edge enumeration,
including missing and full scale uncertainty and a component whose positive
calibrated length rounds to zero. Such a length and its interval must be null,
with component QC surfaced in the standalone and replayed workflow artifact.

Component review can also bind to `source_component_geometry_sha256`.
The versioned `sorted_float64_xyz_edges_json_v1` encoding hashes compact
UTF-8 JSON containing lexicographically sorted undirected endpoint pairs,
each pair ordered by XYZ, with binary64 coordinates and normalized signed
zero. Reversing or repeating a trace, changing its index aliases or
recalibrating the same source selection must preserve the digest. Changing
the selected endpoint pairs must change it, even when the component's
minimum vertex and vertex count remain unchanged. Compare independent
edge enumeration and standalone/replayed workflow hashes. This fingerprint
is source-coordinate dependent; it is not a persistent organism identifier,
a registration-invariant descriptor, or evidence of completed human review.

Component selection provenance now includes `selected_trace_indices`
(sorted zero-based submitted trace indices with at least one nonzero
edge in the component), `nonzero_edge_traversal_count` (including
repetitions) and `distinct_trace_edge_membership_count` (one count per
unique trace/undirected edge pair). The latter is not the number of
independent researchers or independent biological observations. Counts
must agree with direct enumeration of submitted source steps, even after
reversal, repeated traversal, split-index seams or zero-length steps.
Across components, traversal counts sum to the global nonzero traversal
count; membership counts sum to the distinct global edge count plus
cross-trace redundant traversals. Compare these fields in standalone
previews and repeated executions of the saved typed graph, including
artifact hashes. Selection provenance does not change source geometry
fingerprints, calibration uncertainty or provisional review status.

Component review now also exposes `source_endpoint_graph_landmarks`:
lexicographically ordered source XYZ coordinates (signed zero normalized)
and exact graph degrees for degree-one terminals and degree-three-or-more
junctions. Degree-two vertices are intentionally omitted; a closed isolated
cycle has no such landmarks. The Y-like loop-and-stem reference has the
junction [2, 0, 0] (degree 3) and terminal [2, 0, 4] (degree 1).
Compare direct submitted-edge degrees, reversed and repeated traces,
signed-zero aliases, disconnected components, and closed cycles. Verify
standalone and repeated saved typed workflow artifacts. These coordinates
are in uncalibrated source units and do not establish anatomical tips,
branch points, registration correspondences, growth direction or verified
organism identity. They do not change geometry fingerprints, scale-only
uncertainty, or the pending human-review requirement.

Each selected endpoint component now reports source XYZ axis-aligned
minimum/maximum coordinates (`source_axis_aligned_bounds_mesh_units`),
physical XYZ spans (`axis_aligned_spans_m`), and per-axis scale-only bounds
(`axis_aligned_span_scale_only_intervals_m`). Only selected nonzero edge
endpoints contribute; other mesh vertices do not. Compute calibrated spans
from source differences before rounding, not by subtracting rounded
display coordinates. A genuine zero span has [0, 0] limits when scale
uncertainty is supplied. A positive but unrepresentable span or interval
is null with component and preview QC, never a fabricated zero.
Compare crossing but disconnected selections, reversed/split selections,
closed cycles, signed-zero aliases, and mixed-scale underflow using the
standalone preview and repeated persisted typed graph. These orientation-
dependent dimensions describe selected geometry in unregistered source
axes, not anatomical length, colony size, or biological growth. The
intervals quantify scale uncertainty only, not confidence or registration
error. Human verification remains pending.

### Localizing unequal collinear overlaps

Each selected endpoint component reports its own
`unequal_collinear_overlap_pair_count`. The global union also reports
`cross_component_unequal_collinear_overlap_pair_count`: global distinct
positive-length overlap pairs minus those within components. Endpoint-only
contact, noncollinear intersections and repeated identical undirected edges
are excluded. A disconnected endpoint graph may still contain overlapping
geometry; this is not evidence for independent coral structures.

For collinear selections [0, 4], [4, 2], and [1, 3] along one axis, expect
two endpoint components, one within-component overlap pair and two
cross-component overlap pairs. Compare an independent exact-coordinate
pairwise projection oracle, standalone preview and two executions of the
persisted typed mesh-preview workflow, including artifact hashes. Do not
weld components, interpret overlap counts as independent observations, or
sum component lengths as an overlap-corrected biological measure. The
global collinear union remains the overlap-corrected geometric measure;
calibration and anatomical/identity verification remain unchanged.

Each endpoint component additionally carries a nested
`collinear_overlap_corrected_union` with its own source length, calibrated
meters, scale-only limits and QC. In the example above, the two local
corrected lengths are 4 and 2 source units (0.04 and 0.02 m at 0.01
m/unit), while the global corrected length is only 4 units. At 10% scale
uncertainty the local intervals are [0.036, 0.044] and [0.018, 0.022] m.
A local positive length that underflows remains null and its QC is visible
in the overall preview even when the global length is representable.
Check standalone and twice-replayed typed workflow payloads and hashes.
Local corrected lengths must not be summed as a global corrected length
when components overlap. Neither local nor global lengths establish
anatomical centerlines, independent replicates or verified identities.

The oblique reference maps the same three undirected edges onto direction
(1, 2, 3), reverses their submitted directions and repeats the long edge.
It retains two endpoint components, three distinct edges, four nonzero
traversals, one local overlap pair and two cross-component overlap pairs.
Local corrected lengths are 4 and 2 times sqrt(14) source units; the global
corrected length is 4 times sqrt(14), not their sum. Scale all nominal
lengths and scale-only limits by sqrt(14) relative to the axis-aligned
reference. Verify standalone results and two saved typed workflow runs
with identical artifacts and hashes. Repetition supplies no additional
independent biological evidence and does not establish identity or anatomy.

The exact-edge union and top-level preview QC must emit
`surface_trace_cross_component_collinear_overlap` once when positive-length
collinear overlaps occur between different endpoint components. The warning
is distinct from the general overlap warning, and is absent for local-only
overlaps, endpoint contact, and noncollinear interior crossings. Check it in
standalone and twice-replayed typed workflow artifacts. It prohibits adding
local corrected lengths as if they represented disjoint spatial support;
it does not establish any biological identity or independent replicate.

Longitudinal comparison provenance retains the original source payload SHA-256,
source asset ID, import format, byte count and integrity-check flag separately
for each timepoint, even when no pairwise registration or reidentification
review bundle exists. Missing legacy fields remain null. Validate the exact
original byte count and digest against a project-owned OBJ and compare the
standalone result with two executions of the same persisted typed graph. Reusing
that asset must still withhold cross-timepoint change metrics. An integrity
check confirms byte agreement only, not field acquisition independence,
calibration validity or specimen identity.

### Acquisition independence screening

Longitudinal comparison provenance now reports `acquisition_lineage_status`
and `independent_acquisition_verified`. Reuse of a project spatial asset
takes precedence over byte-identical payload reuse. Different payloads
with identical geometry are distinguished from other different payloads;
neither establishes an independent acquisition. Missing original digests
(including inline-only geometry and legacy previews) are explicitly
insufficient unless known asset reuse already determines the status.
The independent-acquisition flag always remains false: proof requires
review of the underlying raw acquisitions, not only reconstructed meshes.
Compare six synthetic lineage cases and confirm standalone and twice-run
persisted typed workflow artifact parity for reused imports. Existing
change-withholding rules and review-bundle canonical hashes are unchanged.

For a reused immutable project asset with missing legacy payload digests,
compare known byte counts, source formats and geometry fingerprints.
Conflicting known byte counts or formats emit
`reused_spatial_source_asset_metadata_inconsistent`; different valid
geometry fingerprints emit `reused_spatial_source_asset_geometry_inconsistent`.
Missing fields alone are not contradictions. Both warnings are scientific
QC, not verified evidence of corruption; all longitudinal change remains
withheld for reused assets. Confirm five legacy-record cases. Additionally,
replay a standalone and twice-executed saved graph with identical triangles
but a changed OBJ comment and doubled calibration scale: the fourfold
nominal area remains visible, while the biological change and rate are
withheld. The lineage status distinguishes rescaled re-export from exact
byte reuse, and both retain unverified identity and acquisition status.

For replayed longitudinal measurement provenance, require a canonical
lowercase hyphenated UUID for a non-null project source asset ID, consistent
with the pairwise review evidence schema. Reject whitespace, non-string
values, uppercase or compact UUID spellings and an asset ID attached to
inline indexed triangles. This is a syntax and consistency guard, not
authentication of asset ownership. Preserve historical records with missing
source format and digest: reuse of a valid asset ID still withholds change.
Exercise malformed and legacy artifacts directly, and compare standalone
and twice-executed saved typed graph results for a real imported project
asset, including identical artifact digests and unverified acquisition status.

Matching parsed geometry and a changed calibration also require withholding
longitudinal change when at least one observation is a known imported mesh
but the original byte lineage is incomplete (legacy missing digests or an
import converted to inline indexed triangles). Preserve both nominal
measurements, source provenance, the incomplete-lineage QC reason and
unverified acquisition/identity flags. Do not label these cases as proven
byte reuse or distinct-file re-export. Same-scale comparisons and pairs
of purely inline previews retain their existing descriptive behavior.
Check OBJ-to-PLY and OBJ-to-inline standalone results, three missing-digest
legacy permutations, and two runs of each persisted typed graph with
matching artifact digests. No geometry match proves biological identity.

A canonical project spatial-source asset ID is also evidence of an imported
original in legacy previews whose source format, byte count and digest
were not recorded. When geometry matches but scale changes, pairing such
an asset-linked preview with inline triangles must withhold longitudinal
change in either timepoint order. This is an incomplete-lineage QC
decision, not authentication of the asset ID or proof of byte reuse.
Exercise both legacy permutations, and compare actual project-owned OBJ
imports against PLY re-exports and inline triangles in the standalone API
and two runs of each saved typed workflow. Preserve original nominal
measurements, asset ID, available integrity-check evidence and unverified
identity; same-scale controls remain descriptive.

The order-sensitive primary mesh digest may change during a vertex reindex,
face reorder or winding reversal. When valid primary digests differ but
the complete nonempty multiset of exact surface-patch digests matches,
withhold longitudinal changes if scale differs and at least one observation
is a known imported original. Record
`longitudinal_change_withheld_rescaled_matching_surface_patches` and
preserve nominal measurements and existing source lineage statuses.
This conservative QC rule does not assert identical full indexed meshes:
unused vertices and internal connectivity can differ, and neither patch
hashes nor original file hashes authenticate biological identity. Missing,
malformed, partial or unequal patch digests do not establish a match.
Exercise reindexed/reversed PLY and inline triangles with OBJ text and
project-owned originals via standalone comparisons and twice-executed
saved typed graphs; retain same-scale controls and artifact hash parity.
Existing primary digests and review-bundle canonicalization remain intact.

Report `surface_patch_fingerprint_comparison` separately from acquisition
lineage and calibration: matching or different complete digest multisets,
or unavailable when either record has incomplete/invalid patch metadata.
Emit `matching_surface_patches_different_geometry_fingerprints` when the
complete multisets match but valid primary digests differ, including
same-scale comparisons. This is a screening flag for possible re-export,
not evidence of independent acquisition or specimen identity. The existing
recalibration withholding rule is unchanged; same-scale results remain
descriptive. Verify the flag in standalone and replayed typed artifacts,
with missing, malformed, partial and unequal digest controls.

Historical artifacts with complete matching surface-patch hashes but missing
or malformed primary mesh digests now emit
`matching_surface_patches_primary_geometry_fingerprint_unavailable`.
The same conservative recalibration withholding rule applies if at least
one timepoint is an imported original and both known scales differ.
Do not treat missing primary digests as evidence of different geometry.
Same-scale comparisons remain descriptive; incomplete patch metadata
cannot establish a match. Exercise both timepoint orders and both missing
and malformed primary digests, with same-scale and incomplete-patch
controls. Current producer artifacts retain valid primary digests; verify
the existing standalone and twice-replayed typed graph still distinguishes
reindexed geometry from missing primary provenance. No authentication of
legacy hashes, biological identity, or acquisition independence is implied.

If two valid primary indexed-geometry digests match but their complete
surface-patch digest multisets differ, report
`identical_geometry_surface_patch_fingerprints_inconsistent` and withhold
derived longitudinal changes, including scale-only change intervals.
Preserve nominal measurements and the conflicting provenance for review.
Missing or malformed patch metadata remains unavailable rather than
contradictory; different primary digests do not by themselves establish
this inconsistency. Check all eight primary/patch-state combinations
against the shared comparison engine. Confirm that consistent OBJ, PLY
and inline previews continue to agree across standalone and twice-executed
persisted typed workflow artifacts. A discrepancy is a reason to check
source and producer versions, not proof of corruption or biological change.

Equal valid primary indexed-geometry digests with contradictory known
topology counts also withhold derived longitudinal changes. Report
`longitudinal_change_withheld_inconsistent_topology` and preserve each
observation's original topology and nominal measurements. Check face,
edge-connected patch, boundary edge, nonmanifold edge and degenerate face
counts independently. Missing legacy counts remain unknown, not
contradictory; differing valid primary digests retain descriptive
reconstruction QC. Exercise sparse legacy artifacts and verify consistent
standalone and persisted typed Workflow Builder results. These are
provenance discrepancies requiring human review, not proof of biological
change or source authenticity.

Equal valid primary geometry digests also require consistent calibrated
dimensions: area scales quadratically and bounding-box diagonal scales
linearly. If either known measurement contradicts its corresponding
scale relationship, withhold derived longitudinal changes, rates and
scale-only change intervals; report
`longitudinal_change_withheld_inconsistent_calibrated_dimensions`.
Retain both nominal measurements and source QC for review. Missing scales
or extents do not establish a contradiction. Different or invalid primary
digests do not establish this equality constraint. Test zero and extreme
finite areas, inconsistent extents, and consistent and missing-evidence
controls. Replay historical typed artifacts and simulate a legacy producer
with a conflicting digest through the standalone endpoint and two executions
of one persisted typed graph, requiring identical comparison artifact hashes.
The dimensional check detects contradictory records; it does not establish
authenticity, anatomical branch length, or verified biological identity.

The dimensionless source-space surface-area/diagonal-squared descriptor
is independent of calibration. Equal valid primary geometry digests with
inconsistent known descriptors therefore also trigger
`identical_geometry_shape_ratio_inconsistent` and the calibrated-dimension
withholding flag, including when either historical scale is missing.
Retain the nominal descriptors; suppress derived comparisons rather than
assuming the same mesh changed shape. Allow relative rounding tolerance
(1e-8), keep missing descriptors unknown, and do not apply this equality
constraint to different or invalid digests. Test legacy records with
missing scales and both matching and conflicting descriptors; exercise
standalone and twice-executed persisted typed graphs with and without
scale metadata. This check is reconstruction QC, not biological identity.

Complete ranked patch-area fractions are also invariant to a common
calibration scale. For equal valid primary geometry digests, a ranked
profile total-variation distance greater than 1e-8 triggers
`identical_geometry_patch_area_distribution_inconsistent` and the existing
calibrated-dimension withholding flag. A concentration index alone cannot
establish equality of profiles. Missing legacy distributions remain unknown;
different or invalid primary digests retain descriptive reconstruction QC.
Preserve original nominal measurements and concentration descriptors, but
withhold derived longitudinal change, uncertainty and profile comparisons.
Validate a conflicting legacy digest with equal source-space total area and
extent but redistributed patch areas, including standalone and two runs of
the same persisted typed graph with equal comparison artifact hashes. This
is a consistency check, not biological fragmentation or identity evidence.

Equal valid indexed-geometry digests also require consistent per-patch
topology distributions, not just matching aggregate counts. Compare the
multiset of joint face, boundary-edge and nonmanifold-edge counts using only
fields available at both timepoints. Reordering complete patch rows does
not establish a conflict. Missing legacy arrays stay unknown. A conflict
emits `identical_geometry_patch_topology_distribution_inconsistent` and
uses the existing inconsistent-topology withholding flag. Retain nominal
measurements and aggregate QC; do not report derived biological change.
Test four faces in two patches with face-count profiles [3, 1] and [2, 2]
and identical aggregate boundary counts, including permutation, missing
array and different-digest controls. Simulate a legacy summary conflict in
the standalone API and two executions of one persisted typed graph; require
artifact equality and equal hashes. This is reconstruction QC, not proof
of geometry authenticity or biological fragmentation.

Equal valid indexed geometry digests with complete matching patch digest
multisets also require consistent digest-bound area fractions. Independently
ranked area fractions can conceal swapped descriptors while retaining the
same total surface area, concentration and topology. Sort digest/fraction
pairs (including repeated digests), compare the half-L1 distance at the
existing 1e-8 tolerance, and emit
`identical_geometry_hash_bound_patch_area_inconsistent` on contradiction.
Use the existing calibrated-dimensions withholding gate, retaining nominal
measurements and unverified identity. Incomplete historical patch hashes
remain unknown. Test two unequal-area patches with swapped hashes, jointly
permuted rows, missing hashes, a different primary digest and a consistent
control; replay the conflict through the standalone API and two executions
of a saved typed graph with artifact/hash equality. These checks establish
internal reconstruction consistency, not verified patch or colony identity.

Equal indexed geometry digests and complete matching patch digests also
require consistent digest-bound topology tuples for mutually available face,
boundary-edge and nonmanifold-edge counts. A joint unbound count multiset
can conceal reassignment of topology to another patch. Compare sorted tuples
of patch digest and available counts, preserving repeated digests as a
multiset. Emit `identical_geometry_hash_bound_patch_topology_inconsistent`
and use the existing topology withholding gate when the bound tuples differ
but the unbound distribution agrees. Missing historical digests or fields
remain unknown, not contradictory. Controls cover swapped counts, jointly
reordered rows, missing hashes, different primary geometry and unchanged
records; replay the swapped-count conflict via standalone API and two
executions of one persisted typed graph with equal artifacts and hashes.
These checks do not establish biological identity or anatomical branch length.

Equal valid indexed-geometry digests also require consistent source-axis
aspect ratios. Exchanging two unequal calibrated axis lengths can preserve
the full bounding-box diagonal and surface-area shape ratio while
contradicting the unchanged indexed geometry. Normalize each axis length
by the largest dimension, compare in source-axis order (relative tolerance
1e-8, absolute tolerance 1e-12), and report
`identical_geometry_axis_aspect_ratios_inconsistent` when the profiles
disagree. Use the existing inconsistent-calibrated-dimensions withholding
gate; preserve nominal area and extent measurements. Missing historical
axis vectors or all-zero extents remain unknown. This is an internal
reconstruction QC check, not evidence of rotation or anatomical growth.
Test swapped unequal axes with unchanged diagonal, missing calibration,
missing axis vectors, different geometry digest and consistent rescaling.
Replay the swapped-axis conflict through the standalone API and twice
through one persisted typed graph with identical artifacts and hashes.

For equal valid indexed-geometry fingerprints, the area-weighted surface
centroid relative to the source origin must also remain consistent after
uniform calibration. Normalize the three centroid coordinates by each
observation's positive calibrated bounding-box diagonal. Compare the
finite dimensionless vectors in source-axis order with absolute tolerance
max(1e-8, eight ULPs of either normalized coordinate) and zero relative
tolerance. This prevents a large source-origin offset from masking a
mesh-scale inconsistency while allowing floating-point roundoff. A contradiction reports
`identical_geometry_source_centroid_inconsistent` and uses the existing
inconsistent-calibrated-dimensions withholding gate. Preserve original
area and extent, but withhold longitudinal change and registered-centroid
derived quantities. Missing centroids, nonpositive or missing diagonals
and unrepresentable normalized vectors remain unknown. This check does
not validate registration or movement. Test shifted centroid with and
without historical calibration scale, missing centroid, different primary
geometry and consistent rescaling; replay a shifted legacy centroid via
standalone API and two runs of the same saved typed graph with matching
artifact hashes.

Include far-origin legacy controls at one billion mesh diagonals from the
source origin: consistent rescaling, a representationally small offset,
and shifts of either sign by one tenth of a diagonal. Require the latter
to withhold longitudinal quantities. Repeat through the standalone API
and two runs of one persisted typed graph with artifact/hash equality.
The threshold is a numerical consistency rule, not biological uncertainty.
