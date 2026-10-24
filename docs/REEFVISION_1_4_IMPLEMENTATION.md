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
