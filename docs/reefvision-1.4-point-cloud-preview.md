# ReefVision 1.4 — provisional XYZ point-cloud preview

The standalone `POST /api/v1/projects/{project_id}/spatial/point-cloud-preview` endpoint and executable persisted `point_cloud_preview` Workflow Builder node share one bounded measurement engine.

Inputs are **either** up to 2,000 XYZ points **or** a vertex-only ASCII PLY 1.0 file with three floating-point XYZ properties and optional complete `uchar`/`uint8` red, green, blue properties in any column order. RGB values are validated as integers in [0, 255]; raw RGB for sampled display points is returned separately from geometry: measurements and geometry fingerprints use XYZ only, not color. For PLY inputs, `provenance.source_text_sha256` separately fingerprints the exact UTF-8 text received (including RGB and header); this is not a digest of the original disk file, an organism identifier, or evidence of human verification. Direct XYZ inputs report `null` for this source-text digest. Partial RGB, binary PLY, polygon meshes, normals, and other attributes remain unsupported. The original PLY is passed as text; **no persistent 3D asset is created**.

Outputs include point count, duplicate-point QC, calibrated global-axis extents and diagonal, arithmetic centroid in the source coordinate frame, and scale-only uncertainties when supplied. Optional `point_index_pairs` (up to 32 pairs of distinct zero-based indices) returns calibrated straight-line chord distances and scale-only uncertainty for selected original input points. Pair indices are strictly integers and must be within bounds. Each chord also records its two calibrated endpoint coordinates in the original source frame and an ordered, scale-independent SHA-256 fingerprint of the selected raw endpoint geometry. This provides a reviewable guard against silently reassigning point-index measurements when source point ordering changes; it is not a persistent landmark or organism identity. Each chord includes `chord_distance_scale_interval_m` (lower/upper bounds) when scale uncertainty is provided; it is `null` when unknown. These are scale-only intervals, not statistical confidence intervals or biological branch lengths. These chords are not surface geodesics or biological branch lengths. An additional ordered-geometry SHA-256 fingerprint records the exact point order used for index selection; the existing order-independent geometry fingerprint is retained. The axis-aligned bounding-box **envelope** volume (m³) is the product of the three extents, **not** coral tissue volume or reconstructed occupied volume. Its scale-uncertainty interval applies the lower and upper scale factors cubically. Coplanar or collinear points have zero envelope volume, regardless of actual organism thickness. Surface area and branch length are **null**, not estimated from a point cloud. Scale evidence and exact geometry fingerprint are recorded, but calibration and coordinate registration are **not verified**. Dimensions are not anatomical branch measurements, and geometry fingerprints are not organism identities.

**Signed-zero geometric identity (November 16, 2026):** IEEE-754 `-0.0` and `0.0` encode the same source-frame spatial coordinate, so direct XYZ and imported ASCII PLY preview measurements now canonicalize either representation to positive zero before calculating the ordered/unordered geometry and selected-chord fingerprints. This prevents notation-only sign changes from masquerading as a different coral scan or reference chord. For PLY, the original text SHA-256 still changes when the text changes; source-byte integrity remains distinct from geometric identity. Existing persisted review receipts bound to a legacy signed-zero geometry hash may require explicit reassessment rather than silent verification; hashes are not organism identities and all calibration/registration evidence remains provisional. Standalone, direct-service and repeated saved-workflow regressions check the distinction.\n\n**Numerical calibration integrity (November 2026):** A nonzero original XYZ coordinate that becomes floating-point zero after multiplication by the supplied meters-per-unit scale is rejected, rather than persisted as an apparently measured zero. This applies identically to direct XYZ and ASCII PLY preview requests, the standalone API, and executable saved Workflow Builder graphs. Truly zero source coordinates remain valid, and extremely small *representable* calibrated lengths are retained. The fail-closed rule protects sampled coordinates, selected chords, bounding measurements, and provenance against silent calibration underflow; it does **not** validate physical calibration, source capture accuracy, anatomical identity, or reconstruction uncertainty. Regression coverage requires failed workflows to produce no measurement artifact and successful tiny-scale workflows to reproduce the complete standalone artifact.

