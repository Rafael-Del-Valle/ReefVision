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
