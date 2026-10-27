# ReefVision 1.4 implementation

Work in progress on isolated branch. Scientific 3D mesh measurement and Workflow Builder integration are the first planned vertical slice. This document does not imply release readiness.

## Local mesh file preview (in development)

The Workflow Builder workspace now offers a standalone, bounded OBJ/ASCII PLY/GLB
file picker. The local desktop UI reads a selected file and sends it to the
project-scoped local API mesh-preview endpoint, then renders the returned
bounded triangle sample using the existing interactive yaw/pitch/zoom viewer.

The current request contract limits OBJ and PLY files to 256,000 bytes and GLB
files to 262,500 bytes before base64 encoding. Backend geometry validation
still applies. The UI requests a positive meters-per-source-unit scale and
human-entered calibration evidence; optional relative scale uncertainty is
propagated into measurements. Calibration is **not** automatically verified.

Standalone preview results are transient. To persist a reproducible
measurement and provenance, users must configure and execute the typed
`mesh_surface_preview` node in a saved Workflow Builder graph. The full
mesh is used for scientific surface-area and dimension calculations; the
512-triangle visualization sample must never be treated as a biological
measurement or as evidence of specimen identity.

Outstanding: persistent asset ingestion and versioning, registered
coordinate frames, independent calibration review, persistent point-cloud asset ingestion,
validated anatomical branch lengths, longitudinal identity linkage, and
installed desktop/GPU/scientific acceptance. A separate bounded ASCII PLY
point-cloud preview and interactive viewer already exist, but their transient
visualization and chord measurements do not establish verified anatomy.

## Imported mesh byte-exact replay guard (provisional)

OBJ, ASCII PLY, and GLB mesh-preview requests may optionally provide
`expected_source_payload_sha256`, a lowercase 64-character SHA-256 digest
of the exact source file bytes. For OBJ/PLY the digest covers the submitted
UTF-8 text; for GLB it covers the decoded binary, **not** its base64 encoding.
If the supplied source does not match the expected digest, the standalone API
rejects the request and the saved executable `mesh_surface_preview` Workflow
Builder run fails without emitting a mesh measurement artifact. This also
catches byte changes that leave parsed geometry unchanged, such as OBJ
whitespace edits. The typed node exposes the same optional parameter.

The result provenance reports `source_payload_integrity_checked=true`
only when an expected digest was provided and matched. Older requests remain
valid, with the field `false`. Direct indexed-triangle requests cannot claim
an imported-file binding. This is a **source-content consistency check**,
not persistent asset ingestion, authentication, independent calibration
verification, coordinate registration, or specimen identification. Hashes
must be supplied from a trustworthy local asset record to be useful; a
matching attacker-controlled hash offers no security guarantee. Saved
workflows continue to retain the submitted bounded input payload and
measurement provenance under existing local project persistence.

## Imported point-cloud byte-exact replay guard (provisional)

The project-scoped standalone ASCII PLY point-cloud preview and executable,
typed, saved `point_cloud_preview` Workflow Builder node now accept optional
`expected_source_payload_sha256`. This must be the lowercase SHA-256 digest of
the exact UTF-8 PLY text submitted to the local API. A changed source, including
a comment-only edit that leaves parsed XYZ coordinates identical, fails closed:
the API rejects the measurement and a saved workflow run fails without
emitting a point-cloud measurement artifact. Raw XYZ arrays cannot claim an
imported PLY file binding.

The point-cloud provenance now includes `source_payload_sha256`,
`source_payload_size_bytes`, and `source_payload_integrity_checked`.
The preexisting `source_text_sha256` remains for compatibility. An unbound
legacy PLY request still works but reports `source_payload_integrity_checked=false`;
raw XYZ arrays have null source-file fields. These digests cover the **submitted
text**, not independently observed bytes from a filesystem; a caller-controlled
digest is not authentication. Matching content does not verify specimen identity,
scale calibration, registration, biological branch lengths, or independent
review. This guard is a prerequisite for future durable asset versioning,
**not** an implementation of persistent 3D asset ingestion.

