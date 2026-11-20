# ReefVision 1.4.0 acceptance report

Report date: 2026-11-15

## Release status

ReefVision 1.4 is **not release-complete**. The integrated candidate has a
verified source and packaging foundation for bounded 3D assets, deterministic
geometric measurements, migration reconciliation, Project Exchange, and the
normal user-facing discovery path. Scientific claims that require representative
specimens, independent references, reviewer authority, or preregistered
thresholds remain blocked and are listed separately below.

This report does not authorize merging to `main`, tagging, or publishing. The
published 1.0.3 release assets remain unchanged.

## Feature-by-feature result

The canonical status and evidence record is
`docs/roadmap/REEFVISION_2_0_FEATURE_INVENTORY.json`; the generated Markdown
inventory must agree with it. A broad 1.4 gate cannot close an individual entry.

| Feature | Result | Boundary |
| --- | --- | --- |
| Bounded OBJ/PLY/GLB mesh and point-cloud preview | Verified | Bounded parsing, QC, warnings, and contextual Workflow Builder discovery are tested. |
| Persistent versioned 3D project assets | Verified | Original bytes, UUID/hash binding, append-only metadata and review history, background parsing, exchange, and tamper rejection are covered. |
| Reviewed geometric measurements | Verified on deterministic synthetic geometry | Extents, dimensions, area, paths, topology/QC, uncertainty, and conditional volume are covered; no biological interpretation is implied. |
| Reviewed registration transforms | Blocked | Requires representative paired scans, independent control correspondences and scale evidence, reviewer/adjudicator authority, and preregistered residual/alignment thresholds. |
| Reviewed 3D organism matching | Blocked | Requires repeated scans with independent identity labels, reviewer/adjudicator roles, an ambiguity protocol, and preregistered false/missed-match thresholds. |
| Longitudinal 3D change | Blocked | Requires the blocked registration and organism-correspondence evidence plus preregistered longitudinal error and repeatability thresholds. |
| Anatomical coral branch length | Blocked | Requires an approved endpoint/centerline rubric, independent reference branches, repeatability evidence, thresholds, and an adjudicator. A generic surface path is not an anatomical branch length. |
| Biological-condition measurements | Blocked | Requires an approved rubric and observation unit, representative labeled specimens, independent review, adjudication, and reliability/accuracy thresholds. Geometry and confidence are not condition labels. |
| 1.3 → 1.4 lineage, upgrade, exchange, and rollback | Source verified; installed lineage matrix blocked | Fresh/current migration and published 1.0.3 upgrade evidence pass. Representative 1.3 and legacy draft-1.4 profiles are still required for the complete installed lineage matrix. |
| Representative 3D field validation | Blocked | Requires the authorized scan corpus, independent references/repeats/labels, target Windows/GPU configurations, and evidence destinations named in the inventory. |

3D specimen correspondence is separate from appearance-based ReefPose
re-identification across long gaps or videos. The latter remains its own 2.0
inventory entry.

### Declared ASCII PLY numeric-width integrity

Mesh and point-cloud ASCII PLY imports now check each declared `float` or
`float32` coordinate against its actual IEEE-754 binary32 range. A finite
decimal that would overflow binary32 or round a nonzero coordinate to zero is
rejected before any scientific measurement or saved-workflow artifact can
succeed. The `double`/`float64` declarations retain binary64 parsing;
representable float32 subnormals and ordinary decimal rounding remain
permitted. Extra numeric mesh vertex properties obey their declared width.
Original PLY text remains bound in source provenance: passing this range check
does not certify source authenticity, camera calibration, specimen identity,
reconstruction error, or biological surface area. Synthetic import, standalone
API, and twice-executed typed saved Workflow Builder regressions cover these
boundaries for both geometry families. Full CI and representative field review
remain separate release gates.

### ASCII PLY source-decimal collision and schema-order QC

A distinct ASCII source decimal may round to the same binary64 coordinate
as a different vertex value. Mesh and point-cloud previews reject this
ambiguity rather than calculate false zero extents, degenerate topology,
or calibrated surface measurements from collapsed source locations.
Equivalent decimal spellings remain permitted. A synthetic mesh regression
also checks a leading non-coordinate color field and nonstandard Z/X/Y
property order: precision collisions on each actual coordinate axis must
fail through direct parsing, the standalone project API, and a saved,
executable typed Workflow Builder graph without a measurement artifact.
The CI gate for this new fixture is not yet established; source text,
calibration, organism identity, geometry registration, and reconstruction
remain independently unverified until the scientific acceptance gates pass.

