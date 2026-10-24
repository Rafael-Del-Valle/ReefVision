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
