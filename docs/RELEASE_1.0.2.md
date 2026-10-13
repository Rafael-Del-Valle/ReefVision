# ReefVision 1.0.2 pre-release acceptance and handoff

**Status: HOLD.** The annotation usability and first-image work is now combined with the integrated 1.0.1 scientific baseline. The combined exact head still requires GitHub-hosted validation and new matched installer artifacts. Installed interactive GUI, NVIDIA GPU, representative scientific acceptance, and explicit maintainer approval remain required.

**Integration branch:** `integration/reefvision-1.0.2-scientific-20261013`

**Inputs:** [1.0.1 scientific PR #68](https://github.com/Rafael-Del-Valle/ReefVision/pull/68) and [1.0.2 first-image PR #58](https://github.com/Rafael-Del-Valle/ReefVision/pull/58), which contains [annotation-usability PR #50](https://github.com/Rafael-Del-Valle/ReefVision/pull/50)

**Publication policy:** Do not merge, tag, publish, replace release assets, or install on the maintainer's personal computer without explicit approval.

## What 1.0.2 adds to the 1.0.1 baseline

| Area | 1.0.1 baseline | 1.0.2 behavior |
| --- | --- | --- |
| First project image | Existing project/gallery entry | Delayed full-resolution decode keeps a usable thumbnail until ready, retries failures, and verifies real decoded dimensions and source-coordinate overlays |
| Gallery | Thumbnail selection | Stable recent-image restore, synchronized paging, Arrow/Home/End navigation, optional wrapping, corrupt-image retry, and active-thumbnail scrolling |
| Viewport | Existing annotation canvas | Cursor-centered zoom, Alt or middle-button pan, Fit, Actual Size, Reset, pointer-cancel recovery, and unchanged source-pixel geometry |
| Duplication | Existing annotation persistence | Internal copy/paste/duplicate for boxes and polygons plus independent raster-mask files, new IDs, bounded translation, undo/redo, and draft review state |
| Shortcuts | Shift+1, Shift+2, class numbers | One accessible registry/dialog with conflict detection, focus guards, tooltips, and protected SAM/class bindings |
| Scientific workflow | Integrated segmentation evaluation and audited deployment from PR #68 | The same immutable holdout, exact-mask metrics, tamper checks, explicit promotion, rollback, and audit history remain available with the usability changes |

## Integrated scientific safeguards

- Verified-only, immutable, group-safe holdouts and training snapshots.
- Exact raster-mask handling for holes and disconnected components.
- Candidate and incumbent inference bound to the same dataset, manifest, split, model IDs, checkpoint digests, parent job, and image list.
- Evaluation-only output isolation from review, verified counts, and training.
- Explicit eligibility, operator identity, reason, confirmation, active-state, task, schema, lineage, and digest checks for promotion and rollback.
- Draft duplicates never inherit human verification or model provenance.

## Verified prerequisite evidence

The two input heads passed independently before integration. Their artifacts prove those exact source heads only.

| Input | Exact source | Automated result | Package evidence |
| --- | --- | --- | --- |
| Integrated 1.0.1 science | `004f6c284234c9a846a1fc537fc899f2399ca2e9` | 25/25 checks; 1,158 backend passed/32 skipped; 117 scientific passed; 395 Vitest; 11 Playwright passed/1 skipped | 1.0.1 MSI SHA-256 `B42EF98864D5150AF0363F6E590E2079F22D1E27B453C8D4CA1B3E14CF6ADEAA`, six CABs, [run 38453678359](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/38453678359) |
| 1.0.2 first-image/usability stack | `02db7df215960d3cc1f37c9cb62af6b66e40283d` | 21/21 checks; 1,044 backend passed/32 skipped; 117 scientific passed; 436 Vitest; 12 Playwright passed/1 skipped | 1.0.2 MSI SHA-256 `3149E3919583C45F1C4219EC2811E8B563B70D5A1FBFFC9417C655B268337925`, five CABs, [run 38443528254](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/38443528254) |

On the first combined merge, local focused validation passed **142 segmentation backend tests** and **56 scientific-panel, first-image, gallery, and annotation-editor frontend tests**. These focused results do not replace the required combined full CI.

## Upgrade and artifact handling

- Back up researcher data before testing a candidate and use a disposable Windows environment.
- Use the MSI and every external CAB from one workflow artifact. Cabinet count is determined by that MSI's Media table and may vary between builds.
- Verify the candidate source SHA, artifact ID, archive digest, MSI SHA-256, ProductVersion `1.0.2`, and CAB inventory before installation.
- Existing project annotations remain in source-image coordinates. Duplicates are new draft annotations and require explicit verification.
- The integrated scientific stack adds API behavior but no new database revision beyond the existing canonical migration head 0037.

## Remaining release gates

- [ ] Complete exact-head combined backend, scientific, frontend, Playwright, migration, SAM-provider, workflow-graph, and version checks.
- [ ] Generate and verify a combined exact-head 1.0.2 MSI/CAB set on GitHub-hosted Windows runners.
- [ ] Execute every case in [the installed GUI checklist](validation/REEFVISION_1_0_2_INSTALLED_GUI_ACCEPTANCE.md) on a disposable Windows system with retained evidence.
- [ ] Run authorized NVIDIA SAM/model/training acceptance, or record an explicit maintainer disposition.
- [ ] Run the full candidate/incumbent evaluation, explicit promotion, and rollback lifecycle on representative scientist-verified masks and retain sign-off.
- [ ] Obtain explicit maintainer approval before merge, tags, publication, asset replacement, or personal-machine installation.

The release remains **HOLD** until these gates are completed. Historical prerequisite artifacts must not be presented as the combined release candidate.