### Bounded mesh-preview surface visibility QC

A decimated preview can omit a complete edge-connected mesh patch even when
the original geometry is retained for measurements. The report exposes the
fraction of reconstructed source-mesh area in fully omitted patches, its
calibrated area in square meters, and a scale-only uncertainty interval where
the caller supplies relative scale uncertainty. The interval squares the
common scale bounds; it does not account for segmentation, reconstruction,
registration, or biological tissue uncertainty. A nonrepresentably small
omitted area is withheld rather than reported as exactly zero. Standalone
API and twice-run, persisted typed Workflow Builder regression checks use a
synthetic hidden large patch, with zero omission and degenerate-area controls.
The preview must never be used to infer coral condition or tissue coverage.

### Compensated per-patch area reconciliation

The complete reconstructed mesh already accumulates triangle surface areas
with compensated summation. Each edge-connected patch now uses the same
reduction instead of repeatedly adding small faces to a much larger running
total. Without this, many sub-ULP positive triangles sharing a patch could
disappear from its reported area even while remaining in the full-mesh total,
making per-patch area fractions and bounded-preview coverage inconsistent.

A synthetic dominant-face-plus-300-sliver fixture verifies exact reconciliation
of the full-mesh area and its sole patch area, complete preview area coverage,
and intentional nonmanifold-edge QC. Standalone API execution and two runs of
a typed persisted Workflow Builder graph must agree on values, unverified
calibration provenance, and stable artifact hashes. This improves arithmetic
integrity, not reconstruction accuracy, organism identity, tissue area,
anatomical branch length, or uncertainty beyond supplied scale error.


### Compensated area-weighted mesh surface centroids

Both per-patch and complete-mesh reconstructed surface centroids now reduce
signed triangle area moments using compensated summation. A dominant face
previously could discard many individually sub-ULP but collectively
representable face contributions, shifting the reported centroid even when
complete and per-patch surface areas reconciled correctly. The same
300-sliver synthetic nonmanifold fixture tests an independently computed
reference centroid and verifies direct, standalone API and twice-run typed,
persisted Workflow Builder artifact parity and provisional provenance.
These centroids are in the imported, unregistered source coordinate frame;
they do not imply coral identity, registration, tissue localization or
positioning accuracy beyond the caller-supplied common scale.

### Signed source-coordinate cancellation in mesh centroids

Even after compensated reduction of triangle moments, an ordinary sum of three
signed source-vertex coordinates could erase a small representable coordinate
when combined with opposing coordinates near the mesh's supported bounds.
Per-face centroid moments now use compensated summation of the three
coordinates before area weighting. A synthetic triangular mesh with x
coordinates +1e9, +1e-8 and -1e9 verifies preservation of the small positive
surface-centroid contribution, together with standalone project API parity and
two persisted typed Workflow Builder executions. Assertions retain provisional
calibration status, source provenance and stable scientific artifact hashes.
This is floating-point arithmetic QC, not registration, tissue localization,
biological identity or independently established coordinate accuracy.

### Compensated disconnected-patch boundary perimeter

Patch boundary-edge lengths and the total calibrated boundary perimeter now
use compensated summation. Ordinary accumulation could discard small positive
boundary contributions when a source mesh contains one large reconstructed
surface patch and many tiny disconnected patches. This is a geometry-derived
boundary metric, not a coral anatomical branch length or tissue perimeter.

A synthetic 301-patch case (one dominant triangle and 300 sub-ULP tiny
triangles) verifies that calibrated boundary length includes representable
small-patch contributions and exactly reconciles with the compensated sum of
per-patch lengths. The standalone project API and two executions of a persisted,
typed Workflow Builder graph must match the same values, scale-only uncertainty
intervals, provisional calibration provenance and stable artifact hashes.
Scientific validation against real reconstruction and anatomy references remains
blocked.

### Partially visible patch coverage

