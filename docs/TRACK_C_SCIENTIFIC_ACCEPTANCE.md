# Track C scientific acceptance protocol (development only)

This is a **test plan**, not evidence that ReefVision 1.4 or 1.5 is validated or release-ready. Run it against a pinned branch SHA, record the test fixture hashes, and attach review evidence to issue #76. No simulated result is a field validation.

## 1.4: 3D geometry and longitudinal studies

### Point-cloud axis-projected sampling gaps (synthetic; CI pending)

The standalone XYZ/ASCII-PLY point-cloud preview now reports the largest gap
between adjacent **distinct source-coordinate levels** on each of the X, Y,
and Z axes. It includes original source endpoints, gap size, fraction of the
observed axis span, scale-converted gap and a scale-only uncertainty interval
when numerically representable. Each largest-gap boundary also reports its
**source-row count** and **distinct observed XYZ-locus count**, so repeated
acquisition rows cannot be mistaken for independent spatial observations.
Reordering rows does not change the diagnostics; adding duplicate rows
increases only the reported raw-row support, not the distinct-locus counts
or source-coordinate gap geometry. If several adjacent intervals share the
exact same largest represented source-coordinate gap, the report now includes
`equally_largest_adjacent_gap_count` and emits
`axis_sampling_multiple_equally_largest_gaps`. The endpoint pair is the
lowest-coordinate representative, **not** the sole gap. A non-constant axis
with one largest interval reports count 1; a constant axis reports count 0
and no endpoints. Exact binary64 tie counting is not an uncertainty-based
equivalence test for near-tied physical sampling gaps.
Constant axes have no adjacent gap and report `null`, not fabricated
support or a zero-length sampling observation.
If a positive gap or its scale-only interval is below binary64 resolution,
the converted quantity is `null` with a specific QC warning.

**Interpretation:** These are 1D projected sampling diagnostics for possible
acquisition/reconstruction coverage review, not Euclidean nearest-neighbor
distances, verified missing 3D regions, coral tissue gaps, biological branch
lengths, or animal condition. A boundary supported by several distinct XYZ
loci is still not evidence of continuous surface coverage; repeated rows
reflect acquisition multiplicity rather than replicated biological units.
Scale calibration and specimen identity remain unverified. The new field is computed by the shared engine and must match
between standalone API responses and two executions of the same persisted,
typed `point_cloud_preview` Workflow Builder graph, including artifact
SHA-256 parity, for both XYZ arrays and imported ASCII PLY. Regression:
`test_spatial_point_cloud_axis_gaps_v14.py` (including row-versus-distinct-locus
boundary support, exact maximal-gap ties, order invariance, direct service and saved-workflow replay).
These synthetic fixtures do not replace representative scans, independent
scientific reviewers, or Windows installed-GUI/GPU release acceptance.


## Imported point-cloud PLY Unicode boundary (synthetic; CI pending)

The stand-alone and typed persisted Workflow Builder PLY entrypoints must
reject malformed ASCII sources before SHA-256 source-byte provenance is
constructed. Direct service entry also must reject lone UTF-16 surrogates
and control bytes as a bounded `ValueError`, not crash with an uncaught
`UnicodeEncodeError` when old/untrusted saved records bypass model validation.
A well-formed ASCII PLY retains its exact source-byte digest, its unverified
calibration status, and normal deterministic saved-workflow replay; invalid
input produces no scientific measurement artifact. Regression:
`test_spatial_point_cloud_ply_numeric_grammar_v14.py` (direct boundary,
standalone API, fail-closed saved workflow) and existing source-binding
replay tests. This verifies parser integrity, not instrument calibration or
biological identity.


## Interactive render coverage QA (synthetic, GUI test; CI pending)

The persisted 1.4 mesh artifact already reports whether render-only sampling
omits source-axis extrema, the dominant triangle, disconnected patches or
reconstructed surface area, and whether missing area is numerically unrepresentable.
The interactive `MeshArtifactViewer` must show these **persisted** coverage
warnings in human-readable form rather than silently rendering an incomplete
sample. It must ignore arbitrary or malformed warning fields, preserve the
scientific artifact unchanged, and state that display QC cannot establish coral
condition or verified physical calibration. The source measurements, saved
typed Workflow Builder outputs, provenance hashes and calibration review remain
server-owned and are not recomputed or promoted by this UI.
Regression: `apps/web/src/features/workflow-graphs/MeshArtifactViewer.test.tsx`.
Representative installed-Windows inspection and independent biological review
remain release gates; a synthetic frontend test is not field validation.


