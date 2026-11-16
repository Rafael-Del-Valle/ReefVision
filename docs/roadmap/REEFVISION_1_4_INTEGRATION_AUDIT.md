# ReefVision 1.4 integration audit

Audit date: 2026-11-15

## Integrated ancestry

- Refreshed draft 1.4 head: `a50b46699af3a5d9795299f15d80a0060479b0d9`
- Validated 1.3 head: `f44053a90286ce57cc6f7356be922bcf8ba41e22`
- Refreshed `main`: `e94dad6a3bece7b776bf45776bc5d06cfbc2c0dc`
- Local pre-integration release-accountability commits: `347a5f9e2` and `8de08f4cf`

The integration is a real ancestry merge. Neither source history was rebased,
squashed, or force-updated.

## Preserved contracts

- The validated 1.3 scientific, ecological, native ReefPose, temporal ReefPose,
  project-exchange, backup, and Workflow Builder surfaces remain present.
- The draft 1.4 mesh and point-cloud preview, measurement, longitudinal
  comparison, spatial source-asset, calibration-review, and artifact-viewer
  surfaces remain present.
- Workflow artifact literals and the run inspector retain both 1.3 scientific
  artifacts and 1.4 spatial artifacts.
- Native ReefPose registration and video execution remain supported.
- Active SLEAP-NN registration/execution and SLP interchange remain retired
  fail-closed under decision 0010; historical records stay readable.
- CI retains the feature-inventory gate and the validated 1.3 opt-in neutral
  pose-interoperability integration suite.

## Conflict rulings

- Union route, model, workflow-schema, diagnostics, and frontend entry points
  where both sides added independently useful behavior.
- Prefer validated 1.3 native ReefPose paths over draft SLEAP execution paths.
- Prefer the newer explicit SLEAP retirement contract over both older branches'
  active SLEAP claims.
- Preserve the 1.4 contextual mesh and point-cloud viewers alongside the 1.3
  scientific artifact renderer.
- Preserve the 1.3 hybrid detector/segmenter validation while also disabling
  execution for a selected historical SLEAP registration.

## Superseded or rejected behavior

- Rejected active `sleap_nn` factories and UI execution labels.
- Rejected treating either branch's single Alembic head assertion as the
  integrated graph. The two histories reuse numeric revision IDs and require a
  separate fingerprinted lineage reconciliation; silently choosing one history
  would orphan the other.
- No draft 1.4 preview output is promoted to reviewed anatomical measurement,
  organism identity, or biological condition evidence.

## Verification boundary

Focused provider, native ReefPose, workflow-graph, and frontend workspace tests
were run after conflict resolution. Two pre-existing oversized/malformed spatial
source parametrizations still error during fixture setup and are tracked as a
draft 1.4 baseline defect. Alembic verification is intentionally not claimed
until the migration-reconciliation task supplies unique active revisions and
legacy database fingerprint tests.