The bounded preview now distinguishes completely hidden edge-connected mesh
patches from patches represented by some, but not all, source faces. It reports
`preview_partially_sampled_patch_indices` and the unitless
`preview_partially_sampled_patch_missing_area_fraction`. For any mesh with
positive area, displayed area, wholly omitted-patch area, and missing area
within partially represented patches should sum to the complete reconstructed
mesh area fraction (1). Direct scientific measurement, standalone project API,
and twice-executed persisted typed Workflow Builder tests check this
decomposition and artifact parity. Zero-area meshes report an undefined area
fraction, not a biological coverage estimate. Neither preview sampling nor the
relative area fraction validates specimen completeness.

### Rendered bounds versus source extrema

A bounded triangle sample may retain a connected surface patch while omitting
the face containing a reconstructed extremum (for example a narrow tip).
`preview_displayed_bounds_in_source_frame_m` now describes only vertices
actually submitted to the renderer, independently of the existing
`preview_referenced_bounds_in_source_frame_m` used to fit the camera to all
source faces. `preview_omitted_axis_extremum_sides` identifies any of the six
source-axis minimum/maximum sides not represented in the rendered sample, and
`preview_omits_source_axis_extrema` warns explicitly. Extrema are compared in
original coordinates before calibration to avoid false equality under extreme
scales. A synthetic 514-face connected mesh with an unsampled tall flap is
exercised through direct measurement, standalone API, and twice-executed
persisted typed Workflow Builder graphs. A follow-up scientific regression
distinguishes the measurement kernel's calibration provenance from the
standalone API's additional source and observation audit fields. It asserts
that the extra fields remain explicitly unverified or absent when callers
supply no independent evidence, while two persisted workflow executions
match the complete standalone API provenance and artifact hashes. The result
is display fidelity QC, not biological branch presence/absence, verified
anatomy, or scale accuracy.

## User-facing entry point

A new user reaches the 1.4 tools through:

1. Home → create or open a project.
2. Video & automation → Workflow builder.
3. Project-owned 3D originals → Import 3D original.
4. Select the project source, then use mesh or point-cloud preview and the
   relevant scientific node's contextual controls.

The packaged 1.4.0 application was launched with an isolated data root and this
path was exercised. The project-owned import and preview controls were present,
and the node registry exposed 3D Mesh Surface Preview, 3D Point Cloud Preview,
and 3D Mesh Longitudinal Comparison (Provisional). The UI explicitly warns that
the asset is not calibrated, a generic chord/path is not anatomical branch
length, and preview output is not a biological condition or verified
registration result. No top-level 3D tab was added; advanced controls remain in
the relevant Workflow Builder workspace.

## Migrations

The validated 1.3 and aliased draft-spatial histories merge at
`b14_integration_0001`. The single current head is `b14_spatial_0040`, which adds
append-only spatial asset metadata revisions. The legacy numeric `0038`/`0039`
migration bodies are preserved byte-for-byte under `legacy_spatial`; applied
migrations were not edited.

Verified migration paths include:

- fresh database → `b14_spatial_0040`;
- `b13_temporal_0001` → current head;
- proven legacy draft-spatial numeric `0038` and `0039` → current head;
- current head → `b14_integration_0001` → current head;
- rejection without mutation for ambiguous, mixed, incomplete, unknown, and
  future schema fingerprints.

See `docs/roadmap/REEFVISION_1_4_MIGRATION_RECONCILIATION.md` for the graph and
lineage invariants.

## Automated verification

Source verification for the candidate includes:

- Ruff lint and Ruff format across the backend: passed.
- mypy across 636 source files: passed.
- release inventory validation: 76 entries; 22 inventory tests passed.
- frontend format and type checks: passed.
- frontend unit tests: 124 files, 717 tests passed.
- Playwright: 14 passed; 18 live-environment checks skipped by their declared
  opt-in requirements.
- production frontend build: passed, with the existing bundle-size advisory.
- release metadata: 11 public version sources agree on 1.4.0.
- Windows harness preflight regressions: 69 passed.
- Alembic fresh upgrade, downgrade to `b14_integration_0001`, and re-upgrade to
  `b14_spatial_0040`: passed with one head.

