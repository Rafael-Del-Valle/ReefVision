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

## November 19 project comparison checkpoint

The integration branch `codex/reefvision-1.4-spatial-candidate` targets
the existing 1.4 draft. `9e4adcf62` merged #79 at `bf727f458` with the
Windows lineage work at `36c80224a`. Both parents contain the validated
1.3 commit `f44053a90` and 1.2 commit `14eb83eb2`. The single Alembic
head at this checkpoint was `b14_spatial_0040`. [Candidate draft](https://github.com/Rafael-Del-Valle/ReefVision/pull/90)

| User workflow | Observed result | Remaining acceptance |
| --- | --- | --- |
| Home → open project → Video & automation → Workflow builder → import two originals → Compare two acquisitions | Source commit `3e0928fed`. The live API and Chromium withheld change for a disputed synthetic identity. The supported fixture correspondence gave a 0.5 m² difference and a scale-only interval of 0.205–0.805 m². | Independently acquired, calibrated paired scans with identified specimens, survey controls, reviewer authority and prespecified tolerances. |
| Save comparison workflow → reopen from Home → run saved revision twice → download JSON | Saved graph `02ec61af-c7b6-495e-8a10-a62f474f3ccd` ran under `f0f50780-8d0e-4c47-8857-366361d86223` and `17635288-f4ca-479d-9fd4-290946659fee`. Both exports matched the standalone payload exactly, with SHA-256 `b76761113933607cc9c2cd22430288cb6bdd4886ca65a125d6b778f5b456b11b`. | Repeat this journey from the packaged Windows WebView2 on the integrated candidate. |
| Draft Windows profile upgrades, Project Exchange and backup recovery | Local tests covering the historical matrix, migration reconciliation, point clouds and inventory passed 74/74. The #89 installer run passed fresh install, published 1.0.3 upgrade and three disposable profile upgrades. The historical 1.3 executable rejected the upgraded DB and preserved its hash. [Installed reports](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44072770396) | Authorized copies of real validated-1.3 and legacy draft-1.4 profiles, with verified backups. Smart App Control enforcement requires a suitable disposable Windows 11 device. |
| 1.1 environmental refresh → offline reread | The #71 missing-cell repair was reproduced on #79 and integrated from `ab0d2afb5`. Incomplete provider responses retained the cached scientific records. | Live provider acceptance requires an authorized account and input. Projective density and repeated-measures decisions remain in the inventory. |
| Frozen temporal corpus → CUDA training → reviewed comparison | A physical RTX 3090 ran the synthetic three-clip exercise. For 24 coordinates in 12 held-out frames from one group, frame and temporal mean localization errors were 46.243 and 45.861 px. Both missed the one complete reference event. | Representative held-out animal recordings, independent landmarks/events, a compatible registered checkpoint, error criteria and timing/count references. |

All named meshes, study identities, reviews and video clips in these local
checks are engineering fixtures. The two live spatial tests use a disposable
API profile and the production React application. Set
`REEFVISION_GUIDED_TEST_WEB` and `REEFVISION_GUIDED_TEST_API` to the local
frontend and API and run the two Playwright specs
`project-spatial-comparison-live.spec.ts` and `spatial-guided-workflow-live.spec.ts`.
Each comparison export contains its asset IDs, original byte hashes, calibration
evidence and local review attribution.

### Centerline and condition review

After `1da2769e5` the selected asset also opens **Anatomical branch length**
and **Condition review**. The centerline tool measures an investigator's
ordered XYZ polyline in the declared source frame. It stores named endpoints,
method, operator, scale and optionally a reference and repeatability protocol
in the saved mesh workflow. An out-of-bounds point was rejected. The
synthetic three-point trace measured 0.025 m with a scale-only interval of
0.0225–0.0275 m. Two runs produced the same payload digest.

Condition review freezes the supplied rubric version, labels an observation
on the selected original and stores attributed decisions and adjudication
as successor revisions. The project routes under
`/api/v1/projects/{project_id}/spatial/assets/{asset_id}/condition-observations`
support the observation ledger and JSON reports. The new Alembic head
`b14_condition_0041` follows `b14_spatial_0040` and adds the rubric and
condition revision tables. An upgraded copy of the disposable two-acquisition
profile retained its originals and saved workflows. The browser recorded a
disagreement, reopened the project and exported the observation and decision.

Four source-browser journeys, 721 frontend tests, 51 focused migration,
exchange, backup and spatial tests, and 123 Windows harness assertions passed
in this integration. A successful run on a field dataset still requires the
reference material, independent review and tolerances in the respective
inventory rows. The Windows clean-install job exercises the packaged WebView2
using a per-process disposable profile and a loopback connection. Its result
belongs to the SHA identified by the installer provenance.
