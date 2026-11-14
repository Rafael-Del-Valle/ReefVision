# Verified mask area and coverage design

Status: implementation design for ReefVision 1.1 Priority A. This design extends the existing immutable computed-metric tables; it does not rewrite migration 0041.

## Scientific contract

`mask_coverage` definitions operate only on explicitly selected, reviewed project images and canonical masks whose status is `verified`. Model proposals, deleted masks, and draft masks are excluded. A definition may restrict target masks to explicit annotation classes and may name one additional label class whose verified masks define a region-of-interest (ROI) union. ROI masks are denominator evidence and are never counted as target objects.

All geometry is converted to exact source-image row runs using the existing documented Pillow fill convention. Raster masks must be complete source-sized PNGs. Polygon and raster failures are fatal; a corrupt or missing verified mask is never silently skipped.

For each image and for the selected set, ReefVision reports:

- target object count;
- summed target-mask pixel area, which can double-count overlap;
- geometric target-union pixel area, which never double-counts overlap;
- overlap pixel area (`summed - union`);
- full-image denominator pixels and union coverage percent;
- optional ROI-union denominator pixels, target-union pixels inside the ROI, and ROI coverage percent;
- summed and union pixel area by target class;
- immutable mask, image, ROI, calibration, algorithm, and source-content evidence.

Group summaries use either one independent unit per image or one unit per nonblank researcher-authored image `group_key`. Group coverage is computed from pooled numerator and denominator pixels, not by averaging percentages.

## Physical area and density

Per-image physical values are available only when the image has a valid scalar `distance_per_pixel` calibration with a supported length unit and no perspective homography. Unknown/non-length units are unavailable rather than being squared into a fabricated physical quantity. Exact union resampling through a projective homography is outside this algorithm, so those images expose pixel results while physical values remain unavailable with an explicit reason.

Physical target union area is `union_pixels * distance_per_pixel^2`. Object density uses an explicit sampling-area denominator: the physical ROI union when an ROI is configured, otherwise the calibrated full-image area. Its persisted numerator is the count of target masks intersecting that same ROI, or all target masks for full-image sampling. It is never divided by target-mask area or populated from masks outside the sampling region.

An aggregate/group physical value is available only if every contributing image has a compatible calibration. Same-unit inputs retain that unit; compatible mixed length units are normalized to metres (and square metres for area) before summation. Missing, unknown-unit, invalid, or projective calibrations leave aggregate physical values unavailable while preserving per-image results and reasons.

## Empty and missing evidence

A reviewed image with no target verified masks is a scientifically meaningful zero and may be persisted. If an ROI class is configured, every selected image must contain a nonempty verified ROI union; otherwise preview/calculation fails because the denominator is missing. Zero image dimensions and out-of-frame/corrupt geometry fail closed.

## Immutability and currentness

Definitions and results use the existing computed-metric rows with new discriminator `mask_coverage`. Result content, definition, evidence, raster content, polygon coordinates, image dimensions/checksum/review state/group key, mask revision/status/class/source, class-label snapshots, calibration snapshot, and algorithm version are hashed. Validation detects added, removed, changed, relabeled, reclassified, regrouped, recalibrated, resized, or content-modified evidence.

## Integration

The same service powers standalone preview/calculation, CSV evidence export, Workflow Builder execution, project exchange, and the React researcher workspace. Workflow replay is idempotent for the same node/input inventory and rejects conflicting replay. Exchange remaps project-scoped IDs, preserves literal group keys, rebuilds canonical hashes, and rejects corruption atomically.

## Deliberate limits

- ROI v1 is the union of verified masks from one explicit label class; arbitrary freehand ROI records are not invented.
- Projective/homography-corrected union area is unavailable until exact source-pixel resampling is implemented and validated.
- No uncertainty intervals, inferential statistics, or inferred subject/treatment hierarchy are introduced.
- Synthetic exact-value fixtures establish algorithmic correctness, not field-data, installed-desktop, or physical-hardware acceptance.