**Near-parallel face area under 3D coordinate-frame changes (synthetic; CI pending):**
Seven integer-coordinate reference triangles include XY, XZ and YZ planes
and two genuinely oblique XYZ surfaces, with large translation, reflection
and reversed face winding. An independent arbitrary-precision integer
cross-product oracle checks squared magnitudes of 1, 9 and 6 source units
to the fourth power, corresponding to areas 0.5, 1.5 and sqrt(6)/2 source
units squared. In the oblique cases, cancellation corrupts two of the three nonzero
cross-product components in ordinary binary64 arithmetic, so a plausible
apparent area cannot be trusted. The parameterized
`test_spatial_mesh_area_cancellation_v14.py` regression checks the source
kernel, direct service, project-scoped standalone API, and twice-replayed
persisted typed `mesh_surface_preview` workflows, including deterministic
artifact hashes and explicitly unverified calibration/specimen identity.
This is a numerical coordinate-frame test, not independent physical
calibration, registered survey geometry, field validation, anatomical
branch area, or verified coral surface condition.

**Signed-volume magnitude overflow guard (synthetic source-kernel check; CI pending):**
A collection of repeated, oppositely oriented tetrahedron faces can have individually
finite signed face terms but a sum of their absolute magnitudes larger than the
largest representable binary64 value. Calling `math.fsum` directly on those
magnitudes raises `OverflowError` even when the signed total is zero or a
representable nonzero residual. The source kernel now normalizes by its largest
finite contribution before summation and uses a dimensionless cancellation
condition to trigger exact rational recovery. The regression uses 12
oppositely oriented synthetic tetrahedral shell copies at an edge of 5e102
source units, exact-zero and one-ULP apex-perturbed cases, and both face
windings. Verify the signed result against an independent `Fraction` oracle.
**These duplicated faces are intentionally not a valid imported coral mesh:**
do not submit them as an accepted standalone or saved Workflow Builder measurement.
Existing topologically valid standalone and twice-replayed persisted graph
regressions must remain green. This is numeric fail-closed protection, not a
calibrated biological-volume or independent human-verification claim.

**Cross-face signed-volume cancellation integrity (synthetic helper gate; CI pending):**
Even when no individual face determinant is near roundoff, an oriented sum
across faces may nearly cancel and return a plausible but inaccurate nonzero
volume. The provisional source-coordinate volume helper now detects aggregate
near-cancellation and recomputes from exact rational representations of the
imported binary64 coordinates. The regression uses two disjoint,
opposite-oriented synthetic tetrahedral shells (an arithmetic stress case,
**not** a biologically admissible coral volume). With one apex differing by
one representable binary64 step near 1e8, the prior floating-point sum yielded
67,108,864 source units³; the independent rational result is approximately
24,835,268.65641276 source units³. Both winding directions and the exact-zero
case must agree with the independent rational oracle.
`test_spatial_mesh_volume_cubic_scale_underflow_v14.py` covers this helper
gate; separate direct-service, standalone API and twice-replayed persisted typed
Workflow Builder tests cover the normal scientific measurement path. Neither
test category validates mesh topology, an organism's enclosed biological
volume, calibration or reviewer-confirmed identity.

**Calibrated-volume underflow contract reconciliation (synthetic; exact-head CI pending):**
A source-coordinate tetrahedron with orthogonal 1e-110-unit edges has a
strictly positive but binary64-unrepresentable source volume. The direct signed
volume helper must raise `Enclosed mesh volume underflowed numeric precision`,
not return a misleading zero. With caller-supplied 1e6 m/unit scaling, the
measurement service can recompute a positive approximately 1.6667e-313 m³
volume in calibrated coordinates; it must record
`enclosed_volume_source_unit_numeric_recovery` and keep calibration and
specimen identity unverified. With 1e-120-unit edges, even that scaling leaves
a positive volume below binary64 precision: the direct service must reject it,
the standalone endpoint must return HTTP 400, and two executions of the same
persisted typed Workflow Builder graph must fail with **no**
`mesh_measurement_preview` artifact, in both winding directions. Regressions
live in `test_spatial_mesh_volume_cubic_scale_underflow_v14.py`. These tests
reconcile earlier expectations of silent missing values with the newer fail-closed
volume engine; they do not verify real coral volume, calibration or identity.
Record final-head CI and human scientific review separately before acceptance.

