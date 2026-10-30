# ReefVision 1.4 — mesh measurement interpretation

A connected triangle patch is a geometric component, not an identified coral colony. A disconnected mesh may contain multiple fragments, reconstruction artifacts, or both. Do not interpret aggregate surface area as an individual organism's area without human verification of patch membership.

Unreferenced vertices must not change calibrated dimensions. Preserve the original geometry hash and report the excluded-vertex count. Calibration uncertainty reflects only scale uncertainty, not photogrammetric reconstruction, segmentation, occlusion, or tissue-boundary error.

Any longitudinal growth comparison must require reviewed organism identity, comparable calibration and acquisition methods, and explicit provenance for each timepoint. Current mesh previews remain provisional, including saved Workflow Builder artifacts.

Per-edge-connected-patch areas are reported in square meters, ordered by the first
face in each patch. Their scale uncertainties assume a common relative scale error;
these are not independent confidence intervals. Patch indices are not persistent
organism identities and must not be used to infer biological growth or survival.

Per-patch global-axis dimensions (meters) and their scale-only uncertainty are
calculated from vertices referenced by that patch's faces. These bounding-box
extents do not measure skeletal branch length or guarantee anatomical alignment;
comparison across timepoints requires a reviewed common coordinate frame.

Per-patch degenerate-triangle counts localize zero-area faces without silently
removing them from the input geometry or claiming a valid enclosed surface.
They must be reviewed alongside topology warnings before biological interpretation.

Open-boundary edge lengths are reported in meters both for the entire mesh and
for each edge-connected patch. Shared interior edges are excluded. These lengths
measure exposed mesh edges (which may reflect incomplete photogrammetry), **not**
coral branch lengths, colony perimeter, or verified tissue boundaries. Scale-only
uncertainty is a common multiplicative error; absent scale uncertainty stays
unknown rather than being treated as zero. Human review remains required.

New `boundary_edge_length_scale_interval_m` and
`edge_connected_patch_boundary_length_scale_intervals_m` fields provide exact
lower/upper bounds for a **shared multiplicative calibration-scale error**:
`[L(1-u), L(1+u)]` for relative scale uncertainty `u`. They are not
confidence intervals or estimates of mesh reconstruction uncertainty. Unknown
`u` yields null intervals, while explicitly zero uncertainty yields
`[L, L]`. The standalone endpoint and persisted `mesh_surface_preview`
Workflow Builder node share this calculation and preserve unverified
calibration provenance.

Exact per-patch geometry SHA-256 fingerprints are calculated from sorted triangle
coordinates, ignoring source vertex numbering, triangle order, and winding. They
support audit of unchanged geometry through standalone and saved Workflow Builder
analyses. Fingerprints are **not** persistent organism identities, registration,
or proof of biological reidentification; any coordinate change may change a hash.

Area-weighted surface centroids are calculated from triangle areas, not the
average of all mesh vertices. They are reported in calibrated meters relative
to the **unregistered source-coordinate origin** for each edge-connected patch
and for the aggregate surface. A patch with zero total triangle area has an
undefined centroid (null), accompanied by a QC warning. Reported centroid
uncertainty includes only multiplicative scale uncertainty relative to that
origin; unknown scale uncertainty remains null. It does **not** include
registration, reconstruction, coordinate-origin, navigation, or biological
localization error. Do not interpret a centroid displacement between surveys
as growth, movement, or reidentification without reviewed registration and
organism identity.

Global-axis bounding-box diagonals are calibrated lengths spanning each mesh
or edge-connected patch's axis-aligned bounding box. They are upper bounds on
pairwise distances between referenced vertices, not observed biological branch
lengths or Feret diameters. They depend on orientation, and comparisons across
time require reviewed registration, calibration, and organism identity.
Uncertainty is scale-only; missing uncertainty remains null, not zero.

## Point-cloud chord integrity in decimated previews

The standalone ASCII PLY/XYZ point-cloud endpoint and the executable, saved
`point_cloud_preview` Workflow Builder node use the same bounded measurement
service. Selected point-pair chords refer to **original point indices**, not
the 512-point visualization sample. New artifacts persist the two calibrated
endpoint coordinates and their chord distance even if display decimation omits
one or both endpoints. The read-only viewer now checks the internal agreement
of those stored coordinates and reported chord distances, and cross-checks
sampled endpoints where available. Malformed or contradictory metadata fails
closed. Older artifacts without embedded endpoints remain displayable, but a
chord with an unsampled endpoint cannot be cross-checked by the viewer.

This check detects inconsistent **saved artifact metadata**; it does not
independently validate the original scan, its point correspondence, coordinate
registration, or calibration. All chords remain provisional straight-line
distances, **not** anatomical coral branch lengths. The source-order geometry
fingerprint is an audit aid, not an organism identity or a review decision.

The viewer also requires source-axis extrema coverage to be recorded as a
**paired** omission list and coverage verdict. A verdict without the list (or
a list without its verdict) is rejected rather than interpreted as verified
coverage. Older artifacts missing both fields remain readable with coverage
explicitly unassessed. This display QC never changes full-cloud measurement,
scientific verification status, or saved Workflow Builder provenance.

