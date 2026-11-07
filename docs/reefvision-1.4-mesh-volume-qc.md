# ReefVision 1.4 — provisional mesh-volume QC

The `mesh_surface_preview` standalone endpoint and executable, persisted
Workflow Builder node share the same 3D measurement engine. A triangular
surface patch receives an **unverified enclosed volume** only when its indexed
edges form a closed, consistently wound, nondegenerate surface. Results remain
provisional: self-intersections, reconstruction completeness, anatomical
identity, and the caller-supplied scale are not independently verified.

## Edge-connected components and touching geometry

A mesh can contain multiple edge-connected surface patches. The engine
preserves each eligible patch's provisional volume and calibration interval,
but withholds the **aggregate** enclosed volume when the union is not a
regular disjoint collection of surfaces.

Two independently diagnosed touching cases are:

- `vertex_touching_patch_vertex_count`: separate edge-connected patches
  reference the **same source vertex index**.
- `coincident_patch_coordinate_count`: separate edge-connected patches
  include **distinct source vertex indices with exactly equal 3D coordinates**.
  Some OBJ/PLY/GLB exports duplicate vertex indices at seams, so checking only
  shared indices could incorrectly accept an aggregate volume.

The second check compares exact coordinates in the imported source frame.
It deliberately does not apply an arbitrary distance tolerance, weld vertices,
or claim registration between scans. Near-coincident vertices, intersecting
triangles without identical vertices, and self-intersections are **not**
resolved by these checks.

For either touching condition, `enclosed_volume_m3` and
`enclosed_volume_scale_interval_m3` are null. Per-patch provisional volumes
remain available for human review. Relevant QC flags are
`vertex_touching_mesh_patches`, `enclosed_volume_vertex_touching_patches`,
`coincident_mesh_patch_coordinates`, and
`enclosed_volume_coincident_patch_coordinates`.

## Provisional surface-to-volume descriptor

For a closed, consistently oriented mesh with accepted provisional enclosed
volume, `surface_to_enclosed_volume_ratio_per_m` reports the geometric ratio
`A/V` (units: inverse meters). Individual eligible edge-connected patches
also report ratios, even when a touching or invalid patch causes the global
volume and global ratio to be withheld. Open, zero-volume, numerically invalid,
or rejected surfaces report `null` rather than fabricating a ratio.

The optional scale-only interval is
`[R/(1+u), R/(1-u)]` for relative scale uncertainty `0 <= u < 1`.
Missing uncertainty produces `null` rather than zero uncertainty. At
`u = 1`, no finite upper bound exists, so the interval is `null` while
the nominal provisional ratio is retained. Per-patch intervals use the same
rule. These are deterministic scale bounds, **not confidence intervals**.
They omit mesh reconstruction, segmentation, self-intersection, and
biological validation errors.

Surface-to-volume ratio is a geometry descriptor, not a validated coral
biomass, health, porosity, or surface-to-tissue-volume measurement. It is
available through the same standalone endpoint and persisted executable
`mesh_surface_preview` Workflow Builder node. Scientific regression tests
cover closed and open surfaces, missing/zero/100% scale uncertainty, and
standalone-versus-saved-workflow consistency.

## Scientific interpretation and reproducibility

Scale-only volume intervals are computed as
`[V(1-u)^3, V(1+u)^3]`, where `u` is the supplied relative scale
uncertainty. They are **not** confidence intervals and exclude reconstruction,
calibration verification, biological segmentation, and spatial-registration
errors. The preview's `measurement_status` remains
`caller_supplied_unverified` and
`provenance.calibration_verified` remains `false`.

Regression coverage in
`test_spatial_mesh_vertex_touching_volume_v14.py` exercises shared-index
touching, distinct-index coincident-coordinate touching, and genuinely
disjoint tetrahedra through the direct engine, standalone API, and a saved,
executed Workflow Builder graph. No persistent mesh-asset registry, verified
biological branch-length inference, or longitudinal organism matching is
implied by this slice.

## Caller-supplied specimen and observation provenance

The standalone mesh preview and persisted `mesh_surface_preview` Workflow
Builder node accept optional `specimen_id`, `observation_id`, and
`observed_at_utc` fields. The timestamp must include a timezone offset and
is normalized to UTC in the measurement provenance. Identifiers are bounded
and must not contain whitespace. A saved workflow retains these values in
its result artifact, alongside the geometry fingerprint and scale evidence.

These are **unverified caller assertions**, not an organism identity registry,
survey linkage, independently checked observation time, or a longitudinal
comparison. The provenance explicitly sets `specimen_identity_verified`
and `observation_metadata_verified` to `false`. Repeated specimen IDs must
not be interpreted as confirmed re-identification, and temporal differences
must not be presented as growth without reviewed registration, calibration,
and identity evidence.

## Disconnected-patch surface-area distribution

The full-resolution mesh preview now reports
`edge_connected_patch_surface_area_fractions` (in source-face patch order),
`largest_surface_patch_index`, and `largest_surface_patch_area_fraction`.
Each share is a patch's uncalibrated triangle-area sum divided by the entire
mesh's triangle-area sum. A common positive scale cancels, so the shares do
not change with calibration scale or its scale-only uncertainty. Tied patches
select the earliest source-face patch deterministically. For an entirely
zero-area reconstruction, fractions and largest-patch fields are `null`:
there is no meaningful dominant surface. Display sampling is never used
to calculate these fields.

These metrics help flag detached reconstructed surfaces for human inspection.
They do **not** identify coral colonies, prove tissue completeness, establish
independent biological replicates, or estimate uncertainty from reconstruction
or segmentation. The standalone endpoint and persisted, typed executable
Workflow Builder node return the same provisional values; regression coverage
includes scale invariance, zero-area and tied patches, and saved-workflow parity.