## Scale-only surface-area bounds (provisional)

The standalone mesh API and saved `mesh_surface_preview` Workflow Builder
artifacts report `surface_area_scale_interval_m2` and
`edge_connected_patch_area_scale_intervals_m2` when a relative scale
uncertainty `u` is supplied. For measured area `A`, the lower and upper
bounds are `A * (1 - u)^2` and `A * (1 + u)^2`, respectively. This uses the
exact square-law dependence of area on a common multiplicative scale. The
existing `area_scale_uncertainty_m2 = 2 * u * A` remains a first-order
sensitivity estimate for backwards compatibility; it is **not** an exact
interval half-width.

These bounds represent **only** the caller-supplied scale range. They are
not statistical confidence intervals and do not include reconstruction,
segmentation, surface incompleteness, calibration verification, or
registration uncertainty. All areas remain `caller_supplied_unverified`;
an open or nonmanifold mesh must not be interpreted as a complete coral
surface without independent human review.

## Calibrated extent intervals (provisional)

Mesh previews and saved executable `mesh_surface_preview` Workflow Builder
artifacts now expose scale-only intervals for global and edge-connected-patch
axis-aligned dimensions and bounding-box diagonals. For any nonnegative
reported distance `L` and caller-supplied relative scale uncertainty `u`,
the interval is `[L * (1 - u), L * (1 + u)]`. When `u` is omitted, interval
fields are `null`; zero uncertainty produces equal bounds. The previous
first-order scale uncertainty fields are preserved for existing consumers.

These intervals use a **single shared multiplicative calibration error**,
not independent axis errors. They do not quantify geometry reconstruction,
surface incompleteness, registration, observer disagreement, or camera
distortion. Imported axes are unregistered: a bounding-box diagonal is
**not** a biological branch length, organism identity, or longitudinal
growth measurement. Calibration and interpretation require human review.


## Provisional enclosed mesh volume (scientific QC gated)

The standalone mesh-preview API and persisted executable `mesh_surface_preview`
Workflow Builder node now report `enclosed_volume_m3` and
`edge_connected_patch_enclosed_volumes_m3` for triangular patches that
have no open boundary edges, nonmanifold edges, inconsistent shared-edge
winding, or degenerate faces. Oriented tetrahedron sums use a local
reference point for translation stability. Either globally consistent
winding direction yields the same unsigned enclosed volume.

An invalid/open patch has `null` volume and an explicit QC warning.
When some patches are valid and others invalid, the per-patch values are
retained but **total enclosed volume is null**, not a misleading partial
total. Missing relative scale uncertainty leaves the interval fields null.
For supplied relative scale uncertainty `u`, scale-only bounds use the
cubic law `[V(1-u)^3, V(1+u)^3]`.

**Do not interpret this as coral biomass, tissue volume, or validated
organism size.** Topological edge checks do not detect self-intersections,
internal voids, surface reconstruction artifacts, overlapping components,
or incomplete observations. Calibration, coordinate registration,
organism identity, and biological completeness remain unverified.
Human scientific review is required before interpreting these provisional
geometric results. No confidence intervals are inferred.

## Vertex-touching closed mesh patches (aggregate volume withheld)

Distinct edge-connected patches may share one or more source vertex indices
without sharing any mesh edges. Even if each patch separately passes closed,
oriented, nondegenerate edge checks, their union has a nonmanifold point
contact and is not a single regular closed surface. The standalone preview
and persisted executable `mesh_surface_preview` node now expose
`vertex_touching_patch_vertex_count` and the QC warning
`vertex_touching_mesh_patches`. When this count is positive, the
`enclosed_volume_m3` aggregate and its scale-only interval are withheld
(`null`) with `enclosed_volume_vertex_touching_patches` QC, while
individual provisional patch volumes remain available for inspection.