## Boundary-cycle topology QC

The mesh engine now distinguishes **closed boundary-edge cycles** from
**noncycle boundary components** in each edge-connected patch. Only edges
incident to exactly one triangle participate. A connected boundary graph
counts as one loop only when every referenced boundary vertex has degree two.
Branches, pinches, and open chains are counted separately rather than being
misrepresented as complete cycles.

The fields `boundary_loop_count`, `noncycle_boundary_component_count`,
`edge_connected_patch_boundary_loop_counts`, and
`edge_connected_patch_noncycle_boundary_component_counts` preserve these
diagnostics in standalone API responses and executed saved Workflow Builder
artifacts. A noncycle component adds the `noncycle_mesh_boundary_components`
QC warning. Existing surface-area, boundary-length, and enclosed-volume
calculations are unchanged; open surfaces already have their provisional
enclosed volume withheld.

These are **combinatorial properties of the indexed triangle mesh**, not
biological holes, coral branching structures, proof of watertight geometry,
or a measure of reconstruction completeness. Duplicate positions with
different vertex indices and nonmanifold edges can affect topology; review
them alongside existing QC warnings. The imported coordinate frame and
calibration remain unverified. Tests exercise a closed tetrahedron, an open
square, a nonmanifold pinched boundary, and disconnected triangle patches
through the measurement engine, standalone API, and persisted executable
Workflow Builder graphs.


## Provisional longitudinal mesh comparison (Track C)

The standalone project endpoint `POST /api/v1/projects/{project_id}/spatial/mesh-longitudinal-comparison`
accepts `before` and `after` mesh-preview requests. The typed executable
`mesh_longitudinal_comparison` Workflow Builder node accepts two persisted
`mesh_measurement_preview` artifacts, one on each named input port, and
persists a `mesh_longitudinal_comparison` artifact. Both paths delegate to
the same conservative comparison engine.

Both observations must have matching nonempty **provisional** specimen IDs,
different nonempty observation IDs, strictly increasing timezone-aware UTC
timestamps, and matching project scope. The output reports elapsed days,
surface-area difference (later minus earlier), and percent difference when
the earlier area is positive. When both observations include scale-only area
intervals, the difference interval uses the conservative endpoints
`[later_min - earlier_max, later_max - earlier_min]`. Percent-change bounds
use the corresponding extreme ratios when the earlier lower bound is positive.
Missing uncertainty stays missing, never zero.

**This is not verified coral growth or re-identification.** Matching
caller-supplied IDs are not human-reviewed identity evidence. The engine does
not infer coordinate registration, biological condition, reconstruction
completeness, correlated calibration errors, or uncertainty due to sampling.
The output retains both source geometry hashes and calibration evidence,
unverified flags, and explicit QC warnings. A researcher must independently
review identity, geometry quality, scale, and comparable survey methods before
interpreting area differences biologically. No model weights, assets, or
research data are transmitted to a cloud service.

### Calibration-only changes across timepoints

The provisional comparison now reports `before_meters_per_mesh_unit`,
`after_meters_per_mesh_unit`, and
`calibration_scale_ratio_after_to_before` from the original preview
provenance. If both observations have different calibration scales, the
comparison emits `calibration_scale_changed_between_observations`. If their
**source geometry SHA-256 fingerprints are identical** despite a scale
change, it additionally emits
`identical_geometry_rescaled_not_biological_growth`. A change in the
reported calibrated surface area can therefore arise entirely from
recalibration of an unchanged reconstruction, not biological growth.

Malformed present scales (including booleans, nonpositive values, and
nonfinite values) are rejected. Missing legacy scale metadata remains null,
with `calibration_scale_metadata_unavailable` rather than a fabricated
ratio. Fingerprint equality only detects byte-equivalent source geometry;
it does not establish coral identity or geometric registration. Scale-only
uncertainty bounds are not statistical confidence intervals, and a shared
calibration error may correlate measurements across surveys. Standalone and
persisted Workflow Builder comparisons use the same validation and warnings.

### Scale-normalized reconstruction area ratio (provisional)

The comparison additionally reports
`scale_normalized_surface_area_ratio_after_to_before`, calculated as
`(after_area / before_area) / (after_meters_per_unit / before_meters_per_unit)^2`.
The engine evaluates this in log space to avoid overflowing intermediate
squared-scale terms. An identical mesh recalibrated from 1 to 2 meters per
source unit has four times the reported physical area but a normalized ratio
of **1**, not evidence of growth. The same-scale example with twice the
reconstructed area has a normalized ratio of **2**.

This is a descriptive **reconstruction-geometry diagnostic**, not an
independently validated biological change. Ratios between different scans
are not scientifically comparable unless their source-unit conventions,
reconstruction methods, organism identities, and coordinate registration
are independently reviewed. The output therefore emits
`scale_normalized_area_ratio_requires_common_units_and_registration`
when available. Missing calibration or a zero baseline produces `null`
and `scale_normalized_area_ratio_unavailable`; unrepresentably extreme
positive ratios remain `null` with
`scale_normalized_area_ratio_out_of_numeric_range`, never an invented
zero. A genuinely zero later area can yield a descriptive ratio of zero.
No uncertainty beyond nominal scale is estimated for this diagnostic.
The standalone endpoint and persisted typed Workflow Builder node use
the same engine and have matching regression assertions.