**Envelope interval numerical resolution (November 2026):** A positive, representable three-dimensional bounding-box envelope can have a lower scale-only uncertainty bound that rounds to floating-point zero even though the lower scale factor is strictly positive. In this case, the nominal envelope remains available, but `axis_aligned_bounding_box_envelope_volume_scale_interval_m3` is `null` and `envelope_uncertainty_interval_below_numeric_resolution` is added to `qc_warnings`; zero must not be reported as a physically supported lower bound. This is distinct from `envelope_volume_below_numeric_resolution`, which indicates an unrepresentable **nominal** positive volume. A relative scale uncertainty of exactly 1.0 has a mathematically valid zero lower scale factor and retains its zero lower bound; ordinary representable intervals remain unchanged. Direct-service, XYZ/ASCII-PLY standalone API, and executable persisted Workflow Builder regression cases guard parity and provisional calibration. No coral tissue volume, physical measurement uncertainty, or biological verification is inferred.

**Dimension uncertainty interval numerical resolution (November 16, 2026):** The
optional `axis_aligned_dimension_scale_interval_m` reports lower/upper
scale-only uncertainty bounds for each source-axis extent (or `null` when
uncertainty is absent). If an axis has a positive calibrated nominal extent
but a mathematically positive lower scale factor rounds its lower bound to
zero, only that axis interval is `null`, with
`dimension_uncertainty_interval_below_numeric_resolution` in `qc_warnings`.
The nominal dimensions, other unaffected axis intervals and calibration
provenance remain available. An actually zero source-axis extent retains
`[0, 0]`; 100% relative scale uncertainty retains a genuinely zero lower
bound. XYZ/ASCII PLY standalone, direct-service and saved executable
Workflow Builder regression cases require identical provisional artifacts.
These are numerical limits of scale propagation, not physical measurement
accuracy, verified coral morphology or anatomical branch lengths.

**Signed coordinate scale-interval numerical resolution (November 16, 2026):** The optional scale-only intervals for sampled preview XYZ coordinates, source-frame extrema and arithmetic centroid now use `null` for an individual coordinate interval if its nonzero signed nominal coordinate has a strictly positive lower scale factor but either nonzero uncertainty bound numerically rounds to zero. `coordinate_uncertainty_interval_below_numeric_resolution` identifies this loss in `qc_warnings`; other representable axes and actual zero coordinates retain their valid bounds. At 100% relative scale uncertainty a zero bound is mathematically valid and remains reported. Negative source-frame coordinates are handled symmetrically. The XYZ/ASCII PLY standalone API and executable saved Workflow Builder paths use the same measurement engine; synthetic direct-service regressions cover both signs and saved-workflow artifact equality. A `null` interval means **numeric precision is insufficient**, not that calibration was physically invalid or an organism coordinate was verified.

**Selected-chord uncertainty interval resolution (November 2026):** When a provisional, positive calibrated source-index chord has positive lower scale factor but its lower uncertainty distance rounds to zero, the nominal `chord_distance_m` is retained, `chord_distance_scale_interval_m` is `null`, and per-chord/top-level `chord_uncertainty_interval_below_numeric_resolution` / `selected_chord_uncertainty_interval_below_numeric_resolution` warnings identify the missing numeric precision. A relative uncertainty of exactly 1.0 retains a mathematically valid zero lower bound. XYZ and ASCII PLY standalone endpoints and executable persisted Workflow Builder regressions require identical artifacts. This does not establish independently verified calibration, organism identity, or anatomical branch length.

**Selected-chord absolute scale-uncertainty precision (November 16, 2026):** A positive subnormal chord can have nonzero supplied relative scale uncertainty even when the computed absolute `scale_uncertainty_m` rounds to zero. Whenever the corresponding chord scale interval is numerically unresolved, its absolute uncertainty is now `null` rather than falsely reported as zero. Exact zero relative uncertainty still returns a valid zero, and a mathematically valid zero lower scale bound (100% relative uncertainty) remains available. Direct XYZ/ASCII PLY measurements, the standalone API, and typed persisted Workflow Builder runs have synthetic regression coverage. This QC change does not verify physical calibration or convert chords into anatomical branch lengths.