The exact final backend and GitHub CI counts are recorded in the final PR #79
evidence update because the evidence SHA is produced after this report is
committed.

## Windows installer evidence

GitHub Actions run
`https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/43792901192`
built and verified the 1.4.0 MSI from source commit
`330bd56fddf66a9dd135b5e493c7f9e9a382be4f` and passed:

- exact source/version/provenance and MSI Media/payload digest verification;
- disposable Windows clean install without developer runtimes on `PATH`;
- first launch, frontend/backend connectivity, schema migration, project
  persistence and restart;
- Project Exchange round trip;
- uninstall with user-data retention;
- published 1.0.3 → 1.4.0 upgrade, persistence, exchange, uninstall, and
  retention.

The MSI SHA-256 is
`526e96386fc831dcef65b2bed8767746002b6f16822655003f64fd75efdf4f6c`.
Its ProductVersion is 1.4.0, ProductCode is
`{A60356E7-2A23-48DE-A2DD-0BCAB0D5BA2B}`, and UpgradeCode is
`{5EDA8EE0-2A5D-5B08-A8DF-9BECFC3A4351}`. Every external CAB digest was
verified.

The same packaged executable was also inspected locally from an administrative
MSI extraction under an isolated profile. A true local MSI install was not run
because this Codex Windows session is not elevated; the disposable GitHub
Windows jobs provide the true installed evidence. Representative 1.3 and legacy
draft-1.4 profile upgrades remain open.

## Synthetic, installed, and representative evidence

- **Synthetic/source:** deterministic geometry, scaling, topology, conditional
  volume, uncertainty propagation, registration/correspondence binding,
  longitudinal withholding, immutable storage, exchange, and tamper rejection.
- **Installed Windows:** clean 1.4.0 install and published 1.0.3 upgrade passed;
  packaged user-path discovery was exercised separately under an isolated
  profile.
- **Representative/physical:** not run. No authorized representative scan
  corpus, independent references/identity/condition labels, reviewer authority,
  preregistered thresholds, or target-hardware evidence destination was
  available.

## Files and contracts changed in 1.4

The integrated branch changes backend spatial source, metadata, parse,
measurement, registration, correspondence, longitudinal, Project Exchange, and
migration code; Workflow Builder controls and previews; release metadata and
Windows packaging; tests; and the release-accountability inventory and reports.
The final PR diff is the authoritative file list.

No original media is modified. Spatial originals remain project-owned immutable
bytes, canonical identifiers are UUIDs, integrity failures are structured and
fail closed, and no provisional output is silently promoted to verified
annotation, calibration, anatomy, identity, growth, or condition evidence.

## Known limitations and specification deviations

- Representative registration, matching, longitudinal, anatomical branch
  length, condition, and physical-hardware acceptance are blocked as listed in
  the canonical inventory.
- Point-cloud scale-only dimension, selected-chord and signed-coordinate intervals
  are unresolved when nonzero uncertainty rounds distinct bounds to one float.
  This is not evidence of exact scale, physical calibration or confidence limits.
- Decimated 3D mesh previews now report how many source faces from each
  edge-connected reconstruction patch remain visible, per-patch fractions
  of full reconstructed patch area represented, and indices of patches omitted
  entirely from the display. The omitted-patch area fraction reports the
  proportion of the complete reconstructed area belonging to fully hidden
  patches, separating patch loss from ordinary within-patch face decimation.
  Within partially visible patches, the direct sum of the hidden faces also
  reports provisional calibrated missing area in m² and a scale-only interval
  when an uncertainty was supplied. Positive raw missing area that would
  underflow to zero under calibration is withheld as null, not falsely reported
  as zero; visualization loss is never equivalent to absent coral tissue.
  A distinct warning marks omissions; a zero-area
  patch has undefined area coverage rather than invented certainty. A separate
  `preview_omits_reconstructed_mesh_surface_area` warning now flags any positive
  source-triangle area omitted by bounded display sampling, including loss
  within a still-visible single connected patch. The displayed area sum uses
  compensated summation. Neither warning implies a biological tissue loss. All
  scientific surface-area/topology measurements still use the complete mesh.
  These are visualization diagnostics, not evidence of coral colony identity,
  tissue coverage, anatomical branch structure, or independently verified
  physical calibration. Standalone and persisted-graph regression coverage is
  under exact-head CI review, not physical/biological field acceptance.