**Source-coordinate triangle cancellation gate (synthetic, not field validation):**
Two nearly parallel XYZ triangles with exact source determinants of -1 and -3 must
produce areas of 0.5 and 1.5 source units squared, even if binary64 cross products
respectively round to zero or a plausible but incorrect nonzero result. Verify both
winding orders, reject genuinely unrepresentable positive areas rather than publish
zero, and retain exact collinearity as zero. Test direct measurement, standalone API,
and two executions of a saved typed Workflow Builder graph; assert complete artifact
and SHA-256 parity, unverified source specimen identity and scale-only uncertainties.
Regression: `test_spatial_mesh_area_cancellation_v14.py`. This does not validate coral
surface reconstruction, biological condition, or branch anatomy.

| Gate | Reproducible acceptance experiment | Required evidence |
| --- | --- | --- |
| Import | Load known-good and malformed OBJ, ASCII PLY and GLB 2.0 fixtures; include point-only PLY, excessive vertex/face counts, malformed indices and truncated input. | Deterministic parse outcomes, byte hashes, bounds checks and error messages; no network or remote model downloads. |
| Interactive preview | Inspect a calibrated, branched coral fixture, a point cloud and a disconnected mesh; exercise rotate, zoom, selection and reload in an installed Windows build. | Screenshots or recordings tied to build SHA and a human reviewer; rendering is not proof of biological identity. |
| Surface area | Compare a closed cube and two planar triangles against independently calculated metric areas at multiple unit scales. | Numerical tolerance, calibration method, units, mesh-topology QC and scale-only uncertainty interval. |
| Dimensions | Compare a rectangular prism against independently measured axes and diagonal after rotation and scaling. For simple planar researcher traces, independently verify maximum vertex chord / equal-area circle diameter on an analytical triangle at multiple scales and reversed waypoint orders. | Coordinate-frame provenance; the dimensionless planar elongation proxy requires positive finite source measurements and remains null for non-simple/nonplanar traces; do not label it organism elongation, anatomical width, or biological condition. |
| Branch length | Use independently traced synthetic centerlines and expert-traced coral branches with documented junction/tip definitions. | Agreement, topology sensitivity and calibration uncertainty; **surface edge path length is not validated anatomical branch length**. |
| Registration | Use known rigid transforms, mismatched coordinate frames and corrupted correspondence evidence. | RMS, transform validation, registration provenance and explicit unverified status until reviewed. |
| Identity and change | Compare the same specimen at two dates and two deliberately different specimens with blinded human reviewers. | Reviewer identity, decision timestamps, source asset IDs and hashes, disagreement handling, no automatic verified reidentification. |
| Longitudinal QC | Replay legacy observations missing face/patch counts, missing intervals, zero-area geometry, offset timestamps and forged metadata. | No invented zero measurements; contradictory topology rejected; normalized elapsed time; direct/API/saved-graph artifact parity. |
| Condition | Compare predeclared expert condition categories with held-out specimens and repeat reviewers. | Confusion matrix, inter-reviewer agreement, uncertainty and failure analysis; avoid treating geometry change as health without validation. |
| Model benchmarks | Run frozen held-out assets across pinned model/checkpoint versions and device profiles. | Dataset splits, inference time, accuracy by class/species, confidence intervals and explicit local-only checkpoint handling. |

An area-weighted centroid of a geometrically valid but **concave** filled outline may lie outside its perimeter (for example, inside the empty notch of a U-shaped contour). ReefVision 1.4 now separately reports `closed_loop_source_planar_centroid_inside_or_on_perimeter` as `true`, `false` or `null` using exact rational point-in-polygon checks on imported source coordinates. This is a geometric QC result, not a verified organism location or anatomical landmark. A `false` result emits `closed_surface_trace_source_planar_centroid_outside_perimeter`; consumers must not blindly use such a centroid as an interior tracking, sampling, or field reidentification point. For unassessable open/nonplanar/nonsimple outlines or unrepresentable centroid coordinates, the inclusion flag remains `null`. Validate a U outline with area 10 source units² and centroid (2, 1.7, 0) outside its filled region, including reversed/rotated winding, multiple calibrations, and saved-workflow artifact/provenance parity.

Point-cloud XYZ/PLY calibration must preserve source-axis spans, not just nonzero calibrated individual coordinates. When the source span is positive but the scaled span underflows to zero or the calibrated axis extrema round to the same number, report a deterministic integrity error rather than zero width or zero chord length. Exercise the standalone endpoint and saved typed Workflow Builder using two synthetic points at x = 1e-20 and x = 1.0000000001e-20 with a 1e-300 m/unit scale; contrast against x = 1e-20 and x = 2e-20, which retains a representable 1e-320 m extent. These numerical stress fixtures are **not** physically credible field calibrations or validated coral measurements.

