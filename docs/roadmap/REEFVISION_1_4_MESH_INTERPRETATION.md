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