**Selected-chord precision guard:** A full point cloud can retain its calibrated axis extents while a pair of very close selected source points becomes numerically indistinguishable. Point-chord measurement now fails closed when distinct source endpoints produce zero calibrated separation or identical calibrated XYZ coordinates; truly coincident source XYZ still retains a zero-length chord with its explicit QC warning. This applies to standalone XYZ/ASCII-PLY requests and persisted typed Workflow Builder runs; a failed run must save no point-cloud measurement artifact. Positive controls retain representable subnormal chord lengths. This checks floating-point representability, not measurement accuracy, biological anatomy or field calibration.

A regression test replays a persisted `point_cloud_preview` graph twice and requires identical artifact payloads and SHA-256 content digests, including unverified calibration and source-text provenance. This checks deterministic workflow reproducibility, not the accuracy of the source measurements.

The optional `coordinate_frame_id` is a bounded caller-provided label for the source reconstruction coordinate system. It is preserved in `provenance.coordinate_frame_id` for both standalone API and executable saved Workflow Builder artifacts. Matching frame labels do **not** prove that separate observations are spatially registered or share a surveyed origin; `coordinate_registration_verified` remains `false`. Invalid, empty, or overlong frame labels are rejected by the request contract. The saved-workflow parity regression checks this label alongside other provenance fields.

Both standalone API and saved-workflow artifacts remain `caller_supplied_unverified`. Do not promote to a verified scientific observation without human review and registration/calibration QC. Future work includes persistent 3D assets, large/binary clouds, registration and longitudinal comparisons.

For visualization preparation, the result includes a deterministic sample of up to 512 source-indexed points with calibrated coordinates. For clouds exceeding 512 points, first and last indices remain included; selected measurement endpoints need not appear in the display sample. The full input, not the decimated sample, determines extents, centroid, fingerprints and point-pair measurements. This is display geometry only: it does not establish a validated organism surface or anatomical landmark, and the persisted Workflow Builder artifact now has a read-only interactive SVG viewer with yaw, pitch, zoom, reset, and optional sampled RGB. The standalone and saved-workflow previews must agree on sampled indices and coordinates.

The preview also returns calibrated minimum and maximum XYZ coordinates in the **original source frame**. These axis-aligned bounds preserve negative coordinates and support future interactive camera framing; they are not registered geographic positions. Standalone API results and persisted Workflow Builder artifacts must agree on these bounds.

The arithmetic point-sample centroid also includes `arithmetic_centroid_in_source_frame_scale_interval_m` when relative scale uncertainty is supplied, with lower and upper limits sorted correctly for negative source coordinates. It is `null` when uncertainty is unknown. This interval propagates **scale uncertainty only**; it does not account for reconstruction error, point-sampling density, or unverified coordinate registration. A sample centroid is not a validated organism center of mass. The standalone and saved-workflow results must match.

**Calibrated centroid arithmetic precision (November 16, 2026):** The arithmetic point-sample centroid now sums the *calibrated* XYZ coordinates with compensated summation before dividing by the number of points. Previously, dividing a subnormal raw-coordinate sum by the point count could round a nonzero mean to zero before a large, valid meters-per-unit scale made it representable. For example, a three-point cloud with one source X coordinate of `5e-324` and an unverified scale of `1,000,000` m/unit has a representable positive calibrated mean X; the pre-calibration division reported zero. Synthetic positive/negative XYZ and ASCII PLY regressions require direct-service, standalone API, and executable persisted Workflow Builder parity (including provenance and scale intervals). This is a floating-point accuracy safeguard only: a point-sampling centroid is not a validated biological center, registration, or instrument calibration, and means below numeric resolution may remain unrepresentable.

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

## Interactive sampled-point inspection (October 27, 2026)

The read-only point-cloud viewer now allows mouse or keyboard selection of
displayed source-index points. The inspection readout reports calibrated XYZ
coordinates in the **unregistered source frame** and, when supplied, signed
scale-only coordinate intervals. The viewer preserves original source indices
despite depth sorting and does not modify saved workflow artifacts or scientific
measurements. When the selected point is not present in a new display sample,
no stale coordinates are shown.