This conservative gate does **not** detect all nonmanifold vertex fans,
self-intersections, coincident-but-separately-indexed points, or actual
organism identity. No human-verified biological volume is inferred. Saved
Workflow Builder parity tests cover both vertex-touching and vertex-disjoint
closed tetrahedral patch pairs.

## Per-patch Euler topology diagnostics (provisional)

The standalone mesh-preview API and saved executable `mesh_surface_preview`
Workflow Builder artifacts expose `edge_connected_patch_vertex_counts`,
`edge_connected_patch_edge_counts`, and
`edge_connected_patch_euler_characteristics`. Each characteristic is the
combinatorial count `V - E + F` for one **edge-connected** triangle patch,
using referenced source vertex indices and unique undirected edges. Patches
that meet only at a vertex remain separate; shared source vertices may be
counted in each patch, so the patch values must not be mistaken for a global
mesh Euler characteristic.

The diagnostic is useful for detecting changes in reconstruction topology
across scans, but it does **not** prove manifoldness, genus, biological
identity, surface completeness, or organism condition. Self-intersections,
nonmanifold vertices, and reconstruction artifacts can invalidate topological
interpretation even when edge incidence appears closed. Geometry and
calibration remain caller-supplied and unverified; no genus or longitudinal
reidentification is inferred from these counts.


## Boundary-component lengths (provisional)

The mesh preview engine now reports `boundary_loop_perimeters_m` for
individual simple closed boundary-edge cycles and
`noncycle_boundary_component_lengths_m` for branching/pinched/open
boundary components. Per-edge-connected-patch nested arrays retain
component membership. Component order is deterministic by the smallest
source vertex index within each patch. The total of these lengths
equals the mesh boundary-edge length, within floating-point rounding.

For each component length `L` and caller-supplied relative calibration
uncertainty `u`, the optional scale-only interval is
`[L * (1-u), L * (1+u)]`. The global and per-patch fields preserve
`null` when uncertainty is not supplied, rather than implying zero
uncertainty. The standalone API and saved executable `mesh_surface_preview`
Workflow Builder node use the same engine and persist the same results.

A topological boundary loop is **not** a confirmed biological opening,
coral branch circumference, skeleton centerline, or organism identity.
These measurements remain `caller_supplied_unverified`, even when a
numerical uncertainty interval is provided. Reconstruction defects,
registration uncertainty, and observer error are not represented.

## Longitudinal mesh surface-area change per elapsed day (provisional)

The standalone `mesh-longitudinal-comparison` endpoint and the persisted,
executable `mesh_longitudinal_comparison` Workflow Builder node now report
`average_surface_area_change_m2_per_day` as the signed difference between
two provisional mesh surface areas divided by the actual elapsed UTC days.
The accompanying `average_surface_area_change_scale_interval_m2_per_day`
is computed by dividing the conservative two-timepoint scale-only difference
interval by the same positive elapsed duration. Missing scale intervals stay
`null`; negative changes and uncertainty bounds retain their signs.

This is a **descriptive two-observation average**, not a fitted growth rate,
annualized biological growth, or a validated estimate of coral condition.
A different camera angle, mesh reconstruction, visibility, occlusion, or
registration may change measured area without biological change. Both
observations require the same *provisional* specimen ID, distinct observation
IDs, increasing timezone-aware timestamps, and the same project; none of
these establishes verified reidentification. The result retains unverified
identity, calibration, and coordinate-registration provenance and emits the
`average_change_per_day_is_not_a_biological_growth_rate` QC warning.

Regression tests in `test_spatial_mesh_longitudinal_v14.py` cover positive
and negative signed rates, 48-hour intervals, missing uncertainty, and exact
standalone-versus-executed-saved-workflow payload parity. CI, independent
scientific validation, and installed Windows acceptance remain outstanding.

