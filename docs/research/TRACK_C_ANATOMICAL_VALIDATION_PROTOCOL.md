# Track C: anatomical coral measurement validation protocol (proposed)

Status: **protocol draft, not validated evidence**. Applies to the isolated ReefVision 1.4 research branch; does not certify a release.

## Distinguish the estimands

- **Mesh surface area (m²):** sum of reconstructed triangle areas after a documented linear scale. This is *reconstructed surface area*, not verified living tissue area. Missing surfaces, occlusion, topology defects and photogrammetry bias are not captured by scale-only intervals.
- **Axis-aligned dimensions (m):** imported-frame bounding extents. Orientation and disconnected debris affect these values. Do not interpret as organism height or width until an anatomical reference frame and exclusion rules are approved.
- **Mesh-edge path length (m):** shortest path along the mesh edge graph between user-selected vertices. It is not a branch centerline, skeletal length, or anatomical branch length. Detour ratio and edge/topology QC are diagnostics, not validation.
- **Enclosed volume (m³):** conditional numerical estimate on admissible closed meshes. Even a closed, consistently wound mesh can self-intersect or represent incomplete biology. Never label it living coral volume without independent verification.
- **Longitudinal difference:** paired reconstruction difference conditional on same-organism identity, registration, compatible coordinate frames and calibration. Provisional reidentification evidence must not silently become verified identity.

## Reference set and acquisition

Create a held-out reference set covering at least three branching morphologies, open versus closed or incomplete reconstructions, occluded branches, nonmanifold and disconnected components, multiple camera orientations, and repeated scans of the same fragment. Record collection/source, acquisition time in UTC, camera and reconstruction software versions, original files' SHA-256 digests, independent scale source, units, calibration uncertainty, mesh topology QC, and operator.

Acquire **independent physical references** where ethical and feasible (e.g., calibrated ruler/photogrammetric targets for dimensions; measured reference objects of known surface area; carefully defined branch centerlines by multiple expert reviewers). A synthetic triangle or cube can verify geometry calculations but cannot validate anatomical interpretation. Do not claim biological ground truth from a model prediction.

## Human review and identity

Two independent reviewers should annotate organism boundaries, branch endpoints and junctions, uncertain or occluded regions, and inclusion/exclusion decisions while blinded to algorithm estimates. Store reviewer ID, timestamp, protocol revision, disagreements and adjudication separately. Preserve raw annotations and provisional model outputs. For repeat scans, require a human-confirmed specimen identifier and explicit registration assessment; a matching geometry fingerprint alone is insufficient.

## Error model and acceptance analysis

Pre-register metrics and tolerances **before** inspecting held-out performance. Report signed error, absolute error, relative error where the denominator is nonzero, and Bland–Altman bias and limits of agreement for paired measurements; report reviewer reliability with an ICC model chosen for the actual sampling design and confidence intervals. Report errors stratified by morphology, reconstruction quality, size and calibration method. Avoid treating multiple branches from one coral or repeated images as independent biological replicates; use specimen-level grouping or a justified hierarchical model.

Propagate calibration uncertainty separately from reconstruction error, reviewer variation, endpoint choice and registration error. Existing scale-only bounds are *not* full confidence intervals. Explicitly flag missing reference data, unregistered frames, incomplete surfaces and unresolved reviewer conflicts as unverified rather than passing them.

## Standalone and persisted Workflow Builder acceptance

For each approved metric, run the same frozen input through the standalone endpoint and a saved, typed Workflow Builder graph. Verify identical numerical results and QC/provenance payloads, immutable input and artifact digests, retained calibration and reviewer state, replayability across process restarts, and predictable failure without a published measurement artifact on malformed or mismatched inputs. Test graph version migration separately. Include Windows installed-GUI review of imported OBJ/PLY/GLB meshes and point clouds, calibration entry, reviewer decisions, and exported results; test GPU paths where applicable.

## Release gate

A green CI run or synthetic geometric regression alone does **not** satisfy anatomical or biological validation. Release readiness requires recorded held-out reference results, predefined scientific tolerances, complete backend/frontend/E2E/migration checks, reproducible saved-workflow runs, and actual Windows MSI/CAB/installed-GUI/GPU acceptance. Keep 1.4 and 1.5 marked **not release-ready** until each applicable gate is evidenced.
