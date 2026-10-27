# ReefVision 1.4 — provisional XYZ point-cloud preview

The standalone `POST /api/v1/projects/{project_id}/spatial/point-cloud-preview` endpoint and executable persisted `point_cloud_preview` Workflow Builder node share one bounded measurement engine.

Inputs are **either** up to 2,000 XYZ points **or** a vertex-only ASCII PLY 1.0 file with three floating-point XYZ properties and optional complete `uchar`/`uint8` red, green, blue properties in any column order. RGB values are validated as integers in [0, 255]; raw RGB for sampled display points is returned separately from geometry: measurements and geometry fingerprints use XYZ only, not color. For PLY inputs, `provenance.source_text_sha256` separately fingerprints the exact UTF-8 text received (including RGB and header); this is not a digest of the original disk file, an organism identifier, or evidence of human verification. Direct XYZ inputs report `null` for this source-text digest. Partial RGB, binary PLY, polygon meshes, normals, and other attributes remain unsupported. The original PLY is passed as text; **no persistent 3D asset is created**.

Outputs include point count, duplicate-point QC, calibrated global-axis extents and diagonal, arithmetic centroid in the source coordinate frame, and scale-only uncertainties when supplied. Optional `point_index_pairs` (up to 32 pairs of distinct zero-based indices) returns calibrated straight-line chord distances and scale-only uncertainty for selected original input points. Pair indices are strictly integers and must be within bounds. Each chord also records its two calibrated endpoint coordinates in the original source frame and an ordered, scale-independent SHA-256 fingerprint of the selected raw endpoint geometry. This provides a reviewable guard against silently reassigning point-index measurements when source point ordering changes; it is not a persistent landmark or organism identity. Each chord includes `chord_distance_scale_interval_m` (lower/upper bounds) when scale uncertainty is provided; it is `null` when unknown. These are scale-only intervals, not statistical confidence intervals or biological branch lengths. These chords are not surface geodesics or biological branch lengths. An additional ordered-geometry SHA-256 fingerprint records the exact point order used for index selection; the existing order-independent geometry fingerprint is retained. The axis-aligned bounding-box **envelope** volume (m³) is the product of the three extents, **not** coral tissue volume or reconstructed occupied volume. Its scale-uncertainty interval applies the lower and upper scale factors cubically. Coplanar or collinear points have zero envelope volume, regardless of actual organism thickness. Surface area and branch length are **null**, not estimated from a point cloud. Scale evidence and exact geometry fingerprint are recorded, but calibration and coordinate registration are **not verified**. Dimensions are not anatomical branch measurements, and geometry fingerprints are not organism identities.

A regression test replays a persisted `point_cloud_preview` graph twice and requires identical artifact payloads and SHA-256 content digests, including unverified calibration and source-text provenance. This checks deterministic workflow reproducibility, not the accuracy of the source measurements.

The optional `coordinate_frame_id` is a bounded caller-provided label for the source reconstruction coordinate system. It is preserved in `provenance.coordinate_frame_id` for both standalone API and executable saved Workflow Builder artifacts. Matching frame labels do **not** prove that separate observations are spatially registered or share a surveyed origin; `coordinate_registration_verified` remains `false`. Invalid, empty, or overlong frame labels are rejected by the request contract. The saved-workflow parity regression checks this label alongside other provenance fields.

Both standalone API and saved-workflow artifacts remain `caller_supplied_unverified`. Do not promote to a verified scientific observation without human review and registration/calibration QC. Future work includes persistent 3D assets, large/binary clouds, registration and longitudinal comparisons.

For visualization preparation, the result includes a deterministic sample of up to 512 source-indexed points with calibrated coordinates. For clouds exceeding 512 points, first and last indices remain included; selected measurement endpoints need not appear in the display sample. The full input, not the decimated sample, determines extents, centroid, fingerprints and point-pair measurements. This is display geometry only: it does not establish a validated organism surface or anatomical landmark, and the persisted Workflow Builder artifact now has a read-only interactive SVG viewer with yaw, pitch, zoom, reset, and optional sampled RGB. The standalone and saved-workflow previews must agree on sampled indices and coordinates.

The preview also returns calibrated minimum and maximum XYZ coordinates in the **original source frame**. These axis-aligned bounds preserve negative coordinates and support future interactive camera framing; they are not registered geographic positions. Standalone API results and persisted Workflow Builder artifacts must agree on these bounds.