### Scale-normalized bounding-box diagonal ratio (provisional)

The longitudinal comparison also reports
`scale_normalized_bounding_box_diagonal_ratio_after_to_before`:
`(later_diagonal / earlier_diagonal) / (later_scale / earlier_scale)`.
It uses log-space arithmetic for positive extents. For the same reconstruction
rescaled from 1 to 2 meters per source unit, the physical diagonal doubles
but the scale-normalized ratio is **1**. This is a geometric diagnostic,
not a coral branch length, growth rate, or organism reidentification result.

Missing scales or extents and a zero earlier diagonal yield `null` with
`scale_normalized_extent_ratio_unavailable`. A truly zero later diagonal
can yield zero; positive ratios that overflow or underflow the numeric
range yield `null` with `scale_normalized_extent_ratio_out_of_numeric_range`.
When available, the result carries
`scale_normalized_extent_ratio_requires_common_units_and_registration`.
No coordinate registration, common mesh-unit convention, biological identity,
reconstruction uncertainty, or calibration verification is inferred.
The metric is computed by the shared engine for the standalone endpoint
and saved typed Workflow Builder graphs. Regression tests cover rescaling,
changed geometry, absent evidence, zero baselines, numeric extremes, and
saved-workflow artifact parity.


### Source-frame provenance and registration QC (Track C)

A mesh-preview request may now include an optional `coordinate_frame_id` source
label (1–128 ASCII letters, digits, underscore, dot, colon or hyphen, starting
with an alphanumeric character). The standalone endpoint and persisted
`mesh_surface_preview` Workflow Builder node carry this label into the
observation provenance. A longitudinal comparison records both labels and
emits `coordinate_frame_metadata_unavailable` when either is absent,
`coordinate_frames_differ_registration_required` when they differ, or
`matching_coordinate_frame_id_not_registration_proof` when they match.

These are **caller-provided labels**, not coordinate transforms, registration
residuals, control-point evidence, or human approval. Matching names do not
prove spatial alignment; `coordinate_registration_verified` remains false.
Mismatches require registration review before comparing axis-aligned extents,
centroids or biological change. Malformed present labels are rejected by both
request validation and the shared longitudinal calculation engine. Existing
artifacts without labels remain readable and receive the missing-evidence QC
warning. API and saved-workflow tests assert identical comparison artifacts.

### Longitudinal reconstruction topology QC (Track C)

The shared comparison engine now retains five integer diagnostics from each
mesh preview: `face_count`, `edge_connected_patch_count`,
`boundary_edge_count`, `nonmanifold_edge_count`, and
`degenerate_face_count`. It reports
`before_reconstruction_topology_counts`,
`after_reconstruction_topology_counts`, and
`reconstruction_topology_changed_fields` in both standalone and persisted
Workflow Builder comparison artifacts.

A change in any *available* count emits
`reconstruction_topology_changed_requires_review`. Missing fields in older
saved artifacts remain null and emit
`reconstruction_topology_comparison_incomplete`; absent evidence is not
interpreted as a zero count. Malformed present counts (including booleans,
negative values, fractional numbers, and strings) are rejected rather than
silently coerced. Regression tests cover API topology drift, malformed and
legacy records, and saved-workflow output parity.

Topology changes can arise from meshing, occlusion, reconstruction parameters,
sampling, or segmentation. They **do not** establish colony fragmentation,
new branch growth, tissue loss, mortality, biological condition, or organism
re-identification. These diagnostics do not independently verify registration,
calibration, source files, or observation identity; all biological
interpretation requires human review.

### Cross-field topology integrity for persisted observations

The shared longitudinal engine rejects impossible combinations of **present**
reconstruction metadata: more edge-connected patches than faces, zero patches
with a positive face count, more degenerate faces than total faces, or more
boundary/nonmanifold edges than three times the face count. These are
combinatorial bounds for indexed triangle meshes, not biological thresholds.
Malformed observations fail rather than producing misleading longitudinal
changes; the same comparison engine is used by the standalone API and the
executable persisted Workflow Builder graph.

Older observations with missing face counts or other topology fields remain
readable. Missing metadata stays null and triggers
`reconstruction_topology_comparison_incomplete`; it is not silently replaced
with zero or marked scientifically verified. Regression cases cover impossible
counts in either observation and partial legacy artifacts. These checks do
not verify source geometry, coordinate registration, organism identity, or
biological growth.

### Extreme positive calibration-scale ratio QC

A calibration-scale ratio is meaningful only when both source scales are
strictly positive and their quotient is representable as a finite, positive
floating-point number. Very different positive scales can overflow to infinity
or underflow to zero. Neither result is a measured zero calibration ratio.
The shared longitudinal engine now withholds these unrepresentable quotients
as `null` and emits `calibration_scale_ratio_out_of_numeric_range`.
The original per-observation scales remain in the comparison artifact for
audit; normalized geometric ratios retain their separate log-space QC.