Selected mesh surface-edge traces now withhold *all* ordered segment or cumulative scale-only intervals if even one positive waypoint bound collapses to an apparently exact value at binary64 precision. Nominal source geometry, total length and source-position fractions are retained, with `surface_trace_scale_interval_below_numeric_resolution` marking an unresolved positive-length bound; absent calibration uncertainty remains unknown, explicitly zero uncertainty remains exact, and a genuine zero lower bound at 100% uncertainty is valid. Exercise the synthetic sub-resolution case (`0.01` m length, `1e-17` relative scale uncertainty) through the direct engine, standalone endpoint and twice-executed persisted graph, comparing artifacts and hashes. This is numerical-integrity QC, not an accuracy estimate or biological branch-length validation.

Triangle-area precision negative controls must reject positive but binary64-unrepresentable source areas in all three orthogonal coordinate planes, regardless of triangle winding, while retaining exactly zero area for truly collinear vertices. Exercise the zero-versus-positive distinction through the direct helper, standalone endpoint and **two separate executions of the same persisted typed mesh workflow**, requiring both failure runs to leave no `mesh_measurement_preview` artifact. Pair this with a representable small-area control whose standalone payload matches two successful saved-workflow artifacts and deterministic SHA-256 hashes. These synthetic cases establish numeric-integrity behavior only, not validated coral tissue surface area, reconstruction uncertainty or biological condition.

**Underflow interface matrix (1.4, November 20, 2026):** The standalone mesh endpoint and twice-executed persisted typed Workflow Builder negative path now have explicit regression cases for all six combinations of XY/YZ/ZX planes and face winding. Each case must reject a positive 1e-200-by-1e-200 triangle with the numeric underflow diagnostic and leave no measurement artifact. The source-level test independently checks all three planes and both windings; a successful run on the latest commit is still required before treating this as a passing gate. These synthetic inputs test numerical error handling, not measurement validity at biologically useful scales.

**Regression reconciliation (1.4, November 20, 2026):** The legacy mesh shape-ratio fixture at 1e-200 source units is a **rejected** noncollinear area-underflow case (standalone HTTP 400 and two failed executions of the same saved typed graph with no mesh measurement artifact), **not** a successful preview with a warning. A truly coincident-vertex triangle, by contrast, remains a successful explicitly zero-extent preview with `mesh_shape_ratio_unavailable_zero_extent`, unverified calibration provenance and two reproducible saved-workflow artifact SHA-256 hashes. Both outcomes are distinct from a verified coral surface measurement. The exact-head backend CI regression must pass before either case is considered accepted.

**Enclosed-volume cancellation stress reference (1.4, November 20, 2026):** A synthetic, closed oriented tetrahedron with source vertices (0, 0, 0), (-1e8, -1e8, 1e8), (-100000000.00000001, -1e8, 1e8), and (-1e8, -99999999.99999999, 1e8) has an analytically nonzero unsigned enclosed volume of approximately 3.7007434154171883e-9 source units³, even though the binary64 face-by-face tetrahedral sum can cancel to zero. The provisional volume kernel now falls back to exact rational arithmetic on the **zero-result path only** and retains a representable nonzero result instead of falsely assigning no volume. The regression checks reversed winding, an exactly planar zero-volume control, the standalone endpoint, and two executions of the same persisted typed graph with matching entire artifact payloads, SHA-256 hashes, and unverified calibration/specimen identity. This is a numerical geometry contract, not coral tissue-volume validation; do not claim scientific acceptance until final-head CI passes.

**Positive-volume underflow guard (1.4, November 20, 2026):** A synthetic closed tetrahedron with orthogonal source edges of `1e-110` has a strictly positive *exact* source-coordinate volume (`Fraction(edge)**3/6`), but that value is below binary64's minimum positive subnormal. The measurement kernel now rejects this unrepresentable positive volume with a controlled scientific-input error instead of reporting a physically false zero. Regression controls require both windings to reject, an exactly coplanar zero-volume source to remain zero, and a `1e-100` edge tetrahedron with representable volume to remain measurable. The standalone preview must return HTTP 400 and two executions of a persisted typed Workflow Builder graph must fail without a `mesh_measurement_preview` artifact. This is synthetic numerical integrity only, not independent calibration, coral identity, mesh completeness, or biological volume verification. The final-head CI result remains a separate required release gate.

