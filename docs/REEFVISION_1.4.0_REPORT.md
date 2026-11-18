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