- Point-cloud axis extrema now report their supporting source-row counts and
  distinct XYZ-locus counts separately for each minimum and maximum face.
  Duplicating acquisition rows raises row support without increasing independent
  coordinate-locus support. These are descriptive quality-control counts,
  neither statistical uncertainty nor evidence of real tissue boundaries.
- A point-cloud preview now carries a SHA-256 of its exact sampled source-row
  indices and normalized, unscaled XYZ positions. Changing which rows are
  displayed can change this digest without changing the complete source cloud.
  This is visualization provenance, not source-byte authentication, verified
  biological identity, registration, surface area, or branch-length evidence.
- The complete installed 1.3/legacy-draft-1.4 lineage matrix is not available.
- Local true installation was blocked by the non-elevated session; remote
  disposable Windows installation passed.
- No 1.4 release-complete claim is made. No merge, tag, or publication was
  performed.

## Track C: signed-centroid identity provenance regression (2026-11-17)

Synthetic centroid acceptance now binds caller-supplied specimen, observation,
UTC timepoint and coordinate-frame labels through the standalone project API
and two executions of a persisted typed Workflow Builder graph. Both paths
must preserve the labels while retaining explicit false values for specimen
identity, observation-metadata and coordinate-registration verification. A
separate face-winding regression distinguishes source fingerprint changes from
winding-invariant reconstructed geometry/centroids. Neither test independently
verifies anatomy, organism identity, source acquisition or field calibration.
The exact-head CI outcome must be checked after this report is committed.


## Track C: calibrated mesh-area interval precision (2026-11-19)

An extremely small but positive calibrated surface area can remain
representable in IEEE-754 binary64 while the positive lower bound of its
scale-only uncertainty interval underflows to zero. For
`relative_scale_uncertainty < 1`, ReefVision now retains the nominal
provisional area but withholds the unrepresentable interval as `null`
rather than reporting zero as an observed lower limit. The
`surface_area_scale_interval_numeric_unrepresentable` QC warning
identifies the loss. At exactly 100% scale uncertainty, a zero lower bound
is mathematically valid; a genuinely zero-area degenerate triangle also
retains a valid zero interval. Unknown uncertainty never fabricates bounds.

The safeguard is shared by global and edge-connected-patch calibrated
surface areas and by the displayed-preview omitted/partially sampled area
intervals. A valid larger-patch interval is preserved if a separate tiny
patch's lower limit is unrepresentable. All these results remain unverified,
scale-only geometric measurements, not confidence intervals, biological
condition, branch-length validation, or evidence of independent calibration.

A synthetic subnormal-area regression covers standalone API measurements,
typed executable Workflow Builder planning and persisted execution twice,
artifact equality and repeatable SHA-256 hashes, while preserving unverified
specimen and coordinate-frame provenance. Until the exact-head CI results
and external representative coral/Windows/GPU review are available, 1.4
remains **RELEASE HOLD**.

## Track C: hidden preview-face area below numeric precision (2026-11-19)

A bounded renderer can omit a very small positive triangle within an otherwise
large, visible edge-connected patch. The **complete mesh** can retain a valid
calibrated area while the calibrated *preview-only missing-face area* underflows
to binary64 zero. The preview now returns `null`, not a false measured zero,
for `preview_partially_sampled_patch_missing_area_m2` and adds
`preview_partially_sampled_missing_area_numeric_unrepresentable` to QC.
This flag is emitted even when scale uncertainty was not supplied. When it
was supplied, the unrepresentable omission interval also carries
`surface_area_scale_interval_numeric_unrepresentable`; an otherwise valid
whole-mesh area interval remains available.

A 513-face synthetic single-patch case (512 sampled display faces) checks the
exact omitted source face, the standalone project API, unverified calibration
and specimen/registration provenance, and two executions of a persisted,
executable typed Workflow Builder graph with matching measurement artifacts
and SHA-256 hashes. These are *numeric/display integrity* checks, not estimates
of missing coral tissue, measurement confidence, or field-validated calibration.
CI and installed Windows/GPU/representative-coral acceptance remain separate
release gates.