**Representable near-underflow volume control (1.4, November 20, 2026):** Unlike a `1e-110`-edge tetrahedron whose exact volume is unrepresentable and must be rejected, a closed tetrahedron with three orthogonal `1e-103`-unit edges has a positive, binary64-**subnormal but representable** source-coordinate volume of approximately `1.6666666666667e-310` units³ (below the minimum normal value of `2.2250738585072014e-308`). Test both consistent face windings, direct evaluation, standalone HTTP 200, and **two executions of a persisted typed Workflow Builder graph**. Require positive whole-mesh and per-patch volume, nonmissing scale-only volume interval, entire artifact payload equality, equal SHA-256 payload hashes, and explicit unverified calibration/specimen identity. This protects acceptance of legitimate finite subnormal measurements without claiming biologically credible geometry. Treat the results as synthetic regression evidence only until exact-head CI completes; no human-verified identity, real coral volume, or calibrated field reconstruction is established.

**Source-unit underflow versus calibrated recovery (1.4, November 20, 2026):** A closed synthetic tetrahedron with `1e-110` source-unit orthogonal edges has a strictly positive source volume below binary64 resolution. With a 1 m/unit scale, direct calculation and standalone/persisted preview must reject it rather than publish an apparently absent or zero scientific measurement. A caller-provided 1,000,000 m/unit scale, however, makes the calibrated volume approximately `1.6666666667e-313 m³`, which is positive and representable. The standalone scientific preview must recover it from scaled coordinates with `enclosed_volume_source_unit_numeric_recovery` QC, positive patch/whole-mesh volumes, and a nonmissing scale-only interval; two executions of the **same saved typed graph** must match the full standalone payload and SHA-256 hashes. Test both face orientations. This is a numeric provenance safeguard, not verified calibration or physically plausible coral tissue volume. The recovery must not silently convert a still-unrepresentable positive volume into zero or a routine missing result; exact-head backend CI and expert validation remain required.

For every relevant analysis, exercise (a) the standalone endpoint, (b) the typed Workflow Builder node, and (c) a persisted graph loaded and executed again after a fresh process start. Compare output payloads and provenance hashes, including negative/error paths. A graph planner accepting a node is **not** sufficient evidence of executable parity.

## Deterministic 1.4 reference fixtures and negative controls

Use independent reference calculations, not ReefVision's own output, as the oracle. Fixture generation must be deterministic, local, versioned, and hash-logged. Preserve source coordinates and calibration separately; never silently rescale imported geometry.

| Fixture | Independent expected value | Required negative control |
| --- | --- | --- |
| Closed cube with side 2 coordinate units and a declared 0.01 m/unit calibration | Surface area = 0.0024 m²; axis-aligned extents = 0.02 m on each axis; diagonal = sqrt(3) × 0.02 m. The 12 triangles must not be counted as 12 independent surface patches. | Omit calibration: reject metric claims or mark them explicitly uncalibrated. |
| One planar 3–4–5 right triangle, with 1 m/unit calibration | Area = 6 m²; no enclosed volume. | Duplicate the triangle with opposite winding: flag overlapping/ambiguous surface rather than claiming validated coral tissue area. |
| Two disconnected planar triangles, each with area 6 coordinate-units² | Total surface area = 12 coordinate-units²; two edge-connected components, assuming no shared vertices or edges. | Join them at a single vertex only: do not silently treat vertex contact as an edge-connected patch. |
| Two observations with identical source geometry and scale, one hour apart | Zero geometric area change and elapsed time = 1/24 day after UTC normalization. | Give observations different specimen identifiers without verified reidentification: no verified biological growth claim. |
| Rigidly translated/rotated cube with known 4×4 transform | Surface area invariant; aligned coordinate positions recover the reference within declared numeric tolerance. | Reflection, non-rigid scaling, singular transform and changed source hash must not be accepted as verified rigid registration. |

For uncertainty acceptance, supply an explicit positive scale interval `[s_min, s_max]` and independently compute the surface-area interval using `A_raw × s_min²` and `A_raw × s_max²`. This is **scale-only** uncertainty: it excludes segmentation, registration, occlusion, mesh reconstruction and biological sampling errors. A malformed interval, a nominal measurement outside its interval, or an interval attached to an absent nominal measurement must be rejected; absent legacy uncertainty must remain unknown, not zero.