The standalone API and persisted typed Workflow Builder use the same engine.
Regression coverage exercises both overflow and positive underflow with
saved-workflow artifact parity. The new QC does not verify the calibration,
common source units, spatial registration, specimen identity, or biological
change; all observations remain provisional and subject to human review.

### Large finite longitudinal area changes (Track C)

The provisional longitudinal comparison computes relative surface-area change by
**dividing the finite area difference by the positive baseline before
multiplying by 100**. This avoids an intermediate floating-point overflow
when the percentage is representable even though `100 * area_difference`
is not. For example, a change from `1e307` to `2e307` square meters in a
synthetic legacy comparison is reported as `100%`, not withheld as null.
Regression tests cover positive and negative finite percentages. Such values
are numeric stress tests, not biologically plausible coral measurements or
validated field observations. The existing standalone API and executable,
persisted Workflow Builder share this comparison engine and retain their
artifact-parity regression. Scientific identity, calibration, registration,
and biological growth remain unverified.

### Registration residual relative to reconstructed extent (Track C)

When caller-supplied pairwise registration evidence is present and both mesh
previews report positive axis-aligned bounding-box diagonals, the longitudinal
comparison records `registration_residual_to_smaller_extent_ratio`: the
claimed RMS registration residual in meters divided by the **smaller** of the
two reconstructed diagonals in meters. This dimensionless value is a screening
diagnostic, not an estimate of registration uncertainty or accuracy. Values at
least 1 emit `registration_residual_at_least_smaller_mesh_extent` to prioritize
independent inspection. No biological or registration acceptance threshold is
implied by smaller values.

Missing or zero diagonals yield `null` and
`registration_residual_extent_ratio_unavailable`. A positive ratio outside
finite floating-point range yields `null` and
`registration_residual_extent_ratio_out_of_numeric_range`, never a false zero
or infinity. The original RMS, correspondence count, method, frame IDs and
evidence note remain in provenance. These measurements are **unverified**,
axis-aligned diagonals are orientation-dependent, and residuals can hide
registration bias or missing anatomy. The standalone endpoint and persisted
typed Workflow Builder use the same calculation, with saved-workflow parity
and direct numerical QC regression coverage.

### Registration-frame surface-centroid comparison (Track C)

When the caller supplies a validated rigid source-to-target transform and both
mesh previews have finite triangle-area-weighted surface centroids, the
longitudinal engine transforms the earlier centroid into the later observation's
coordinate frame. It reports
`registered_surface_centroid_offset_target_frame_m` (a signed XYZ offset in
target-frame meters) and `registered_surface_centroid_separation_m` (its
Euclidean magnitude). The underlying imported mesh geometry is **not** changed.

The results are explicitly provisional: surface-centroid shifts can result
from different mesh coverage, occlusion, reconstruction quality, or calibration,
even when the organism is stationary. They are **not** measured organism
movement, branch growth, or verified reidentification. The output retains
`coordinate_registration_verified: false` and
`specimen_identity_verified: false`; QC includes
`registered_centroid_offset_not_verified_biological_movement` and
`registered_centroid_position_uncertainty_not_estimated`. No displacement
confidence interval is invented from calibration-only scale bounds.

Missing centroids or a missing transform produce null results; malformed
nonfinite, Boolean, or non-XYZ centroids are rejected when used for transformed
comparison. Standalone API and saved typed Workflow Builder graphs use the
same calculation and are checked for complete artifact parity. Human review
of both specimen identity and spatial registration is required before
interpreting any difference biologically.

### Dated independent specimen reidentification review (Track C)

Optional `independent_reviewed_at_utc` records when a separately identified
reviewer assessed a provisional pairwise specimen match. The timestamp must
include a timezone and accompany a complete reviewer ID, decision, and note.
The shared longitudinal comparison rejects a review dated **before** the
later observation, including when equivalent instants are written with
different UTC offsets. Existing undated reviewer decisions remain readable
but emit `reidentification_independent_review_timestamp_unavailable`.
Review records are revalidated before execution, including after in-memory
mutation, to prevent stale or backdated audit evidence.

This is a chronology and attribution check, **not** cryptographic
authentication, proof that the reviewer examined the images, or verified
organism identity. A supporting review still leaves
`specimen_identity_verified: false`. Both standalone analysis and executable
persisted Workflow Builder graphs use the same comparison engine; regression
coverage checks dated review provenance, invalid chronology, legacy QC,
and saved-workflow artifact parity.

### Project-scoped provisional reidentification evidence (Track C)

Optional `project_id` in `MeshReidentificationEvidence` binds a provisional
specimen match to the project containing both reconstructed observations.
Even matching observation labels, specimen IDs, source geometry fingerprints,
and timestamps cannot justify importing a match from another project.
The shared longitudinal engine rejects mismatched project bindings.
Older records without `project_id` remain readable but emit
`reidentification_project_binding_unavailable` for scientific review.

This is a caller-supplied project-scope check, not cryptographic evidence of
identity, a verified specimen match, or a substitute for independent review.
The standalone endpoint and persisted typed Workflow Builder graphs share
the same validation and provisional provenance; regression coverage checks
cross-project rejection, legacy QC, mutated evidence, and saved artifact parity.