The viewer validates the optional per-point intervals against the associated
calibrated coordinates and the provenance relative scale uncertainty. Invalid,
misaligned, nonfinite, inverted or contradictory intervals fail closed instead
of appearing as verified positions. Legacy saved artifacts without interval
metadata remain viewable and explicitly report unknown scale uncertainty.
The same viewer is used for standalone and persisted Workflow Builder preview
results; frontend regressions cover mouse/keyboard inspection, source-index
alignment, immutable artifacts and malformed saved evidence.

This is **not** spatial registration, calibration verification, anatomical
landmark identification, coral condition assessment, or persistent 3D storage.
A source-index selection is a display inspection, not a scientist-verified
biological annotation.

## Mesh viewer provenance guard (October 27, 2026)

The sampled-triangle viewer rejects saved display payloads that explicitly
claim verified calibration, coordinate registration, specimen identity,
observation metadata, or a measurement status other than
`caller_supplied_unverified`. Contradictory or malformed supplied calibration
provenance also fails closed. This prevents a preview-only surface from
silently presenting incompatible scientific review claims. Existing legacy
display artifacts that omit optional review metadata remain viewable and are
still labeled provisional.

This is a frontend scientific-integrity check, not a verification workflow:
source-file fingerprints, human review, calibration and registration evidence
must still be assessed independently. It does not change standalone mesh
measurements or saved Workflow Builder execution and does not create
persistent project-scoped 3D assets. Regression tests cover invalid claims,
the fail-closed display, and legacy compatibility.


## Bounded RGB decimal tokens (November 1, 2026)

ASCII PLY unsigned-byte RGB channels are validated as at most three ASCII
decimal digits representing 0–255 before integer conversion. A long string of
leading zeroes must not trigger Python's integer-string conversion limit or
bypass a consistent scientific import error. Ordinary bounded representations,
including `000`, remain supported. Invalid source rows fail atomically:
a supplied color output buffer is not partially modified.

The standalone point-cloud endpoint and executable, persisted, typed
`point_cloud_preview` Workflow Builder node use the same parser. Regression
tests reject both four-digit and oversized zero-padded channels and require
failed graph execution to publish no point-cloud measurement artifact. Valid
colors are display metadata only; they do not imply coral condition,
independent calibration, verified biological identity, or surface area.

## Strict ASCII PLY input boundary (November 2026)

The backend now rejects **any non-ASCII code point** in imported PLY 1.0
point-cloud text, including Unicode digits that Python might otherwise parse
as floating-point coordinates, Unicode whitespace, and non-ASCII comments.
The local picker already requires ASCII, but direct API and saved Workflow
Builder submissions must enforce the same rule. An invalid PLY fails without
a provisional measurement artifact; valid ASCII comments and numeric values
remain supported. This also avoids silently treating Unicode-normalized
inputs as interchangeable with the exact submitted source bytes.

The prior RGB-token bound remains in force: each color channel must contain
one to three ASCII decimal digits representing an unsigned byte from 0 to 255.
These are import-integrity checks, **not** evidence of verified calibration,
registered coordinates, biological condition, specimen identity, or accuracy.

## ASCII PLY control-character integrity (November 2026)

Imported ASCII PLY 1.0 point clouds now reject embedded ASCII control bytes
other than tab, carriage return and line feed, including NUL, vertical tab,
form feed, escape and DEL. Python's text splitting routines otherwise treat
some control bytes as whitespace or line separators, potentially interpreting
malformed source rows differently from the submitted file. Ordinary CRLF line
endings and tab-delimited vertex coordinates remain accepted.

The direct parser, standalone project point-cloud endpoint and executable,
persisted, typed Workflow Builder node share this fail-closed validation.
Regression tests require invalid imports to fail without publishing a
point-cloud measurement artifact and preserve valid ASCII whitespace support.
This is source-format integrity only: it does not authenticate calibration,
coordinate registration, coral identity, anatomical branch length or
biological condition. Source-file review and scientific verification remain
necessary.

## PLY error-contract and saved-workflow parity (November 2, 2026)