The arithmetic point-sample centroid also includes `arithmetic_centroid_in_source_frame_scale_interval_m` when relative scale uncertainty is supplied, with lower and upper limits sorted correctly for negative source coordinates. It is `null` when uncertainty is unknown. This interval propagates **scale uncertainty only**; it does not account for reconstruction error, point-sampling density, or unverified coordinate registration. A sample centroid is not a validated organism center of mass. The standalone and saved-workflow results must match.

Selected point-index chords now carry per-chord `qc_warnings`. When two **distinct indices** resolve to the **same XYZ coordinate**, the preview retains the zero-distance chord and marks `coincident_endpoint_coordinates`; a distinct-index pair is not proof of a nonzero biological segment. The warning and measured zero remain in the saved Workflow Builder artifact, without promoting any measurement to verified status. The global `duplicate_points_present` warning remains independent of these pair-specific warnings.

Preview RGB roadmap acceptance: retain validated raw PLY RGB only as aligned, bounded display metadata; do not use color for geometry hashes, biological condition, calibration, or automatic verification. Require standalone API versus saved typed Workflow Builder graph parity, deterministic decimation, and independent source-text provenance before enabling the viewer. Sampled RGB and read-only interactive rendering are implemented for saved Workflow Builder artifacts; scientifically calibrated biological color remains pending.

`preview_point_colors_rgb_uint8` is `null` for XYZ-only and colorless PLY inputs, or a list aligned with `preview_point_indices` for complete RGB PLY. Color is raw display metadata, never a geometric fingerprint, biological condition measurement, or calibration verification. Standalone and persisted Workflow Builder outputs must match; the 513-point decimation regression checks color alignment at the display threshold.

PLY RGB parsing is atomic for caller-provided color buffers: a malformed later vertex causes the import to fail without exposing partial RGB records. A valid colorless PLY leaves a preexisting color buffer unchanged. This behavior protects import integrity; RGB remains uncalibrated display metadata, never evidence of organism condition or human verification.

## Persisted artifact viewer integrity (October 2026)

The saved-workflow point-cloud viewer draws only bounded, validated, source-indexed display points. It deliberately fails closed when the artifact omits explicit unverified calibration provenance, claims verified calibration or coordinate registration, reports a non-provisional measurement status, or supplies non-null surface area or branch length. Such contradictions display an invalid-artifact message rather than a scientifically misleading 3D rendering. Frontend regression tests cover these cases. The viewer never writes or changes the persisted artifact, and its rotation/zoom do not affect full-input scientific measurements.

A saved point-cloud viewer is **not** a standalone PLY file-picker, persistent geometry asset, organism identity, validated coral tissue measurement, or evidence that calibration has been reviewed. The standalone point-cloud API and executable typed persisted Workflow Builder node remain the two measurement paths; their scientific parity is covered by backend regression tests.

## Standalone local-file preview (October 23, 2026)

The Workflow Builder workspace now exposes a separate local ASCII PLY point-cloud file picker alongside the existing OBJ/PLY/GLB mesh picker. It calls the same `point-cloud-preview` endpoint used by the executable, typed and persisted `point_cloud_preview` workflow node. The file is read locally, decoded as strict UTF-8, checked for ASCII-only content and the 256,000-byte limit, and sent only to the local project's preview endpoint. The server remains authoritative for vertex-only PLY 1.0 validation, up to 2,000 points, optional complete RGB, and measurement provenance.

The interactive point viewer shows only provisional sampled geometry. The file picker does not persist a 3D asset, mark calibration or registration verified, infer coral condition, or create biological branch length or surface area. The scientist must save and execute a typed workflow graph to persist the analysis and its provenance; the existing standalone-versus-saved-workflow backend parity tests remain the scientific reference.

File/calibration changes invalidate in-flight preview responses; switching projects remounts an isolated preview session. Frontend API and component regression tests cover bounded local reading, invalid bytes and calibration, stale results, project isolation and failure handling. Full scientific acceptance, large/binary point clouds and persistent geometry assets remain future work.

## Optional source-index chord selection (October 23, 2026)