## Longitudinal axis-aligned 3D extent (provisional)

The standalone mesh longitudinal comparison endpoint and executable persisted
`mesh_longitudinal_comparison` Workflow Builder node now additionally report
the before/after axis-aligned bounding-box diagonal (m), signed change (m),
and average signed change per elapsed UTC day (m/day). Where both observation
previews include valid scale-only diagonal intervals enclosing the nominal
values, conservative difference and per-day bounds are computed by subtracting
opposite interval endpoints. Missing dimensions or uncertainty remain
`null`, with explicit QC warnings, rather than being imputed.

**Important:** An axis-aligned bounding-box diagonal depends on scan
orientation and reconstruction coverage. It is **not** a coral branch length,
biological extension rate, verified growth, or evidence of specimen
reidentification. The new fields are descriptive geometric diagnostics only.
Registration, independent calibration review, observation identity, and
reconstruction uncertainty remain unverified. The same engine is exercised
through the standalone endpoint and saved typed Workflow Builder execution.

### Relative change in longitudinal 3D extent

The same standalone and saved-workflow comparison artifacts now include
`relative_axis_aligned_bounding_box_diagonal_change_percent` and
`relative_axis_aligned_bounding_box_diagonal_scale_interval_percent`.
The signed percentage is `100 * (later / earlier - 1)`, defined only
for a positive baseline diagonal. When both scale-only intervals exist
and the earlier lower bound is positive, the conservative interval is
`[100 * (later_low / earlier_high - 1), 100 * (later_high / earlier_low - 1)]`.
Zero baseline or an interval spanning zero yields `null` rather than
infinity or fabricated certainty. Missing uncertainty also yields a
`null` uncertainty interval. The QC flag
`relative_axis_aligned_extent_change_unavailable` identifies undefined
relative change. All measurements remain provisional, orientation-dependent,
and **not** verified coral growth or reidentification. Saved Workflow Builder
parity, negative changes, and zero-baseline regression cases are included.

## Longitudinal reconstruction QC propagation

The standalone `mesh-longitudinal-comparison` endpoint and persisted,
executable `mesh_longitudinal_comparison` Workflow Builder node now retain
`before_mesh_qc_warnings` and `after_mesh_qc_warnings` from the original
timepoint previews. When either source reports mesh QC, the comparison adds
`source_mesh_qc_requires_review`. A change in recorded mesh import format or
calibration method adds `mesh_source_formats_differ_between_observations`
or `calibration_methods_differ_between_observations`, respectively.

These warnings do not invalidate the numerical difference or establish
verified biological change: open meshes, reconstruction artifacts, and
different measurement protocols can confound apparent coral surface-area
change. The comparison preserves both observations' original QC rather than
silently replacing it with a single clean-looking longitudinal result.
Missing geometry fingerprints do not count as identical scans. Malformed
source QC lists fail validation rather than being silently discarded.

The existing saved-workflow parity regression asserts propagation of open
mesh QC, and a separate API regression exercises mixed OBJ/indexed-triangle
inputs and differing calibration methods. Neither scan identity nor
calibration is automatically verified; physical/scientific acceptance remains
required.

## Longitudinal project scope and canonical observation times

The standalone longitudinal comparison and persisted executable
`mesh_longitudinal_comparison` Workflow Builder node use the same comparison
engine. Each source measurement must contain a nonempty string `project_id`,
and both projects must match. Missing, malformed, or cross-project provenance
cannot silently become a scientific comparison. Source `provenance` must be a
mapping, and the existing specimen, observation, calibration, and chronology
checks still apply.

The comparison retains the original source timestamp strings in
`before_observed_at_utc` and `after_observed_at_utc`, and additionally
records `before_observed_at_utc_normalized` and
`after_observed_at_utc_normalized` as canonical UTC ISO-8601 strings ending
in `Z`. This makes offset-equivalent timepoints directly comparable without
overwriting original field evidence. The elapsed duration already uses
timezone-aware instants, not naive wall-clock subtraction.