### Machine-readable registration-review withholding provenance (Track C)

Longitudinal mesh artifacts now retain two explicit Boolean provenance flags:
`registered_centroid_comparison_withheld_due_to_registration_dispute` and
`registered_centroid_comparison_withheld_due_to_inconclusive_registration_review`.
They distinguish an independent review that **disputes** alignment from one
that cannot determine alignment. A supporting review, an absent review, and
missing registration evidence leave both flags `false`; none of these states
constitutes verified registration. A disputed or inconclusive decision sets
its corresponding flag to `true` and withholds transformed-centroid offsets,
separations, associated caller-bound intervals, and RMS ratios as `null`.
The original mesh measurements, transform diagnostics, reviewer attribution,
and QC warnings remain available for audit.

These flags describe why a derived diagnostic was withheld, **not** whether
coral movement was absent or the registration was scientifically validated.
Standalone analysis and saved executable typed Workflow Builder graphs share
the same comparison engine; regression assertions verify the flags and full
persisted-artifact parity for supported, disputed, and inconclusive reviews.

### Calibration-scale-bound registration evidence (Track C)

A geometry SHA-256 fingerprint identifies reconstruction geometry, not the
physical scale applied to it. An imported mesh can be recalibrated without
changing its vertex/face fingerprint. Optional paired
`source_meters_per_mesh_unit` and `target_meters_per_mesh_unit` values now
bind a caller-supplied registration to the exact scale of each observation.
Providing only one scale is invalid. A mismatch rejects the comparison rather
than silently applying a meter-valued transform to recalibrated geometry.

Legacy evidence without either scale remains readable, but emits
`registration_calibration_scale_binding_unavailable` as scientific QC. These
scale bindings are **caller-supplied consistency checks**, not verified
calibration, accurate alignment, or proof of biological growth. Standalone
comparison and executable persisted Workflow Builder graphs use the same
validation and preserve evidence in provenance; tests cover a successful
scale-bound saved workflow, stale-scale rejection with identical geometry,
incomplete bindings, and flagged legacy evidence.


### Calibration-provenance-bound registration evidence (Track C)

A calibration can be reinterpreted without changing the imported triangles,
meters-per-unit value, or numerical uncertainty. The registration evidence
schema therefore accepts an optional **complete quartet**:
`source_calibration_method`, `target_calibration_method`,
`source_calibration_evidence`, and `target_calibration_evidence`.
All four must be supplied together and must exactly match the corresponding
mesh preview provenance. A revised method or supporting evidence string rejects
reuse of a stale registration, even when both geometry fingerprints and scales
remain unchanged. These strings are audit bindings, not evidence that the
calibration itself is accurate.

Legacy registrations without this quartet remain readable with the explicit
`registration_calibration_provenance_binding_unavailable` QC warning. Partial
or malformed quartets are rejected. The standalone longitudinal API and saved,
typed Workflow Builder graph use the same comparison engine, and a saved-workflow
regression exercises a fully bound registration. No calibration, spatial
alignment, organism identity, or biological growth is marked verified.

### Nonblank scientific audit evidence (Track C)

Mesh previews now reject calibration evidence containing only whitespace.
Pairwise registration and provisional reidentification records likewise reject
whitespace-only evidence notes, independent-review notes, and paired calibration
references. This validation applies to standalone analysis and the same typed
schemas used by persisted Workflow Builder execution; existing saved-workflow
artifact-parity regressions continue to cover valid attributed evidence.
Nonblank text is an auditability requirement, **not** proof that the supporting
material exists, was independently reviewed, or establishes biological change.

### Point-cloud calibration audit parity (Track C)

The point-cloud request contract now rejects calibration evidence made entirely
of whitespace, matching the mesh request and the underlying point-cloud
measurement engine. This applies to standalone project preview endpoints and
saved executable `point_cloud_preview` Workflow Builder graphs. A regression
covers request validation, direct scientific-service rejection, and a persisted
graph that must fail without emitting a scientific measurement artifact when its
calibration evidence is blank. Existing valid saved-graph artifact parity tests
remain in place. Nonblank evidence remains caller-supplied and **unverified**;
this does not certify scale, geometry, specimen identity, or branch length.

### Strict numeric provenance for point-cloud calibration and geometry (Track C)

The point-cloud request schema and direct scientific measurement service now reject
Boolean and numeric-string values for `meters_per_unit`,
`relative_scale_uncertainty`, and XYZ point coordinates. Pydantic's ordinary
float coercion would otherwise interpret `true` as `1.0`, potentially turning
an accidental Boolean calibration or point coordinate into a plausible-looking
physical measurement. Explicit JSON integers and floating-point numbers remain
accepted; all existing finite-value and coordinate-range bounds still apply.
ASCII PLY numeric tokens remain parsed as the PLY text format requires.

A rejected request produces no scientific measurement. Regression coverage checks
the direct service, standalone project API, and execution of persisted typed
Workflow Builder graphs: invalid saved graph parameters fail without generating
a `point_cloud_measurement_preview` artifact. Valid point clouds remain
provisional: this input-integrity check does not verify ruler measurements,
specimen identity, coordinate registration, surface area, or biological branch
length, and no local model checkpoints are transmitted or modified.

