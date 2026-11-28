# ReefVision 1.4 integration audit

Audit date: 2026-11-15

## Integrated ancestry

- Original refreshed draft 1.4 head: `a50b46699af3a5d9795299f15d80a0060479b0d9`
- Validated 1.3 head: `f44053a90286ce57cc6f7356be922bcf8ba41e22`
- Refreshed `main` used for integration: `e94dad6a3bece7b776bf45776bc5d06cfbc2c0dc`
- Release-accountability foundation: `347a5f9e2` and `8de08f4cf`

The integration is real merge ancestry. Neither source history was rebased,
squashed, or force-updated. Subsequent concurrent commits were merged without
force-pushing.

## Preserved contracts

- Validated 1.3 scientific, ecological, native ReefPose, temporal ReefPose,
  Project Exchange, backup, and Workflow Builder surfaces remain present.
- Draft 1.4 mesh and point-cloud preview, measurement, longitudinal comparison,
  spatial source-asset, calibration-review, and artifact-viewer surfaces remain
  present.
- Workflow artifact literals and the run inspector retain both 1.3 scientific
  artifacts and 1.4 spatial artifacts.
- Native ReefPose registration and video execution remain supported.
- Active SLEAP-NN registration/execution and SLP interchange remain retired
  fail-closed under decision 0010; historical records stay readable.
- CI retains the feature-inventory gate and the opt-in neutral pose interchange
  suite.

## Conflict rulings

- Union route, model, workflow-schema, diagnostics, and frontend entry points
  where both histories added independent behavior.
- Prefer validated native ReefPose paths over draft SLEAP execution paths.
- Preserve 1.4 contextual mesh and point-cloud viewers alongside the 1.3
  scientific artifact renderer.
- Keep advanced 3D controls inside Workflow Builder instead of adding a
  top-level tab.
- Preserve historical migration bodies and reconcile the numeric `0038`/`0039`
  collision with schema-fingerprinted aliases and a real merge revision.

## Current migration graph

```text
b13_temporal_0001 ─┐
                   ├─ b14_integration_0001 ─ b14_spatial_0040
spatial_0039 ──────┘
```

`b14_spatial_0040` is the single current head. It adds append-only units,
coordinate-frame, affine-transform, calibration, local-review, ancestry,
source-hash, and integrity-hash metadata. Fresh, validated-1.3, and proven
legacy-spatial upgrades pass; ambiguous or unknown fingerprints fail before
mutation. See `REEFVISION_1_4_MIGRATION_RECONCILIATION.md`.

## Scientific-integrity boundary

Known synthetic geometry and integrity checks can verify software behavior, but
they cannot verify field accuracy or biological meaning. Registration,
cross-acquisition organism correspondence, longitudinal change, anatomical
branch length, biological condition, and representative spatial validation
remain blocked on the exact external inputs in the canonical feature inventory.
No preview, confidence, chord, route, or locally attributed review is promoted
to those scientific claims.

3D specimen correspondence remains distinct from appearance-based ReefPose
re-identification across long gaps or videos.

## Acceptance boundary

Source gates cover lint/format, type checking, the full backend and frontend
suites, Playwright entry flows, production build, release metadata, inventory,
and Alembic round trips. Exact final counts and SHA are posted to draft PR #79
and coordination issue #76 after the final commit.

The exact-SHA Windows run at
`https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/43792901192`
passed clean install and published 1.0.3 → 1.4.0 upgrade, persistence, Project
Exchange, uninstall, and data-retention checks. Packaged UI inspection confirmed
the normal Home → project → Video & automation → Workflow builder →
Project-owned 3D originals path and the absence of a top-level 3D tab.

The remaining installed lineage evidence is representative 1.3 and legacy
draft-1.4 profiles upgraded by a final-candidate installer, including exchange
and verified pre-upgrade-backup restore. Representative scientific and physical
hardware evidence is separately blocked; neither omission is hidden by the
successful broad gates.