These checks establish neither specimen reidentification nor spatial
registration. Geometric changes remain provisional, with human scientific
verification required before any biological growth claim.

## Identical-geometry calibration consistency QC (provisional)

When both observations carry the same syntactically valid lowercase 64-character
SHA-256 geometry fingerprint and valid meters-per-mesh-unit scales, the
longitudinal engine checks whether their
surface-area ratio matches the **square** of the calibration-scale ratio.
It compares logarithms for positive areas to avoid floating-point overflow;
a zero/nonzero mismatch is also flagged. The
`identical_geometry_area_inconsistent_with_calibration_scale` warning means
that identical recorded source geometry and calibration alone do not explain
the two reported areas. This may indicate stale or corrupted previews,
different processing, or incorrect metadata; it is **not** evidence of
biological growth. Missing scale metadata does not generate a fabricated
consistency conclusion. The warning is preserved in standalone results and
persisted typed Workflow Builder comparison artifacts; scientific identity,
calibration, and coordinate registration remain unverified.


### Geometry fingerprint input QC

Longitudinal comparisons only apply identical-source and recalibration
consistency warnings when both recorded geometry fingerprints are valid
lowercase 64-character hexadecimal SHA-256 strings. A missing, uppercase,
truncated, or placeholder fingerprint produces
`geometry_fingerprint_missing_or_invalid` and cannot trigger the
`identical_geometry_fingerprint` assertion. This is a **format check only**:
caller-supplied fingerprints are not authenticated or evidence of the same
biological organism. The original fingerprint values remain in provenance for
audit. Standalone and saved Workflow Builder comparisons use the same rule.

## Exact-zero followup versus numerical underflow

The standalone longitudinal comparison and saved, typed
`mesh_longitudinal_comparison` Workflow Builder node distinguish a **reported
zero** followup area or axis-aligned extent from a strictly positive geometric
ratio that underflows floating-point precision. With a positive baseline and
valid calibration scales, an exact zero followup produces a normalized ratio
of `0.0`. A positive ratio too small to represent produces `null` and the
existing `scale_normalized_area_ratio_out_of_numeric_range` or
`scale_normalized_extent_ratio_out_of_numeric_range` QC warning instead.
The latter must not be interpreted as complete disappearance.

A zero followup after a positive baseline also raises
`zero_followup_surface_area_requires_reconstruction_review` or
`zero_followup_extent_requires_reconstruction_review`, respectively.
A zero area or extent may arise from degenerate, incomplete, or failed
reconstruction rather than biological loss. No organism mortality, tissue
loss, verified reidentification, or growth conclusion is inferred. A
standalone-versus-saved-workflow regression uses an explicitly degenerate
followup mesh and compares the persisted artifact byte-for-byte at the
JSON-payload level; a separate regression retains positive-underflow QC.

## Identical-source topology metadata consistency (provisional)

When two timepoints claim the **same syntactically valid SHA-256 geometry
fingerprint**, calibration changes cannot alter the original triangle count,
connected-patch count, boundary-edge count, nonmanifold-edge count, or
number of degenerate faces. If any available topology counts disagree, the
comparison emits `identical_geometry_topology_metadata_inconsistent` in
addition to `reconstruction_topology_changed_requires_review`. This is a
provenance and reconstruction-integrity warning, **not** a biological change
or organism reidentification. Missing legacy topology fields retain the
`reconstruction_topology_comparison_incomplete` warning rather than inventing
missing values. Invalid or different fingerprints cannot trigger the
identical-source-specific warning. The same comparison engine is used by the
standalone endpoint and executable persisted Workflow Builder node; neither
verifies the authenticity of caller-provided fingerprints.

## Pairwise coordinate-registration diagnostics (provisional)