A syntactically valid point-cloud request whose submitted ASCII PLY text fails
the bounded scientific parser returns **HTTP 400** with a specific validation
detail (for example, invalid vertex count, numeric token, precision underflow,
or unsupported control byte). **HTTP 422** instead describes request-schema
validation failures before the PLY parser runs. These statuses must not be
interchanged in regression tests: parser rejection is an intentional,
fail-closed outcome, not a failed schema validator.

The same malformed source must fail a persisted, executable, typed
`point_cloud_preview` Workflow Builder run without publishing a
`point_cloud_measurement_preview` artifact. Regression tests now assert the
standalone status and exact parser reason before exercising saved-graph
execution. Atomic RGB rejection tests also track the strict numeric grammar:
nonfinite `nan` is rejected as an invalid coordinate token before numeric
conversion, and existing color buffers remain unchanged. Successful source
parsing remains provisional and does not verify scale, reconstruction,
registration, coral identity, biological condition, or anatomical branch length.

## Nonplanar point-cloud envelope underflow QC (November 16, 2026)

The optional axis-aligned bounding-box **envelope volume** is a geometric
product of three measured extents, not coral tissue volume. With extremely
small caller-supplied scales, all three lengths can remain finite and nonzero
while their cubic product underflows the available floating-point precision.
Previously, that case incorrectly reported a zero envelope volume, which is
indistinguishable from a truly planar cloud.

For a nondegenerate cloud in that condition the result now retains its three
measured dimensions but reports
`axis_aligned_bounding_box_envelope_volume_m3: null`, a null scale-only
envelope-volume interval, and the explicit QC warning
`envelope_volume_below_numeric_resolution`. A truly planar or collinear
cloud still reports a genuine zero volume (and, when an uncertainty is
provided, the interval [0, 0]). No uncertainty interval is fabricated for an
unrepresentable nominal volume.

XYZ and ASCII PLY synthetic regressions check direct service behavior,
standalone project API responses, and **full checksummed artifact equality**
through an executed, typed, persisted Workflow Builder graph. This is a
numerical-integrity boundary, not validated biological volume, scientific
scale calibration, registration, tissue completeness or coral reidentification.

**Representable mixed-scale envelopes (November 16, 2026):** Axis-aligned
envelope multiplication now evaluates the larger axis extents first. Extremely
small X/Y extents multiplied before a large Z extent could previously round an
intermediate product to zero even though the full three-axis product is a
positive, representable subnormal number. The revised multiplication retains
such provisional positive envelopes and their representable scale-only bounds.
It still returns `null` plus `envelope_volume_below_numeric_resolution` when
the final nominal envelope itself cannot be represented. XYZ/ASCII PLY standalone
requests and executable saved Workflow Builder graphs are tested for exact
artifact/provenance parity using a synthetic mixed-scale example. This numerical
safeguard does **not** validate tissue volume, coordinate registration, physical
calibration, or coral identity.

## Quantized positive envelope-uncertainty bounds (November 16, 2026)

A positive but subnormal axis-aligned envelope may be representable even when
distinct mathematical scale-uncertainty bounds both round to the **same**
floating-point number. Reporting that degenerate interval would falsely imply
zero uncertainty. When relative scale uncertainty is strictly positive and
the computed bounds are identical, the preview now retains the nominal
envelope, sets its scale-only interval to `null`, and emits
`envelope_uncertainty_interval_below_numeric_resolution`. The same warning
continues to cover a positive lower bound that underflows to zero. An exactly
zero caller-supplied scale uncertainty retains a legitimate [volume, volume]
interval; a truly planar cloud remains [0, 0].

Parameterized XYZ/ASCII PLY regressions exercise the direct scientific service,
standalone endpoint, typed graph planning and fully executed persisted Workflow
Builder, including complete saved-artifact equality and provisional provenance.
The synthetic subnormal examples test numeric integrity only, **not** verified
calibration, validated coral tissue volume or organism condition.
 
## Dimension absolute-uncertainty parity at numeric limits (November 16, 2026)

