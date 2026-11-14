# Track C scientific geometry acceptance checkpoint (2026-11-09)

Scope: isolated ReefVision 1.4 draft PR #79, coordinated under issue #76. This is a **validation plan**, not evidence of release readiness or biological accuracy. No changes to local model checkpoints or review decisions.

## Evidence reviewed

- Branch HEAD before this document: `56acaccb69004be089309ddd568c7fa97f3b1ea3`.
- Exact-head pull-request Actions: 19 successes and 2 failures (21 returned).
- Both failed Windows jobs reached Tauri bundling and reported `failed to bundle project: http status: 504`; installer/installed-GUI acceptance did **not** pass. The PyInstaller hidden-import diagnostics alone do not establish the terminal failure.
- Existing production triangle-area primitive validates three-component finite numeric coordinates. Existing synthetic geometry tests cover a calibrated cube, 3-4-5 triangle, duplicate faces, edge-connected components, orphan vertices, rigid transformations, and scale-only intervals.
- A passing synthetic reference or a Windows build *workflow* is not evidence of independently verified coral anatomy, field calibration, successful MSI installation, or GPU inference.

## Next independent acceptance references

| Test reference | Standalone expectation | Saved typed Workflow Builder expectation | Human review |
| --- | --- | --- | --- |
| Known-scale planar 3-4-5 triangle | Area = 6 source units squared; 10% scale uncertainty gives [4.86, 7.26] area interval | Same area, interval, geometry hash, calibration provenance and QC after graph save/reload/execute | Calibration remains provisional |
| Closed cube with side 2 source units | Surface area = 24 source units squared; enclosed volume = 8 source units cubed only if watertight and consistently oriented | Same topology qualification and explicit volume caveat | Not a biological volume estimate |
| Branched synthetic coral centerline with measured geodesic reference | Distinguish selected *surface-edge path* from validated anatomical branch centerline; do not label the former branch length | Persist the distinction in typed output and provenance | Anatomical landmark and path verification required |
| Repeated scan of same specimen with changed frame | Registration evidence, frame identity, source hashes, uncertainty and QC retained; no unverified growth claim | Reload and execute the saved graph; assert identical evidence bindings | Reviewer verifies identity and alignment |
| Two scans of different specimens | Do not infer organism identity solely from similar geometry | Preserve provisional identity and reject mismatched bound evidence | Explicit reidentification decision |
| Point cloud without reconstructed watertight surface | Preview and point metrics only; no invented surface area or enclosed volume | No downstream numeric area/volume artifact without validated mesh | Reconstruction method and QC required |

## Release blockers

1. Validate true anatomical branch length against independent manually measured or physically calibrated reference specimens; keep surface geodesics distinct.
2. Establish uncertainty budgets beyond scale alone (segmentation/reconstruction, registration, observer, specimen movement) and avoid interpreting scale-only intervals as total confidence intervals.
3. Run saved-workflow execution and reload tests for every exposed analysis, including failures and human verification transitions.
4. Validate imported OBJ, PLY, GLB and point clouds in the installed interactive GUI, including provenance and persistent asset reopening.
5. Repeat Windows MSI/CAB build, fresh installation, upgrade, persistence, uninstall and GPU/CPU acceptance after the HTTP 504 dependency-download failure clears.
6. For 1.5, establish experimental-unit checks, reviewer agreement and model benchmark statistical references before marking any study package reproducible.

Do not merge, tag, publish or declare either version ready based on this checkpoint.

## Reproducible scientific acceptance protocol (not yet executed)

For every row above, record an immutable fixture identifier and SHA-256, units, coordinate frame, software commit, calibration method and calibration uncertainty, expected numeric tolerance, actual result, reviewer identity, and explicit verification state. Save the Workflow Builder graph, close and reopen it from persistence, execute it again, and compare both the typed result **and** the artifact's source fingerprints, QC flags, and review provenance. A standalone result alone is insufficient. Do not convert provisional observations into verified ones automatically.

**Mesh numerical tolerances:** For the exact synthetic 3-4-5 triangle and cube, use absolute tolerance 1e-10 in source units for area/volume on correctly scaled, nondegenerate inputs; reject nonfinite coordinates, duplicate/coincident faces, malformed dimensions, and topology-ineligible volume. The scale interval for 10% relative length-scale uncertainty is calculated by squaring the lower/upper length factors (0.9² and 1.1²), not by adding ±10% to area. These fixture tolerances are software regression criteria, **not** uncertainty estimates for real corals.

**Anatomical path test:** Include a Y-shaped, independently defined centerline with three segment lengths and a designated base/tip. The expected branch path is the sum of the designated centerline segments, not the mesh perimeter, shortest surface-edge path, total skeleton length, or Euclidean tip-to-base distance. Require an explicit unverified/unsupported outcome until a centerline and landmark review path actually exists; never manufacture a numeric anatomical branch length from a surface path.

**Longitudinal and reidentification test:** Include a rigidly transformed identical reconstruction, a genuinely changed reconstruction, and a distinct-organism negative control. A rigid transform should not by itself create a growth claim. Preserve source/target geometry hashes, specimen identifiers, UTC observation times, frame transforms, calibration, and reviewer decisions across reload. Reject stale evidence whose bound geometry fingerprint changes; distinguish measurement change, registration residual, and biological change.

**Statistical 1.5 handoff:** Before enabling a study-package export, include fixtures with repeated fragments nested within tanks, multiple reviewers scoring the same observations, and held-out model predictions. The experimental unit must be declared (e.g., tank for a tank-level feeding treatment), with pseudoreplication checks; ICC model/type and single-versus-average rating must be specified; Bland–Altman must report pairing, bias, limits of agreement and assumptions; model comparisons must use the same held-out samples and identify leakage. Saved workflows must retain design, randomization, missingness, analysis configuration, multiplicity decisions, and QC, with no unreviewed significance or causality claim.

**Pass evidence:** Link exact-head CI job and fixture output for backend/frontend/E2E/migrations/scientific checks, then separately document Windows MSI/CAB construction, fresh-install GUI interactions, persisted reopen, and actual CPU/GPU inference. A passing packaging workflow does not establish successful installed-GUI or hardware acceptance.