The standalone longitudinal mesh comparison API accepts optional
`registration_evidence` with source/target frame identifiers, alignment method,
RMS residual in meters, matched correspondence count (at least three), and an
evidence note. The frame IDs must match the observations. Non-finite/negative
residuals, malformed counts, and unrecognized fields (including any caller
`verified` flag) are rejected. The executable, saved Workflow Builder
`mesh_longitudinal_comparison` node accepts the same typed evidence and
persists it in the comparison artifact.

**This is an audit record, not a registration algorithm or approval.** A low
RMS residual does not demonstrate independent accuracy, valid transformations,
adequate coverage, or coral identity. The service does not compute or verify
a transform: `coordinate_registration_verified` remains false and the
comparison remains provisional with explicit review warnings. Missing
registration evidence stays null rather than being inferred from matching
frame labels. Full transform/landmark storage and independent human review
remain future work.

## Observation-bound reidentification notes (provisional)

The standalone longitudinal comparison API and executable persisted
`mesh_longitudinal_comparison` Workflow Builder node accept optional
`reidentification_evidence` with earlier/later observation IDs, a bounded
observer identifier, a matching method (visual morphology, survey tag,
photo match, or other), and an evidence note. The evidence must reference
exactly the observations being compared; unexpected fields, including
`verified: true`, are rejected. Notes are preserved in the comparison
provenance and saved workflow artifact.

These are **unverified caller-supplied matching notes**, not verified
reidentification or a biological condition score. The output retains
`specimen_identity_verified: false` and emits a review-required QC warning;
missing evidence is recorded explicitly. Independent human review and
project-scoped identity records are still needed before longitudinal growth
or condition claims. Existing comparisons without this optional evidence
remain supported.

### Reidentification evidence bound to source geometry (Track C, 2026-10-26)

Pairwise `MeshReidentificationEvidence` can now include optional
`before_geometry_sha256` and `after_geometry_sha256` fields. When supplied,
**both** lowercase SHA-256 fingerprints are required and must match the two
source mesh preview provenance fingerprints. Mismatches are rejected rather
than silently reusing notes across reconstructions with the same observation
labels. Earlier evidence without hashes remains readable, with
`reidentification_geometry_binding_unavailable` QC. Fingerprint equality
binds evidence to supplied geometry bytes; it does **not** verify biological
identity, capture location, calibration, or an independent reviewer.

The standalone longitudinal API and persisted typed Workflow Builder node
share this validation engine. Regression tests cover valid binding, cross-mesh
reuse, malformed/partial hashes, legacy evidence, post-validation mutation,
and saved-workflow artifact parity. CI and Windows installed-GUI/GPU scientific
acceptance are separate release gates, not implied by these tests.


### Independently attributed reidentification review (Track C, 2026-10-26)

Pairwise reidentification notes now optionally retain `independent_reviewer_id`,
`independent_review_decision` (`supports_match`, `disputes_match`, or
`inconclusive`), and `independent_review_note`. These fields are an
all-or-none audit record: incomplete reviews and reviews attributed to the
original matching observer are rejected. Legacy evidence without a separate
reviewer remains valid but carries
`reidentification_evidence_requires_independent_review` QC.

An independent reviewer decision is preserved with the exact observation
pair in both the standalone comparison API and saved, executable
`mesh_longitudinal_comparison` Workflow Builder artifacts. The engine
emits `reidentification_independent_review_recorded_not_identity_verification`
for any recorded review and explicit dispute/inconclusive QC when applicable.
A supporting review is **not** an approval workflow or a verified biological
identity determination: `specimen_identity_verified` remains false and
`reidentification_evidence_review_status` remains
`caller_supplied_unverified`. Review notes cannot establish calibration,
spatial registration, anatomical growth, or biological condition. Regression
coverage includes partial/self-review rejection, mutated evidence,
disagreement QC, and standalone-versus-persisted-workflow artifact parity.