The standalone ASCII PLY preview now accepts an optional pair of zero-based **original source point indices**. Both indices must be supplied together; the frontend checks integer, distinct and 0–1999 bounds before sending a request, while the shared backend additionally checks indices against the actual imported point count. The optional `point_index_pairs` request uses the same scientific chord engine as saved executable `point_cloud_preview` workflows; the existing backend saved-workflow parity and reproducibility tests remain authoritative. The frontend tests cover the API payload, invalid index rejection and UI selection. The feature does not alter the imported point ordering or use the decimated display sample for measurements. Both the standalone and saved-artifact interactive viewers now display valid, bounded source-index chords as provisional straight-line distances, with scale-only uncertainty when available. Contradictory chord indices, nonfinite/negative distances, or invalid uncertainty cause the saved viewer to fail closed rather than present a misleading measurement.

These are provisional **straight-line endpoint chords**, not coral branch lengths, geodesics, biological landmarks or verified scale measurements. A scientist must save and execute a typed workflow graph to retain the geometry-derived measurement artifact, provenance and human-review trail. The file picker does not automatically save its temporary preview as a workflow or persistent asset.

## Chord display integrity check (October 23, 2026)

When both original source-point indices for a selected chord are present in the bounded interactive display sample, the frontend independently recomputes their straight-line distance from the sampled, calibrated XYZ coordinates. A nonfinite or contradictory reported chord distance causes the viewer to reject the artifact rather than display inconsistent scientific metadata. The comparison uses a small relative tolerance plus an absolute-coordinate-magnitude guard for cancellation at very large source-frame offsets; this avoids falsely rejecting full-resolution chords lost to rounding in the display sample. When one or both endpoints were omitted by deterministic decimation, the viewer **does not** reconstruct them or pretend to validate their distance: the full-input backend remains authoritative, and the saved workflow preserves the original indices and ordered-geometry fingerprint. This is a consistency check on provisional display metadata, **not** human verification, calibration acceptance, an anatomical branch-length estimate, or an independent validation of the full point cloud.

## Source-axis extrema coverage QC (October 23, 2026)

The deterministic 512-point interactive sample can omit an isolated outlier even
when the full 513–2,000-point input is valid. The shared standalone/API and saved
`point_cloud_preview` Workflow Builder execution now compare raw XYZ extrema
against the sampled XYZ extrema before scale multiplication. They persist
`preview_omitted_axis_extrema` (any of `x_min`, `x_max`, `y_min`,
`y_max`, `z_min`, `z_max`), `preview_axis_extrema_covered`, and the
`preview_omits_axis_extrema` QC warning when applicable. The interactive
saved-artifact viewer displays the omission explicitly; malformed or
contradictory new coverage metadata fails closed. Older saved artifacts without
this field remain readable but show coverage as **unassessed**.

This checks whether the displayed sample reaches each *axis-aligned* source
extremum. It does **not** establish full convex-hull coverage, adequate point
density, a valid organism outline, anatomical branch length, tissue surface
area, verified calibration, or source-frame registration. Full-cloud bounds,
selected source-index chords, geometry fingerprints, uncertainty intervals,
and scientific provenance are unchanged by display decimation. Tests include a
513-point scan with a hidden extreme at original index 511, standalone versus
saved executable workflow parity, and malformed frontend metadata.

The saved viewer now independently compares displayed point extrema with the persisted full-cloud bounding box. If a missing axis extreme remains numerically visible after calibration scaling, its omission must appear in `preview_omitted_axis_extrema`; otherwise the artifact fails closed. Conversely, a reported omission is treated conservatively even if large source-frame offsets make the scaled sample and bound numerically equal: rounding can erase evidence of a genuinely missing raw extreme. This validation does not upgrade the preview to a verified measurement. Regression tests cover falsely claimed complete coverage, wrong-axis omission flags, and conservative warnings.


## Provisional specimen/timepoint provenance

Point-cloud previews accept optional `specimen_id`, `observation_id`, and
timezone-aware `observed_at_utc` fields. The standalone endpoint and executable,
persisted `point_cloud_preview` Workflow Builder node normalize the observation
timestamp to UTC and save these fields in measurement provenance. Invalid IDs and
timestamps without a timezone are rejected; omitted fields remain null.

Both `specimen_identity_verified` and `observation_metadata_verified` are
always false. These caller-provided labels do not establish a reviewed organism
registry, point-cloud registration, longitudinal re-identification, growth,
survival, or a confirmed observation. A geometry hash may match even when
specimen labels differ; neither hash nor label is evidence of biological identity.
Scale-only uncertainties do not account for scan reconstruction or registration
errors. No user-trained model weights or cloud services are involved.