## Track C: preview omission with absent uncertainty (2026-11-19)

The 513-face hidden-triangle synthetic regression now also omits the
`relative_scale_uncertainty` field entirely, instead of supplying a
numerical estimate or an explicit `null`. This keeps the positive but
numerically unrepresentable display-only missing area flagged and withheld,
while prohibiting fabricated scale-only area intervals or confidence
intervals. The standalone project API and a separately persisted typed
Workflow Builder graph must agree on the omitted-uncertainty payload,
twice-replayed artifacts and deterministic hashes. Calibration and specimen
identity remain **unverified** in both paths; these checks do not establish
reconstruction accuracy or biological tissue loss. CI confirmation, external
scientific review and real Windows/GPU/representative-coral acceptance are
still required. **RELEASE HOLD**.


## Track C: mesh-edge route scale-interval precision (2026-11-19)

Mesh-edge shortest routes remain **provisional reconstruction geometry**, not
identified coral skeletal branches. Previously, a nonzero but sub-resolution
relative calibration uncertainty could round both length bounds to an
apparently exact measurement (or round a positive lower bound to zero).
The 1.4 path engine now preserves the nominal finite route, chord, geometric
excess, segment and cumulative distances, while setting only numerically
unrepresentable scale-only intervals to `null`. A
`path_scale_interval_below_numeric_resolution` QC warning requires review;
related scalar uncertainty is withheld when its interval is unresolved.
Genuinely zero geometric lengths, exact zero scale uncertainty and the
mathematically zero lower limit at 100% relative uncertainty remain distinct.

The saved-mesh artifact viewer also refuses misleading legacy exact-appearing
intervals when a nonzero calibration uncertainty is recorded, while leaving
legitimate exact and 100% uncertainty cases inspectable. Synthetic regressions
cover source-engine, standalone project API, executable typed persisted graphs
executed twice, scientific-artifact parity and reproducible hashes, plus
frontend saved-artifact inspection. These checks do not verify calibration,
coral branch anatomy, specimen identity, or physical field reconstruction.
Final-head GitHub CI, representative datasets, independent scientific review,
Windows installed-GUI and physical GPU acceptance remain release gates.
**RELEASE HOLD**.


## Track C: omitted mesh-route uncertainty and formatting gates (2026-11-19)

The standalone mesh-preview endpoint and a twice-executed persisted, typed
`mesh_surface_preview` Workflow Builder graph now have a dedicated regression
for **omitting** `relative_scale_uncertainty` entirely. The nominal provisional
route and displayed mesh geometry remain available, but no route/chord,
segment, cumulative or excess scale-only uncertainty intervals are invented.
An absent uncertainty estimate also must not trigger the
`path_scale_interval_below_numeric_resolution` warning, which is reserved for
numerical loss of an **actually supplied** nonzero uncertainty. Direct-engine,
API, planner, executed-artifact equality, repeatable SHA-256 hashes, and false
calibration/specimen/registration verification flags are covered.

The predecessor exact-head Actions run reported four failed workflows, caused
by Ruff formatting in `spatial_mesh_paths_v14.py` and Prettier formatting in
`MeshArtifactViewer.test.tsx`; the relevant workflow-graphs failure shared
the latter cause. Both formatting issues have been corrected on the isolated
1.4 branch. A subsequent exact-head Actions run must confirm them and the
new regression; no local full-suite, physical MSI/GUI/GPU or representative
coral validation is claimed. **1.4 and 1.5 remain on RELEASE HOLD.**


## Track C: calibrated surface-area bounds below numeric resolution (2026-11-19)

A strictly positive relative calibration uncertainty may be smaller than the
resolution of a nominal surface-area measurement. Previously the quadratic
scale-only area bounds could round to the *same positive value* and imply an
exact result despite nonzero uncertainty. The area interval helper now withholds
such false-exact intervals while preserving nominal mesh area and the separate
per-edge-connected-patch area. Existing
`surface_area_scale_interval_numeric_unrepresentable` QC requires review;
no statistical confidence interval or independently verified biology is inferred.