## Longitudinal registered-centroid versus landmark RMS (provisional)

The standalone 3D longitudinal comparison and the persisted typed
`mesh_longitudinal_comparison` Workflow Builder node now include
`registered_centroid_separation_to_registration_rms_ratio`. This is the
Euclidean separation between two reconstruction surface centroids after
applying a caller-supplied source-to-target rigid transform, divided by the
reported positive landmark-fit RMS residual. The result is dimensionless.

A missing centroid or transform, zero RMS, or a floating-point out-of-range
ratio yields `null` with explicit QC. A true zero centroid separation with
positive RMS yields zero. Tests cover these edge cases and compare the
standalone artifact with the saved, executed Workflow Builder result.

**This ratio is not a confidence interval, positional uncertainty estimate,
statistical significance test, or evidence of coral movement or growth.**
Landmark-fit RMS describes the supplied correspondence fit, not the
reconstruction surface-centroid error distribution. Calibration, specimen
identity, registration, and biological interpretation remain unverified and
require independent scientific review.


## Longitudinal reconstruction QC rates (provisional)

The standalone mesh-longitudinal API and saved executable
`mesh_longitudinal_comparison` Workflow Builder artifacts now include
`before_reconstruction_qc_rates`, `after_reconstruction_qc_rates`, and
`reconstruction_qc_rate_changes_after_minus_before`. Each record reports
degenerate-face fraction, boundary edges per face, and nonmanifold edges per
face, with denominators taken from the corresponding timepoint's face count.
These are **descriptive reconstruction diagnostics**, not biological condition
scores. Boundary and nonmanifold edges per face are rates, not probabilities;
they may exceed one. Changes can reflect sampling, meshing, resolution, or
segmentation differences rather than coral tissue condition or growth.

Missing topology fields or zero-face meshes yield `null` rates and changes,
never fabricated zero defects. Scientific QC warnings flag that the rates
cannot establish biological condition. The source counts, provisional
measurement status, provenance, and independent review requirements remain
unchanged. A saved-workflow parity test exercises the new fields.


## Longitudinal reconstruction triangle-count comparability (provisional)

The shared standalone and saved, executable `mesh_longitudinal_comparison`
engine now reports `reconstruction_face_count_ratio_after_to_before`.
A ratio of 2 means the follow-up reconstruction contains twice as many
triangles as the baseline; it does **not** mean twice the coral surface,
growth, or resolution. Changes in triangulation, coverage, mesh decimation,
and reconstruction settings can affect normalized topology QC rates, so
unequal available counts trigger an explicit comparability-review warning.
A known zero-face follow-up yields a true zero ratio when the baseline has
faces; missing counts or a zero-face baseline yield `null` rather than a
fabricated value. Numerically unrepresentable ratios are withheld. All
measurements remain provisional, and human scientific review is required.


## Project- and timepoint-bound 3D registration (Track C, 2026-10-26)

Provisional `MeshRegistrationEvidence` now optionally binds the registration
to `project_id`, a paired `source_observation_id` /
`target_observation_id`, and paired timezone-aware
`source_observed_at_utc` / `target_observed_at_utc`. When supplied,
these must match the project, observation IDs and actual UTC instants in the
two source mesh previews. Incomplete pairs are rejected. Offset-equivalent
timestamps compare as the same instant; a changed survey date, project or
observation label cannot silently reuse stale registration evidence.

Older records without these optional bindings remain readable, but emit
`registration_project_binding_unavailable`,
`registration_observation_binding_unavailable` and/or
`registration_timepoint_binding_unavailable` QC. Paired source-geometry
SHA-256 bindings and coordinate-frame checks still apply independently.
The standalone API and saved, executable typed
`mesh_longitudinal_comparison` Workflow Builder node use the same
validation engine and preserve the supplied evidence in provenance.
Regression coverage includes valid bindings, mismatched projects and
observations, stale timestamps, partial records, timezone-equivalent
instants, legacy warnings and mutated model objects.