## Strict scientific numeric inputs (October 27, 2026)

Mesh measurement inputs supplied as indexed triangles now reject Boolean values and numeric strings for XYZ vertex coordinates, meters-per-unit calibration, and relative scale uncertainty. Integer and floating-point JSON numbers remain accepted (including integer zero for a declared zero relative scale uncertainty). Both the standalone mesh-preview API and the persisted executable `mesh_surface_preview` Workflow Builder node use the same strict request schema, and the underlying measurement service independently rejects coerced values. Invalid saved graphs fail without emitting a mesh measurement artifact. This prevents a Boolean such as `true` from silently becoming a 1-meter scale or vertex coordinate, or a text field from becoming a numeric scientific observation. Existing OBJ/PLY/GLB import parsing remains separate and continues to validate its own geometry format. This input-integrity safeguard does not independently verify calibration, source geometry, organism identity, or anatomical branch length.

## Duplicate geometric triangle rejection (Track C)

The mesh measurement service now rejects **exactly coincident triangles even when
the importer assigns them different vertex indices or reverses winding**.
Index-only duplicate checks were insufficient: duplicate OBJ/PLY/GLB vertices
could otherwise cause the same reconstructed surface to be counted twice.
Each face is compared using its three sorted, uncalibrated XYZ coordinates,
without a tolerance, spatial welding, or mutation of the source geometry.
The existing duplicate-index check remains in place.

The standalone mesh-preview API and persisted executable `mesh_surface_preview`
Workflow Builder node share this fail-closed calculation. Rejected geometry
must not produce a mesh measurement artifact. Distinct triangles that happen
to share vertices or coordinate positions remain eligible, with their
independent topology QC retained. The rule does **not** detect partially
overlapping triangles, reconstruction folds, or near-duplicate coordinates;
those require separate reconstruction review. This is an area-integrity
safeguard, not proof of coral tissue completeness, organism identity,
calibration validity, or anatomical branch length.

## Imported 3D source-byte provenance (Track C)

The bounded OBJ, ASCII PLY, and GLB 2.0 mesh preview now records
`provenance.source_payload_sha256` and `source_payload_size_bytes`.
OBJ/PLY fingerprints use the exact caller-supplied UTF-8 text bytes; GLB
fingerprints use the **decoded binary file**, not its base64 transport string.
These byte-exact values complement `geometry_sha256`, which identifies the
parsed indexed triangles. Two differently formatted source files can yield
identical measured geometry but different source-byte fingerprints; whitespace
changes to a valid OBJ likewise change the source fingerprint without changing
its geometric measurements. For directly supplied indexed triangles, both
source-file fields are explicitly `null` rather than inventing a file.

The standalone mesh endpoint and persisted executable Workflow Builder node
produce identical source fingerprints and provisional measurement provenance.
The `test_spatial_mesh_source_fingerprint_v14.py` regression covers all
three import formats, saved-graph execution, and indexed-triangle fallback.
This is a reproducibility prerequisite for future project-scoped content-addressed
asset imports, **not** persistent file storage, verified calibration, verified
source acquisition, or an anatomical coral measurement.

## Geometric patch-area concentration (1.4 development)

The full-resolution mesh preview reports
`edge_connected_patch_area_concentration_index` as the sum of squared
surface-area fractions for all edge-connected patches, and
`area_weighted_effective_patch_count` as its reciprocal. For two
equal-area patches these values are 0.5 and 2, respectively; for one
positive-area patch both are 1. A mesh whose total triangle area is zero
reports null for both rather than inventing an effective patch count.
Values are dimensionless and invariant to a shared calibration scale.

These statistics characterize how reconstructed **geometric surface area**
is concentrated across disconnected patches. They are **not** organism
counts, diversity estimates, completeness scores, or evidence of coral
reidentification. Patches can represent fragments, reconstruction errors,
or multiple parts of one colony. Human review and calibration/registration
provenance remain required before biological interpretation.

The standalone mesh-preview API and the executable, saved
`mesh_surface_preview` Workflow Builder node use the same measurement
engine; the corresponding regression test checks exact saved-artifact
parity, zero-area handling, scale invariance, and deterministic ties.

## Longitudinal patch-area distribution QC (October 28, 2026)

The provisional `mesh_longitudinal_comparison` analysis now recomputes
scale-invariant patch-area concentration and effective geometric patch count
from the **complete-mesh** per-patch surface-area fractions at each observation.
It reports both timepoint descriptors and after-minus-before changes. Because
patch order and individual patch identity are not assumed to persist between
surveys, it compares only permutation-invariant aggregate descriptors, never
patch-to-patch correspondence. Changing the caller's meters-per-unit scale
cannot by itself change these dimensionless statistics.

The analysis validates that source fractions are finite, between zero and one,
sum to one, and match the recorded topology patch count when available. If
stored concentration or effective-count values are supplied, they must agree
with values recomputed from the fractions; contradictory metadata fails closed.
Older artifacts without these fields and zero-area surfaces produce null
comparison values with an explicit availability warning, not fabricated zeros.
A disputed or inconclusive independently recorded specimen match withholds
cross-timepoint differences while retaining each original observation's
reconstruction descriptors and QC. Supporting review never certifies identity.