The synthetic acceptance regression adds a positive but sub-resolution
(`1e-17`) relative uncertainty to the subnormal-area fixture and checks direct
measurement, standalone API, an executable typed persisted Workflow Builder
graph executed twice, unverified provenance, equal artifacts and reproducible
SHA-256 hashes. A separate ordinary-area control checks that positive
sub-resolution uncertainty remains distinguishable from explicit zero,
missing uncertainty, and the mathematically valid zero lower bound at 100%.
The preceding head's three backend failures were Ruff formatting in the
surface-trace regression; its formatting was separately corrected.

**RELEASE HOLD:** Exact-head CI for these edits remains to be confirmed,
and representative coral datasets, independent scientific review, migrations,
installed Windows MSI/CAB/GUI and physical GPU acceptance remain outstanding.
Neither synthetic fixture validates biological branch length or calibration.


## Track C: inverse-scale A/V precision boundary and saved graph (2026-11-19)

The provisional surface-area/enclosed-volume ratio is an inverse-length
geometric descriptor, not a biological condition metric or growth estimate.
For strictly positive, sub-binary64 relative scale uncertainty, dividing by
`1 +/- uncertainty` can produce identical inverse-scale interval endpoints;
those falsely exact bounds are now withheld and the
`surface_volume_ratio_scale_interval_numeric_unrepresentable` QC warning is
attached when a finite provisional global or per-patch ratio exists. Unknown
uncertainty does not invent bounds or QC. At 100% scale uncertainty, a finite
upper A/V bound is mathematically unavailable and does **not** trigger the
numeric-resolution warning. Zero uncertainty retains an exact interval.

The existing synthetic closed-tetrahedron test additionally covers direct
measurement, standalone API and two executable typed persisted Workflow Builder
runs with equal scientific payloads and SHA-256 artifact hashes. Its direct
engine fixture was corrected to omit request-level specimen/coordinate fields
(which are attached only by `preview_from_request`); only API and workflow
artifacts assert those unverified provenance fields. This is **synthetic
regression coverage**, not validated coral data or independently verified
calibration, segmentation, or specimen identity.

**RELEASE HOLD:** This head still requires complete backend/frontend/E2E and
migration CI, scientific review with representative observations, and real
installed Windows MSI/CAB/GUI and GPU gates before any release-ready claim.

## Track C: identity-label invariance for subresolution cubic scale (2026-11-19)

A synthetic closed-mesh regression now verifies that changing only a caller
supplied specimen label preserves the source geometry hash, nominal enclosed
volume, inverse-length area/volume ratio, and numeric-resolution QC. Both
labels remain **unverified biological assertions**, not 3D specimen matches.
The original specimen/observation/frame labels and supplied calibration
evidence remain present in the standalone scientific provenance and in the
twice-executed persisted typed Workflow Builder artifacts. Independent
identity adjudication, calibrated real-coral repeat scans, and longitudinal
matching remain blocked by the 1.4 acceptance matrix.

The predecessor exact-head run finished 20 successes and three backend
failures, all caused by Ruff formatting in the inverse-scale precision gate
and its new test. These formatting hunks have been corrected separately;
this iteration's new test and exact-head Actions must still pass before
any verification claim. **RELEASE HOLD for 1.4 and 1.5** remains mandatory.

## Track C: independent provisional label QC (2026-11-19)

The cubic-scale synthetic fixture now independently alters `specimen_id`,
`observation_id`, and `coordinate_frame_id` in the standalone mesh-preview
API. It requires all unchanged labels to remain attached, provisional
calibration/identity/registration flags to stay false, and the geometry SHA-256,
surface area, enclosed volume, area/volume ratio, scale-only uncertainty
intervals, patch volume, and numeric-resolution QC to remain invariant.
This guards against an unreviewed field label silently changing geometry
or being promoted into a biological match or registered coordinate frame.

The baseline scientific artifact is still compared against two executions
of a persisted, executable typed Workflow Builder graph, including stable
artifact SHA-256. Label changes to the standalone requests deliberately do
not overwrite the saved graph's original parameters. This is synthetic
contract testing only; it is not a real-coral field-validation result and
cannot establish calibration accuracy, specimen identity, branch anatomy,
or longitudinal biological change.