For each fixture, capture the input file SHA-256, calibration source and units, source and target observation IDs, code commit, numeric tolerance, standalone response, typed node response, serialized workflow definition, fresh-process replay response, saved artifact hash, and reviewer disposition. Run the negative control through all three execution paths and assert equivalent failure classifications; compare scientifically meaningful fields rather than volatile database IDs or timestamps. Keep automatic QC and provisional identity separate from human verification.

## 1.5: experimental and field science

Before implementing or claiming acceptance, define independent experimental units, randomization blocks, repeated measures, missingness, covariates and planned contrasts. Reject pseudoreplication (for example, treating multiple fragments sharing a treatment tank as independent tank replicates). Verify ICC model, rater structure and single-versus-mean estimands; Bland–Altman bias and limits of agreement must identify paired units and repeated-measure assumptions. Check multiplicity and model diagnostics, report effect sizes and uncertainty, and include power/sensitivity simulations under explicitly stated assumptions.

For field inference, mosaics, drift checks, plugins, multimodal fusion, surveys, scientific figures and reusable study packages, require offline reproducibility, typed persisted workflow replay, data/source licensing, reviewer signoff and deterministic failure behavior. A model prediction or automated QC result must never silently become human-verified evidence.

## Release gate and evidence ledger

Record for each gate: commit SHA; fixture and model hashes; exact-head Actions run URL; backend, frontend, migration, E2E and scientific results; Windows MSI/CAB packaging outcome; **installed** GUI/GPU observations; reviewer and date; outstanding limitations. Passing CI or producing an installer is not equivalent to installing and testing it. Until every applicable gate has actual evidence, keep both versions marked **HOLD**. Never promote local user-trained checkpoints, calibration evidence or provisional biological identities into a release automatically.

**Imported source filename surrogate integrity (1.4, November 20, 2026):** Preserve imported OBJ/PLY/GLB source filenames as portable, valid Unicode scalar sequences. Reject lone high and low UTF-16 surrogates before import, and revalidate original filename metadata before source-byte retrieval. Reject unpaired surrogates at the service import boundary before SQLite persistence (SQLite itself cannot UTF-8 encode these code points). Existing tampered-but-storable original filename metadata must still fail standalone measurement and persisted typed Workflow Builder replay without a measurement artifact. The direct import regression covers both surrogate classes and guarantees no imported asset row; a separate non-BMP original filename control must import successfully and replay an asset-bound mesh measurement through a saved workflow with unverified calibration and source SHA-256 preserved. This is a provenance-integrity regression, not evidence of human-verified coral identity or calibrated geometry. The preceding volume-regression Ruff format discrepancy is corrected; exact-head Actions must still establish CI acceptance.

**Large source-coordinate translation volume fixture (1.4, November 20, 2026):** A unit-edge, closed synthetic tetrahedron translated to a coordinate origin of (100,000,000, 100,000,000, 100,000,000) source units retains the same oriented signed volume, ±1/6 source units³, under both consistent face windings. With caller-supplied 0.01 m/source-unit scale, its unsigned enclosed volume remains 0.01³/6 m³, independent of translation. The new regression requires direct-kernel and measurement-engine parity, standalone preview success, and twice-executed persisted typed Workflow Builder results matching the complete standalone artifact with identical SHA-256 hashes. The source coordinates are deliberately artificial: this establishes translation-invariance/numeric-integrity only, not georeferencing, independently verified calibration, enclosed coral tissue volume, or specimen reidentification. The expanded synthetic regression tests **six** winding/source-frame combinations: positive-origin unchanged coordinates, negative-origin single-axis reflection, and mixed-sign origin double-axis reflection, each with inward/outward face winding. The determinant sign must follow frame handedness while **unsigned** volume, calibrated axis-aligned dimensions (0.01 m each), and cubic scale-only uncertainty bounds remain invariant through direct computation, standalone API, and twice-executed persisted typed Workflow Builder graph. This tests coordinate-frame numerical integrity, not externally verified spatial registration or specimen identity. The immediately preceding exact-head CI had 20 successful and three Ruff-format failures; the new regression also corrects Ruff's required single-line assertions. Final-head backend CI and installed Windows acceptance must pass before treating the fixture as accepted.