The axis-aligned dimension's absolute scale uncertainty now follows its
`axis_aligned_dimension_scale_interval_m` availability. If a **positive**
dimension and supplied positive relative uncertainty have an interval below
binary64 resolution, the corresponding entry in
`axis_aligned_dimension_scale_uncertainty_m` is `null`, not a misleading
`0.0`. Other axes remain independently measurable. An exactly zero
dimension or an explicitly zero relative uncertainty retains a genuine
zero absolute scale uncertainty. The existing
`dimension_uncertainty_interval_below_numeric_resolution` warning explains
an unresolved interval; no new certainty or biological inference is implied.

Parameterized XYZ and ASCII PLY direct-service, standalone endpoint and
executable saved-workflow regressions cover underresolution, exact-zero and
100%-relative-uncertainty inputs, with whole-artifact parity and unverified
calibration provenance. This scale-only numerical safeguard does not provide
reconstruction, photogrammetry, coral-anatomy or statistical confidence limits.

## Bounding-diagonal scale uncertainty at numeric limits (November 16, 2026)

The calibrated axis-aligned bounding-box diagonal now exposes
`axis_aligned_bounding_box_diagonal_scale_interval_m` alongside the existing
nominal diagonal. It propagates the caller's **relative scale uncertainty only**,
not photogrammetric/reconstruction accuracy or a statistical confidence interval.
When the diagonal is positive but its lower/upper scale bounds collapse to a
false zero-width interval (or lose a mathematically positive bound through
underflow), the interval and existing absolute diagonal uncertainty become
`null`, and `diagonal_uncertainty_interval_below_numeric_resolution` appears
in `qc_warnings`. A genuinely zero diagonal and exactly zero relative scale
uncertainty retain valid exact bounds; 100% uncertainty preserves a genuine zero
lower bound. Unknown scale uncertainty leaves the interval null without the
numeric-resolution warning.

Signed XYZ and vertex-only ASCII PLY inputs share the same engine. Synthetic
regressions compare direct measurements, standalone API output, and complete
provisional persisted artifacts from executable typed Workflow Builder graphs.
An axis-aligned diagonal is **not** measured coral branch length, and no
calibration, coordinate-frame registration, specimen identity, or biological
condition is independently verified.

**Exact source affine dimension (November 16, 2026):** `source_affine_dimension`
is 0 for coincident points, 1 for collinear samples, 2 for planar samples,
and 3 for affinely three-dimensional imported source-coordinate samples.
Exact rational predicates on the finite binary-float coordinates avoid
guessing a planarity threshold or silently losing subnormal geometry.
Lower-dimensional clouds emit `source_point_cloud_affine_dimension_below_3`.
A tilted straight line or plane can have positive global-axis XYZ spans and
a positive 3D *bounding-envelope* volume without occupying three-dimensional
volume. A rank of 3 does **not** validate watertightness, inferred coral
tissue volume, reconstruction accuracy, physical calibration, biological
anatomy or surface area. Capture noise can turn an otherwise planar specimen
into exact rank 3; interpret this as source-coordinate QC only. Synthetic
XYZ and ASCII PLY direct, standalone API and repeated executable persisted
Workflow Builder tests verify identical rank and QC provenance.


## Positive bounding envelope of a lower-dimensional point set (November 16, 2026)

The source-coordinate affine-rank diagnostic now also emits
`positive_bounding_envelope_for_lower_dimensional_source` **only** when a
rank-0/1/2 point set nevertheless has a strictly positive, representable
axis-aligned 3D bounding-envelope volume. A tilted line or plane may span
nonzero X/Y/Z extents, so the bounding envelope remains a mathematically
valid box measurement, but that number is **not** occupied volume, coral
biomass, tissue volume, or a reconstructed surface. True zero envelopes and
rank-3 scans do not receive this specific warning. The existing general
`source_point_cloud_affine_dimension_below_3` warning remains independent.

The XYZ and ASCII PLY synthetic affine-rank cases assert the new diagnostic
across the direct measurement service, standalone API, typed executable
Workflow Builder plan, and twice-executed persisted workflow artifacts.
Provenance remains explicitly caller-supplied and unverified; discrete exact
rank reflects imported floating-point coordinates and can be sensitive to
capture noise, so no biological or registration inference is authorized.