These differences describe **reconstruction geometry**, not biological
fragmentation, growth, coral condition, or independent colony counts. They
cannot correct differences in mesh completeness, segmentation, or source
registration. The standalone project comparison endpoint and the executable,
typed, persisted Workflow Builder graph share the same comparison engine;
`test_spatial_mesh_longitudinal_patch_concentration_v14.py` covers numeric
examples, malformed source metadata, legacy fallback, disputed identity,
and saved-workflow artifact parity.

### Ranked patch-area profile distance across timepoints (Track C)

The provisional longitudinal mesh comparison now includes
`ranked_patch_area_profile_distance`, a dimensionless reconstruction-QC
descriptor computed from the **complete-mesh** surface-area fractions of
edge-connected patches. Each observation's fractions are independently sorted
largest to smallest; missing ranks in the shorter list are padded with zero.
The reported value is half the sum of absolute differences between ranks,
bounded by 0 and 1. A value of 0 means identical *ranked area distributions*,
not identical mesh geometry or specimen identity. For a change from patch
fractions [0.75, 0.25] to [0.5, 0.5], the value is **0.25**. It is unchanged
by patch index reordering or common calibration-scale changes.

The calculation deliberately **does not match individual patches** across
surveys. Changes can arise from occlusion, reconstruction quality, tessellation,
mesh cleanup, or scan coverage rather than coral fragmentation or growth.
The artifact carries `ranked_patch_area_profile_distance_not_patch_correspondence`
as a QC warning and retains provisional human-review requirements. If either
observation lacks a valid distribution, the distance is null; contradictory
stored concentration or fraction metadata is rejected. A disputed or
inconclusive independent specimen-identity review also withholds the distance
while preserving each observation's original measurements. The standalone
longitudinal API and executable, persisted typed Workflow Builder graph use
the same engine; regression tests cover known fractions, patch-order
invariance, different patch counts, missing legacy evidence, disputed identity,
and complete saved-workflow artifact parity. No cloud processing or model
checkpoint changes are involved.

### Ranked patch-area Jensen-Shannon divergence and numeric resolution (Track C)

The provisional longitudinal comparison also reports
`ranked_patch_area_jensen_shannon_divergence_bits`, the base-2
Jensen-Shannon divergence between sorted patch-area fractions, with
missing patch ranks padded by zero. Its mathematical range is [0, 1].
It is invariant to patch enumeration and a common scale factor but
does **not** establish anatomical patch correspondence, growth, tissue
loss, or biological reidentification. Both standalone comparisons and
saved executable `mesh_longitudinal_comparison` Workflow Builder
graphs use the same calculation.

The implementation uses `2*p/(p+q)` rather than dividing by a
potentially underflowed midpoint. If distinct ranked profiles differ
below floating-point resolution, either the profile distance or the
Jensen-Shannon divergence is reported as **null**, with an explicit
`*_below_numeric_resolution` QC warning, rather than a false exact
zero. Missing legacy distributions also remain null. Tests cover
positive subnormal fractions, ordinary small positive differences,
identical distributions, and persisted-workflow artifact parity.

### Full-mesh patch-area consistency guard (Track C)

Longitudinal patch-area comparisons now cross-check stored area fractions
against the actual per-patch `edge_connected_patch_surface_areas_m2` values
whenever that breakdown is present. The number of patch areas must match
the number of fractions; every area must be finite and nonnegative, the
areas must sum to the full-mesh `surface_area_m2`, and each fraction must
agree with its corresponding area divided by that total. Contradictions
fail closed before ranked-profile or concentration differences are reported.
This prevents edited summary fractions from silently contradicting the
source reconstruction's complete-mesh area breakdown.

Older artifacts that genuinely lack the optional per-patch area breakdown
remain readable under the previous fraction and topology checks; the
absence of an area breakdown does **not** establish verified geometry.
The guard does not independently authenticate imported mesh bytes, validate
calibration or registration, or prove that two timepoints show the same coral.
Regression tests exercise both timepoints, altered distributions that retain
the same total, invalid numeric area records, mismatched totals, legacy
compatibility, and existing saved Workflow Builder/standalone parity.


## Independent calibration review evidence (Track C)

The standalone mesh preview and executable, saved `mesh_surface_preview`
Workflow Builder node now accept optional `calibration_review` evidence.
The researcher first generates an unreviewed preview to obtain its
`provenance.geometry_sha256`, then records a separately attributed review.
The record requires a calibration operator, a **different** independent
reviewer, a decision (`supports_scale`, `disputes_scale`, or `inconclusive`),
a nonblank note, an aware review timestamp, and explicit bindings to the
source geometry SHA-256, specimen and observation identifiers and timestamp,
meters-per-unit scale, calibration method, calibration
evidence, and relative scale uncertainty (including a distinct unknown/null
value). A review predating the source observation is rejected.