The predecessor exact-head 1.4 run at `3f38f092` completed 20 successful
workflows and three failed backend workflows, all at Ruff formatting.
The two diagnosed long-line cases were corrected in this iteration.
The updated fixture and final-head CI remain unverified until GitHub
Actions completes. **ReefVision 1.4 and 1.5 remain on RELEASE HOLD.**

## Track C: OBJ Unicode source-scalar integrity (2026-11-19)

A bounded OBJ import can contain otherwise inert object labels or comments with
escaped, *unpaired UTF-16 surrogates*. Python JSON decoding can represent these
as strings, but they cannot be encoded as immutable UTF-8 source bytes. The OBJ
parser now explicitly rejects the malformed scalar with a scientific-input
ValueError instead of allowing an uncaught UnicodeEncodeError to interrupt
the preview or job worker. It still accepts legitimate Unicode scalar text
(including non-BMP coral-label characters) in inert metadata without changing
surface geometry. This does not trust or interpret source labels as biological
identity.

The new regression covers direct parser rejection in both labels and comments,
escaped-input standalone API failure, and positive non-BMP Unicode source
parity between standalone preview and an executable, persisted typed Workflow
Builder graph. Supplied calibration and specimen identity remain unverified.
Before this change, the preceding 1.4 HEAD had 22 successful Actions checks
and one still running; final-head tests must be checked independently.
Representative coral validation, independent scientific review, migrations,
Windows installed GUI/MSI/CAB and physical GPU gates remain release blockers.
**RELEASE HOLD for 1.4 and 1.5.**


## Track C: ASCII PLY point-cloud Unicode safety and persisted QC (2026-11-19)

A malformed, JSON-escaped unpaired Unicode surrogate in a point-cloud PLY
comment or coordinate record previously reached `text.encode("utf-8")`
before the ASCII-source check. This could leak `UnicodeEncodeError` rather
than return a controlled scientific-input rejection. The bounded PLY reader now
checks its character-count limit followed by `isascii()`, which is a
byte-equivalent size check for the only accepted source alphabet. Well-formed
but non-ASCII labels are also rejected (unlike OBJ, ASCII PLY remains
ASCII-only), and permitted ASCII coordinates, comments, and source checksums
retain their existing interpretation.

Regression coverage includes direct parser checks, JSON-escaped standalone
API input with malformed surrogate values, and a typed executable persisted
Workflow Builder graph with a well-formed but non-ASCII PLY comment. The graph
must fail without emitting a point-cloud measurement artifact. Existing
positive standalone/twice-replayed saved-workflow tests continue to guard
provisional calibration, source provenance, and deterministic SHA-256
artifacts. The predecessor exact-head Actions completed 20 successful checks
and three backend Ruff-format failures in the OBJ Unicode regression; those
reported hunks were corrected in this iteration.

**RELEASE HOLD:** Final-head CI is pending; none of this establishes biological
identity, calibrated organism surface area or branch length from points,
independent coral validation, physical GPU testing, or an installed Windows
MSI/CAB/GUI acceptance result. ReefVision 1.5 remains isolated and unchanged.

## Track C: malformed JSON Unicode 422 serialization (2026-11-19)

Exact-head CI for predecessor `4997d4bc` reported one failed `CI / backend`
job (five failed cases; 5,169 passed, ten skipped). The five failures were
three OBJ and two ASCII PLY malformed-source API tests. Pydantic rejected
escaped unpaired UTF-16 surrogates *before* the mesh/point-cloud endpoint;
FastAPI's default 422 response then echoed the invalid input and raised
`UnicodeEncodeError` while encoding JSON, rather than returning a controlled
client error. This is distinct from the already-tested direct parser rejection.

The API application now preserves FastAPI's normal 422 `detail` structure but
renders invalid surrogate code points as printable backslash escapes within
validation details, keeping the response UTF-8 serializable without changing
valid Unicode text or inferring any geometry. The OBJ and PLY regressions now
require the `string_unicode` 422 result and safe escaped input, while the
existing valid-Unicode OBJ and persisted typed Workflow Builder parity tests
remain intact. No imported scientific measurement or local checkpoint is
modified by this HTTP boundary fix.

These edits and final-head CI remain **unverified pending Actions**. Synthetic
tests do not establish calibration, specimen reidentification, anatomical
branch length, or field validation. **RELEASE HOLD: 1.4 and 1.5.**