## Opt-in extrema-preserving display sample (October 24, 2026)

Both the standalone point-cloud preview request and the executable, persisted
`point_cloud_preview` Workflow Builder node now accept the strict boolean
`preserve_axis_extrema_in_preview` (default `false` for backward compatibility).
When enabled for more than 512 points, the deterministic source-index sample
retains the first source occurrence of each minimum and maximum XYZ coordinate,
plus its original first and last point, within the same 512-point budget. Other
uniformly sampled indices are displaced, never reindexed; the full input is
still used for bounds, chords, hashes and calibration measurements.

The result records `preview_extrema_source_indices` and
`preview_sampling_strategy` alongside the existing
`preview_axis_extrema_covered` QC fields. The opt-in sampling policy can make
axis extrema visible in the interactive sample, but does not prove that a
single isolated outlier is a biological feature or that a reconstruction is
complete. No source points are deleted, no coordinates are registered, and
calibration and specimen identity remain explicitly unverified. Scientists
should compare the original scan with the preview before accepting biological
interpretations. Regression coverage includes a 513-point hidden-extreme
example, strict request validation and saved-workflow parity.


## Optional measured-chord endpoint preservation (October 27, 2026)

For scans larger than the 512-point display budget, the default deterministic
index sample can omit original point indices used by an explicitly selected
straight-line chord. The local ASCII PLY file picker now exposes an explicit checkbox; the
same option is available as the request/workflow parameter
`preserve_measured_chord_endpoints_in_preview: true`, which pins both original
source indices of every validated `point_index_pairs` selection into the
bounded preview (up to 32 pairs, at most 64 endpoints). The existing
`preserve_axis_extrema_in_preview` flag can be combined with this option.
The sampler reserves first/last source indices and any requested protected
indices, then fills remaining slots evenly over the **entire** unprotected
source index range rather than favoring early file rows.

The result records `preview_omitted_selected_chord_endpoint_indices` and
`preview_selected_chord_endpoints_covered`, so a default/legacy sampling
decision remains auditable. The sampling strategy identifies chord-only,
extrema-only, combined, or default uniform-index selection. The opt-in
changes **display indices only**: calibrated full-input extents, source
geometry hashes, original-index chord distances, and scale-only uncertainty
remain unchanged. Standalone API and saved executable typed Workflow Builder
graphs use the same service; scientific regression tests cover both, including
512-point limits and distributed source-index coverage.

An endpoint shown in the interactive viewer is **not** a reviewed anatomical
landmark. Chords remain unverified Euclidean distances, never inferred coral
branch lengths or geodesics. The flag does not create persistent point-cloud
assets, establish calibration or registration, or promote model output to
verified biological evidence. Existing requests retain their default behavior.

The interactive point-cloud viewer now reports whether selected source-index
chord endpoints are actually present in the bounded display sample. It
cross-checks the reported omitted indices against the saved chord selections
and sampled source indices; contradictory, duplicated, missing-pair, or
incorrectly marked coverage metadata fails closed instead of hiding a display
omission. Older persisted previews without these fields remain readable, with
endpoint display coverage explicitly marked **unassessed**. This is a visual
completeness check only: even when every endpoint is displayed, neither the
chord nor its calibration becomes human-verified or an anatomical branch length.

## Omitted selected-chord endpoint QC (October 27, 2026)

When the 512-point display sample omits either original source index of a selected
point-pair chord, the measurement result now adds the machine-readable
`preview_omits_selected_chord_endpoints` warning to `qc_warnings`, alongside
`preview_omitted_selected_chord_endpoint_indices` and
`preview_selected_chord_endpoints_covered=false`. Opting into endpoint pinning
keeps selected indices visible within the same bounded preview budget and clears
this warning when all are covered. A hidden endpoint does **not** invalidate the
full-input chord calculation, but its distance cannot be independently checked
from the decimated display alone. Direct-service tests and standalone-versus-
saved typed Workflow Builder regressions cover both omission and pinning. These
warnings do not verify calibration, registration, coral identity or biological
branch length; they preserve an explicit human-review limitation.


## Repeated source-index chord QC (October 27, 2026)