**These are provenance consistency checks, not independent verification.**
Neither matching project/observation metadata nor matching geometry
fingerprints establish correct alignment, specimen identity, calibrated
physical movement, or coral growth. All measurements remain provisional
until scientific and installed-desktop acceptance are completed.


### Independently attributed registration review (Track C)

Pairwise 3D registration evidence now accepts optional registration-operator
attribution and a separately attributed reviewer, decision, note and
timezone-aware review timestamp. A reviewer cannot be the operator; incomplete
review fields, dates preceding the later observation, and post-construction
mutations are rejected. Legacy unreviewed evidence remains readable with
explicit missing-attribution/review QC warnings.

Supporting, disputing and inconclusive reviewer decisions are **audit records
only**. Disputes and inconclusive decisions produce additional QC warnings.
A supporting decision never sets `coordinate_registration_verified` to true
and does not certify calibration, alignment, uncertainty or coral movement.
Standalone and persisted typed Workflow Builder comparisons use the same
validation engine and preserve review provenance in their artifacts.

### Withholding longitudinal organism changes after a disputed match

When an independently attributed reidentification reviewer explicitly
records `disputes_match`, ReefVision now withholds paired specimen-change
estimates, including surface-area and extent differences, relative changes,
daily rates, scale-only change intervals, and registered surface-centroid
offset/separation measurements. These fields are `null`, not zero. A
`longitudinal_change_withheld_disputed_specimen_identity` QC warning and
`provenance.longitudinal_change_withheld_due_to_identity_dispute: true`
explain the decision. This is a conservative scientific guard against
interpreting two potentially different colonies as a growth time series.

Original per-observation measurements, timestamps, mesh reconstruction QC,
registration diagnostics, and reviewer notes remain available for audit.
Missing identity review still leaves any descriptive changes **provisional**,
not verified. An explicitly `inconclusive` independent identity review now
also withholds paired change estimates: insufficient evidence of a match
cannot support an organism growth comparison. The distinct
`longitudinal_change_withheld_inconclusive_specimen_identity` QC warning
and `provenance.longitudinal_change_withheld_due_to_inconclusive_identity_review`
flag preserve the review reason without conflating it with a disputed match.
The original observations, reconstruction QC and attributed review remain
available for audit. The standalone API and saved, executable typed Workflow
Builder node share the comparison engine, with dedicated disputed-match,
inconclusive-review and persisted-artifact parity regressions. Neither
decision establishes verified identity, growth, or Windows desktop acceptance.

## Mesh triangle-area concentration QC (provisional)

Standalone `mesh-preview` responses and persisted executable
`mesh_surface_preview` Workflow Builder artifacts now include
`largest_triangle_area_fraction` and
`area_weighted_effective_triangle_count`. The former is the largest
triangle's area divided by the **full-resolution** mesh surface area. The
latter is `1 / sum((triangle_area / total_area)^2)`, a reciprocal
area-concentration index analogous to an effective number of triangles.
For two equal-area triangles the values are `0.5` and `2`; for
one triangle with all positive area they are `1` and `1`.
Zero-area triangles contribute no area weight. An entirely zero-area mesh
reports `null` for both metrics, not an invented concentration.

The engine uses `math.fsum` for the total area and squared shares to
reduce rounding error. These descriptors are **scale-invariant mesh
tessellation diagnostics**: they do not estimate surface reconstruction
accuracy, geometric registration, coral tissue area, specimen identity,
biological sample size, or uncertainty. No arbitrary mesh-quality pass
threshold or human verification is inferred. Full mesh areas and the
existing calibration-scale intervals remain the scientific calculation
basis; decimated preview triangles do not change these metrics.
Standalone, direct-service, and saved-workflow regression cases cover
unequal triangles, zero-area triangles, provenance, and artifact parity.