**Exact enclosed-volume recovery: strict typing and face-origin invariance (1.4, November 20, 2026):** The floating-point tetrahedron vectors and the fallback `Fraction` vectors must use distinct local variable names and preserve a rational accumulator; otherwise the exact recovery path fails strict mypy even when Ruff passes. The existing nonzero synthetic cancellation fixture now checks all four rotations of the face list (each selecting a potentially different first-face origin) and both consistent face windings. Expected signed volume is ±`1e8 × (2**-26)**2 / 6` source units³, with the sign controlled only by winding. The same test also verifies the standalone API and two persisted typed Workflow Builder executions produce identical provisional artifacts and SHA-256 hashes, without claiming verified specimen identity or calibration. These changes address the four mypy errors reported by the preceding exact-head backend, pose, and 1.0 acceptance workflows; rerun those gates on the **new commit** before declaring the repair confirmed. This is a synthetic numerical-integrity and compilation regression, not field or biological validation.

**Ill-conditioned nonzero enclosed-volume integrity (1.4, November 20, 2026):** A floating-point determinant may be **nonzero yet wrong** when large opposing cross-product or dot-product terms nearly cancel. Do not restrict exact `Fraction` source-coordinate recovery to an already rounded zero; also inspect near-roundoff cancellation in the per-face cross and dot products, and return exact zero when the source-coordinates' rational result is exactly zero. The regression selects all **four distinct tetrahedron vertices** as the first-face source origin (by cycling vertex order without reversing orientation), in both winding directions. It checks signed ±`1e8 × (2**-26)**2 / 6` source units³ with zero absolute tolerance. One previously erroneous case produced `4.967053731282552e-9` rather than `3.7007434154171883e-9` source units³. That case must pass direct kernel, standalone mesh-preview API and two persisted typed Workflow Builder graph executions with identical provisional artifact hashes. Numerical results do not establish real-coral completeness, calibration or identity. Exact-head backend/pose/scientific and installed Windows acceptance remain required.


**Concave closed-mesh analytic fixture (1.4, November 20, 2026):** Extend the enclosed-volume reference beyond tetrahedra to a deeply concave, edge-connected U-shaped synthetic prism. The 28 oriented triangles form six top triangles, six bottom triangles and sixteen wall triangles; each of the 42 undirected edges has two oppositely oriented face incidences. For length L = 100,000,000 source units, arm thickness t = 1 and height h = 1,000, the independently derived section area is (3Lt - 2t²) = 299,999,998 source units², enclosed volume is (3Lt - 2t²)h = 299,999,998,000 source units³, perimeter is (6L - 2t), and closed surface area is 2(3Lt - 2t²) + (6L - 2t)h = 600,599,997,996 source units². Under a **caller-provided, unverified** 0.01 m/source-unit calibration, both surface area and unsigned volume must match these analytic values after quadratic/cubic scaling, along with a scale-only uncertainty interval. The reference reverses all face windings separately and chooses a first-face origin at the edge of the deep notch to expose determinant cancellation; a naive floating-point tetrahedral sum can differ materially from the analytic volume. Require direct-kernel, standalone HTTP 200, twice-executed persisted typed Workflow Builder parity, complete artifact equality, stable SHA-256, and explicitly unverified specimen/calibration flags. This is a deliberately nonbiological numerical stress fixture: it provides no evidence of real coral topology, watertight reconstruction quality, independently calibrated scale, or human-verified identity. Exact-head CI and installed Windows/GPU validation remain separate release HOLD gates.

**Concave mesh coordinate-frame invariance (1.4, November 20, 2026; regression pending exact-head CI):** The analytic 28-triangle U-prism fixture now also runs in a translated, single-axis-reflected coordinate frame, for both consistent face-winding directions. Signed source-unit volume must flip sign under either reflection or winding reversal but preserve its analytical magnitude; metric unsigned volume, surface area, calibrated axis extents and the cubic/quadratic caller-supplied scale-only uncertainty bounds must remain invariant. Each parameterized case checks the direct kernel, standalone endpoint, and two executions of an independently saved typed Workflow Builder graph, requiring complete payload parity and deterministic SHA-256 hashes with unverified calibration/specimen provenance. This tests geometric frame consistency and reproducibility only; translation/reflection is not a validated registration, real-coral reconstruction, or biological reidentification. Ruff-format cleanup was included; do not mark this gate passing without the resulting exact-head CI and human acceptance evidence.