The shared point-cloud measurement engine now flags a selected point-index
chord when its **unordered pair of original source indices** has already been
measured in the same request. A reversed pair (such as `[1, 0]` following
`[0, 1]`) and an exact repeat both receive the per-chord
`repeated_point_pair` warning. The top-level
`repeated_selected_point_pairs` QC warning signals that the selected
measurement set contains repeated evidence. The first occurrence is retained
without this warning, and the input order, endpoint geometry fingerprints,
measured distances, and uncertainty intervals remain unchanged.

This is an audit warning, not automatic deduplication: repeated chords must
not be counted as independent branch segments or biological replicates.
Distinct source indices that happen to share identical XYZ coordinates remain
covered by the existing `coincident_endpoint_coordinates` warning, not by
index-pair deduplication. Both the standalone API and executable persisted
`point_cloud_preview` Workflow Builder node use the same rule, with saved
artifact parity regression coverage. No calibration, organism identity,
anatomical branch length, or human verification is inferred.


## Repeated XYZ chord geometry QC (October 27, 2026)

Point-cloud scans may contain multiple **different original point indices** with
identical XYZ coordinates. Repeated source-index pair checks alone cannot
recognize that two selected chords trace the same unordered geometric endpoints.
The shared scientific measurement service now compares exact unordered endpoint
coordinate pairs within each request. A subsequent chord with the same geometry
but a different unordered source-index pair receives the per-chord
`repeated_endpoint_geometry` warning, and the result receives
`repeated_selected_endpoint_geometry`. Exact or reversed repeats of the
**same source-index pair** continue to receive `repeated_point_pair` instead;
the warnings distinguish source-index reuse from duplicated reconstruction
geometry. The first geometric occurrence is retained unflagged.

This check is deliberately exact (not tolerance-based): nearby points may
represent different anatomy, and no spatial clustering or branch inference is
attempted. Distances, scale-only uncertainty, original point indices,
ordered-endpoint geometry fingerprints, full-cloud geometry fingerprints, and
provenance remain unchanged. The standalone API and executable, persisted typed
Workflow Builder graph share the implementation and regression coverage.
Neither warning verifies coral identity, calibration, surface area, anatomical
branch length, or independent biological replicates; human review is required.

## Selected-chord QC summary (October 27, 2026)

The provisional point-cloud result now includes a
`selected_point_chord_qc_summary` with the number of requested chords,
distinct unordered source-index pairs, distinct unordered exact XYZ endpoint
geometries, and zero-distance chords whose two endpoint coordinates coincide.
The top-level `coincident_selected_chord_endpoints` warning identifies any
zero-distance selected chord; individual chord records continue to carry
`coincident_endpoint_coordinates`. Empty selections report zero counts.

These counts describe **user-selected geometric chords**, not coral branches,
independent biological replicates, verified landmarks, or observations of
growth. Duplicate source indices and duplicated reconstructed XYZ vertices
remain distinguishable. The summary does not alter source geometry, chord
distances, uncertainty intervals, calibration provenance, or provisional
verification. The standalone endpoint and saved executable typed Workflow
Builder graph use the same calculation, with regression checks for identical
saved-artifact summaries and provenance.

## Sampled preview-point scale uncertainty (October 27, 2026)

The point-cloud preview now returns `preview_point_scale_intervals_m` for each
displayed XYZ point, aligned exactly with `preview_point_indices` and
`preview_points_in_source_frame_m`. Each point contains three signed
`[minimum, maximum]` coordinate intervals in meters. The same positive
scale-factor bounds are applied to the corresponding source-frame coordinate;
negative values are sorted so the lower limit remains first. Zero coordinates
retain zero-width intervals. An explicitly supplied uncertainty of zero yields
`[coordinate, coordinate]`, whereas unknown uncertainty yields `null` for
the entire field.

These intervals propagate **only caller-supplied relative scale uncertainty**.
They are not per-point reconstruction error bars, spatial-registration
uncertainties, biological confidence intervals, or validated positions in a
geographic coordinate system. Display decimation does not affect the underlying
full-resolution point measurements. Calibration remains unverified and the
measurement status remains `caller_supplied_unverified`.

The standalone endpoint and executable persisted `point_cloud_preview`
Workflow Builder node use the same engine. Regression coverage checks signed,
zero and absent uncertainty, plus standalone/saved-graph parity for both direct
XYZ points and imported ASCII PLY. The sampled uncertainty field is optional
display/scientific-review metadata, not a replacement for persistent 3D assets,
anatomical landmarks, or calibrated biological surface/branch measurements.
