# Track C 1.4 — anatomical branch-length verification protocol (draft)

Status: **proposed validation protocol, not completed validation**. Applies to imported OBJ/PLY/GLB triangle meshes and PLY point clouds. This document does not certify any current mesh-edge path as a biological coral centerline.

## Measurement definitions and experimental unit

- **Mesh-edge route**: shortest connected path along imported triangle edges between two user-selected vertices. It depends on tessellation, endpoint choice, and topology; it is *not* automatically a skeletal axis or anatomical branch length.
- **Anatomical branch length**: distance along a reviewer-approved, explicitly recorded branch centerline from a defined basal junction to an identified terminal tip. Junction/tip definitions and treatment of broken or occluded tips must be prespecified.
- **Independent experimental unit**: the physical colony or fragment (as specified by study design), not its triangles, branch segments, repeated images, or annotator clicks. Nested branches and repeat visits require appropriate within-colony dependence handling.
- **Calibration**: source coordinate units, scale provenance, scale uncertainty, and whether a physical reference has been independently verified must travel with every result. Scale-only intervals do not include reconstruction, registration, endpoint, or observer error.

## Reference collection (required before biological verification)

1. Assign persistent project, colony, fragment, acquisition, and observation IDs, with UTC timestamps and immutable source-geometry SHA-256 fingerprints. Do not infer identity solely from shape similarity.
2. Acquire physical reference lengths with a traceable instrument and document instrument resolution, repeatability, and placement. Photograph scale placement; keep reference readings independent from the software result.
3. Have at least two independent reviewers identify basal junctions, terminal tips, and centerline traces while blinded to algorithm estimates. Save raw selections, reviewer identity, timestamps, and disagreement/adjudication records. Do not silently overwrite either reviewer.
4. Include branching, curved, occluded, damaged, open-boundary, nonmanifold, disconnected, and differing-tessellation examples. Report exclusions and failed reconstructions, not only successful paths.
5. Record reference uncertainty separately from scale-only model uncertainty. Quantify endpoint selection, inter-reviewer variability, reconstruction repeatability, and registration drift where applicable.

## Acceptance analyses

- On a held-out, colony-separated reference set, compare algorithmic centerline length against physical and independently reviewed references. Report sample sizes at the **colony** and branch levels, absolute and relative errors, bias, confidence intervals, and stratification by topology and reconstruction method.
- Use Bland–Altman differences and limits of agreement with clustering or hierarchical resampling when multiple branches belong to a colony; do not treat repeated branches as independent.
- Use a prespecified ICC model and unit (single versus mean reviewer, absolute agreement versus consistency), with confidence intervals. ICC is agreement/reliability evidence, **not ground truth**.
- Assess calibration-interval coverage separately from full measurement uncertainty coverage. Validate numerical invariance across known scale changes and sensitivity to mesh decimation, tessellation, vertex order, endpoint perturbation, and rigid transforms.
- For longitudinal measurements, verify persistent identity and source fingerprints at each time point, use registered coordinate frames with independently assessed drift, and distinguish true biological change from reconstruction or calibration change.
- Declare biological verification only after prespecified tolerances and independent scientific review pass; otherwise label results **provisional geometric evidence** with QC warnings.

## Standalone and Workflow Builder parity

For every fixture, execute both the standalone scientific API and a **saved, reloaded, typed, persisted** Workflow Builder graph. Compare measurement values, nulls, QC warnings, source fingerprints, calibration and reviewer provenance, and verification state. Include negative tests for stale evidence, disconnected routes, nonfinite geometry, invalid calibration, and partial/mismatched identity bindings. Verify that neither path upgrades provisional evidence to verified automatically.

## Release evidence checklist

A future release gate must link the exact commit and passing backend, frontend, persisted-workflow/E2E, migrations, synthetic reference, scientific held-out validation, Windows MSI/CAB packaging, installed GUI, and actual GPU test artifacts. Successful Windows packaging alone is not installed-GUI/GPU acceptance. Retain local-only trained checkpoints and avoid remote upload of private scientific assets.