**Patch-preserving bounded mesh display (1.4, November 20, 2026; exact-head CI pending):** The optional strict boolean `preserve_edge_connected_patches_in_preview` prioritizes one largest-area triangle from each edge-connected surface patch before filling the fixed 512-face display budget. Patches are prioritized by their *full reconstructed mesh area*, then first source-face index; the existing axis-extrema/dominant-face option can be combined with this policy. Preserve the original full-mesh source hashes, topology, calibrated area/dimensions, uncertainty and provisional identity; sampling is only a render choice. For a synthetic 514-face mesh with a low-area disconnected component hidden at face 256 under otherwise extrema-aware uniform sampling, require the component to appear in the patch-preserving preview without altering any scientific result. Confirm strict request typing and standalone API versus twice-executed persisted typed Workflow Builder artifact/hash parity. When the number of patches exceeds the display budget, keep explicit omitted-patch QC rather than claiming the preview shows all reconstructed surfaces. This provides no claim of tissue completeness, anatomical branch identity, verified calibration or biological validation.

**Patch-budget scientific-display ranking (1.4, November 21, 2026; exact-head CI pending):** In patch-only preview mode, never reserve the first and last source faces just because of their file order; when 513 disconnected patches compete for 512 display slots, select representatives of the 512 largest full-mesh area patches and report the remaining omitted patch. With the combined axis-extrema-and-patch mode, reserve extreme source-coordinate faces first, then prioritize available patches by reconstructed area; this explicit tradeoff may exclude a larger patch than patch-only sampling and must retain the omission QC. Synthetic tests exercise 511 equal large-area interior triangles versus two low-area endpoint triangles, scientific measurement/source-hash invariance, standalone HTTP preview and two executions of a persisted typed Workflow Builder graph with complete artifact and SHA-256 parity. Render coverage is not tissue completeness, verified physical calibration, biological condition or specimen identity. Human inspection and installed Windows acceptance remain separate required gates.


**Largest scan-gap endpoint visibility (1.4, November 21, 2026; awaiting exact-head CI):** A bounded 512-point display can omit an endpoint of the full-source largest adjacent **axis-projected sampling gap** even while displaying all source-coordinate extrema. The point-cloud scientific engine now emits `preview_largest_axis_gap_endpoint_support` (per-axis lower/upper visibility, or null for a constant axis), `preview_omitted_largest_gap_boundary_axes`, and `preview_omits_largest_axis_gap_endpoint` when appropriate. These are preview-only QC diagnostics. They never alter the full source-cloud gap, calibrated extents, source geometry hashes, provisional specimen identity, or scientific calibration evidence. A 600-row synthetic cloud makes index 6 invisible under uniform 512-point sampling while the unique largest x gap between indices 6 and 7 remains measured as 101 source units and both x extrema stay displayed. Test direct/standalone results and twice-executed persisted typed Workflow Builder replay with complete artifact and SHA-256 parity for XYZ and imported ASCII PLY. An omitted displayed boundary is **not** evidence of missing tissue, verified scan coverage, anatomical branch length, biological condition, or registration. Track C release HOLD persists until exact-head backend/frontend/E2E/migrations, independent biological validation, installed Windows MSI/CAB GUI and real GPU gates pass.

**All tied maximum scan-gap boundaries in bounded point-cloud displays (1.4, November 21, 2026; CI pending):** The previously exposed `preview_largest_axis_gap_endpoint_support` remains the visibility of the representative lowest-coordinate largest-gap interval only. When two or more adjacent **source-axis coordinate** intervals have the same maximum width, that representative may be fully displayed while another tied interval loses one or both endpoints to 512-point decimation. New `preview_largest_axis_gap_interval_coverage` reports for each nonconstant axis `total_intervals`, `fully_displayed_intervals`, `partially_displayed_intervals`, and `hidden_intervals`, counting *all* exactly tied maximum gaps using distinct coordinate levels, not duplicated acquisition rows. `preview_omitted_largest_gap_boundary_axes` and the existing `preview_omits_largest_axis_gap_endpoint` warning now cover **any** omitted tied maximum interval, not only the representative pair. Constant axes return null coverage. Test a 600-row cloud whose two 101-unit maximal x gaps are respectively displayed at indices 7/8 and partly hidden at indices 299/300. Require standalone XYZ/ASCII PLY HTTP results and two executions of each persisted typed Workflow Builder graph to reproduce the same complete artifact and SHA-256. Full source geometry, uncertainties, calibration provenance and specimen status must not change. This is visualization sampling QC, **not** proof of absent coral tissue, acquisition completeness, 3D surface coverage, independently calibrated length, or verified identity. Exact-head CI, independent biological review, installed Windows MSI/CAB GUI and physical GPU verification remain release HOLD gates.