Reusing the review after any bound input changes fails closed instead of
silently transferring an old scientific assessment to new geometry or a new
calibration. The record is preserved under
`provenance.calibration_review_evidence` in standalone and persisted workflow
artifacts. Disputed and inconclusive reviews add explicit QC warnings.
Legacy previews without review remain readable.

**Review evidence is caller-supplied and not authenticated.** Even a
`supports_scale` decision does not establish physical calibration,
photogrammetric reconstruction accuracy, instrument traceability, biological
identity, or a statistical confidence interval. `calibration_verified`
remains `false` and `measurement_status` remains
`caller_supplied_unverified`. The scale-only intervals do not incorporate
review uncertainty or reconstruction error. This slice does not introduce
persistent 3D source-asset storage, a reviewer identity service, or a
certification workflow. Backend regression tests cover independent attribution,
source binding, stale evidence, decision warnings, and saved-workflow parity.

### Ordered cumulative mesh-route arclength (Track C)

For each connected, caller-selected mesh-edge shortest path, the provisional
`surface_edge_paths` artifact now includes `path_cumulative_lengths_m`.
The array starts at zero and contains one cumulative calibrated distance for
every ordered route vertex, including vertices omitted from the bounded
interactive render sample. The corresponding
`path_cumulative_length_scale_intervals_m` provides per-vertex **scale-only**
lower and upper bounds when a relative calibration uncertainty is supplied.
These are *not* independent confidence intervals; all values share the same
caller-supplied calibration and its systematic uncertainty. Disconnected or
unreferenced paths report null arrays, not fabricated zero-distance routes.
The terminal cumulative distance agrees with the reported route length within
floating-point precision. Standalone preview and persisted executable
`mesh_surface_preview` Workflow Builder artifacts use the same engine; tests
cover two-edge routes, uncertainty bounds, missing routes, and saved-graph
parity. This is a geometric mesh-edge path, **not** an anatomical coral
centerline, tissue-length measurement, verified branch length, or evidence of
growth. Geometry, calibration, registration, and biological identity remain
unverified.

### Zero-area reconstruction QC and longitudinal comparisons (Track C)

A zero-area mesh (including a degenerate reconstruction with triangles but
zero geometric surface area) has **no defined patch-area distribution**.
Its patch concentration, effective patch count, ranked profile distance, and
Jensen–Shannon divergence are reported as unavailable, not as measured zero
change. Modern previews with missing fractions are accepted only when the
per-patch area list is finite, exactly zero for every patch, consistent with
the reported patch count, and the total surface area is zero. Positive or
malformed per-patch areas, missing fractions alongside non-null concentration
statistics, and inconsistent topology remain rejected. Older records that
lack the optional patch-area breakdown remain readable without fabricating
a distribution. This is reconstruction-quality evidence, not biological
tissue loss, fragmentation, or verified coral growth.

Standalone longitudinal comparisons and persisted executable Workflow
Builder graphs share this validation path. Regression coverage includes
degenerate zero-area previews, forged area evidence, and the pre-existing
zero-face and extreme-calibration saved-workflow cases. Physical calibration,
registration, and specimen identity remain unverified.

### Legacy scale-interval provenance guard (October 29, 2026)

Longitudinal 3D comparisons now reject a stored surface-area or
axis-aligned bounding-box diagonal **scale interval** if the associated
observation lacks `provenance.relative_scale_uncertainty` entirely.
An interval that encloses its nominal measurement is not sufficient:
without the source calibration uncertainty, a legacy record could
otherwise present arbitrarily narrow bounds as scientific evidence.
The existing checks also reject supplied intervals when source
uncertainty is explicitly unknown or their endpoints contradict it.

Older observations **without a claimed interval** remain readable, with
combined longitudinal scale bounds withheld rather than invented.
Both the standalone comparison and executable typed Workflow Builder
adapter use this fail-closed validation. Regression tests exercise
both timepoints and both interval types. These are scale-only bounds,
not statistical confidence intervals or verified coral growth; physical
calibration, registration and biological identity remain provisional.

### Dimensionless mesh shape diagnostic (October 30, 2026)

Standalone OBJ/PLY/GLB mesh previews and executable, persisted Workflow Builder
`mesh_surface_preview` nodes now emit
`surface_area_to_bounding_diagonal_squared_ratio`. The value is the **full
mesh** triangle surface area in source units divided by the square of the
axis-aligned bounding-box diagonal in the same source units. For the example
2-by-3-unit right triangle, the ratio is `3 / 13`. It is independent of a
common positive isotropic meters-per-unit scale; source-unit calculation also
avoids numerical underflow from squaring very small calibrated dimensions.
A zero diagonal produces `null`, not a fabricated finite ratio. The field
does not acquire a separate scale-only uncertainty interval because the
common scale factor cancels algebraically.

This is a **provisional reconstruction shape descriptor**, not a coral health,
biomass, branch length, growth, or species classification. It changes with
source-axis rotation, reconstruction completeness, mesh tessellation, and
the spacing of disconnected patches. No orientation registration, independent
scale validation, biological reidentification, or reconstruction-error
uncertainty is implied. Persisted-workflow and standalone regressions check
the same value, calibration-scale invariance, and the zero-diagonal case.
