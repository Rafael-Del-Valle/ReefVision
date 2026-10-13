# ReefVision 1.0.1 pre-release acceptance and handoff

**Status: HOLD.** Automated software acceptance passed on the integrated scientific candidate. Installed interactive GUI acceptance, NVIDIA GPU acceptance, representative scientific validation, and explicit maintainer approval remain required.

**Candidate branch:** `feat/segmentation-evaluation-gui-20261013`

**Last fully tested source commit:** `004f6c284234c9a846a1fc537fc899f2399ca2e9`. The draft PR records the current exact head and its live checks.

**Draft PR:** [#68](https://github.com/Rafael-Del-Valle/ReefVision/pull/68), based on the complete 1.0.1 annotation branch in [#44](https://github.com/Rafael-Del-Valle/ReefVision/pull/44)

**Publication policy:** Do not merge, tag, publish, replace release assets, or install on the maintainer's personal computer without explicit approval. Preserve `v1.0.1-rc.1` and its published assets.

## Implemented behavior

- Optional SAM 2.1 Tiny, Small, Base+, and Large checkpoint acquisition is explicit, verified by revision and SHA-256, cancellable, and recoverable. ReefVision does not bundle unrelated pretrained detector weights.
- Shift+1 creates image-wide proposals with the active local detector or bounded full-image SAM generation. Shift+2 refines exactly one selected saved mask without changing the original until acceptance. Box-prompt SAM and bare numeric class shortcuts remain separate.
- Pending proposals support class assignment, edit, accept, reject, Accept Selected, and Accept Visible. Unapproved and evaluation-only outputs cannot become verified counts or training examples.
- Local `.pt` registration retains task, label schema, checkpoint digest, and provenance. COCO and YOLO import preserve source association, stable identities, geometry, labels, and external metadata.
- Verified-only learning snapshots are immutable and group safe. Segmentation evaluation uses source-pixel instance masks, class-aware one-to-one matching, mask AP50, precision, recall, count MAE, signed count bias, and per-class support.
- Candidate and incumbent evaluation are bound to the same immutable holdout. Child jobs carry the expected model ID, checkpoint digest, dataset ID, split, manifest digest, parent job, and source-image list; finalization rejects tampering.
- Segmentation promotion and rollback require explicit operator identity, reason, confirmation, current active-state checks, eligibility, matching project/task/schema/lineage, and a verified checkpoint digest. They do not change the active detector.

## Exact-head automated evidence

Commit `004f6c284234c9a846a1fc537fc899f2399ca2e9` completed **25/25 GitHub checks successfully** on October 13, 2026.

| Gate | Verified result | Evidence |
| --- | --- | --- |
| Backend | Ruff PASS; strict mypy PASS on 403 files; 1,158 passed, 32 skipped, 1 warning | [Full acceptance](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/38453678022) |
| Scientific regression | 117 passed, 1 warning | Same full acceptance run |
| Database | Canonical Alembic upgrade, downgrade to base, and upgrade through revision 0037 PASS | Same full acceptance run |
| Frontend | Prettier and TypeScript PASS; 395 Vitest tests in 87 files PASS; production build PASS | Same full acceptance run |
| Browser E2E | 11 passed, 1 configured skip | Same full acceptance run |
| SAM providers | Live SAM 2.1 checkpoint/CPU inference, pinned Windows providers, and native Windows Python 3.12 PASS | Same full acceptance run |
| Windows package | Independent MSI/CAB build PASS | [Artifact 11843879278](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/38453678022/artifacts/11843879278) |
| Disposable Windows lifecycle | Install, launch, persistence, packaged SAM CPU inference, uninstall, and retained data PASS | [Build run](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/38453678359) and [evidence artifact 11843918504](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/38453678359/artifacts/11843918504) |

The lifecycle run tested `ReefVision_1.0.1_x64_en-US.msi` with SHA-256 `B42EF98864D5150AF0363F6E590E2079F22D1E27B453C8D4CA1B3E14CF6ADEAA`. Its MSI Media table required six external cabinets, `rv1.cab` through `rv6.cab`, and all six were present. Use only the MSI and cabinets from the same [installer artifact 11845095338](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/38453678359/artifacts/11845095338); the independent release-build artifact is a separate build.

Automated installation and browser E2E do not establish interactive mouse/keyboard acceptance, NVIDIA execution, or scientific validity on representative research data.

## Scientific safeguards

- Only explicitly verified masks enter learning or evaluation ground truth.
- Related image groups remain in one split, and parent-training lineage is checked to prevent holdout leakage.
- Missing, corrupt, empty, mismatched, or out-of-bounds masks fail closed.
- Raster holes and disconnected components remain exact mask geometry rather than lossy polygon approximations.
- Evaluation-only inference is isolated from annotation review and training.
- Promotion and rollback preserve immutable evaluation history and deployment audit records; stale concurrent operations are rejected.
- No candidate activates silently.

## Remaining release gates

- [ ] Execute the installed Windows GUI workflow for Shift+1, Shift+2, proposal editing, acceptance/rejection, model evaluation, promote/rollback, restart persistence, and uninstall with retained evidence.
- [ ] Run real NVIDIA SAM, registered-model inference, and training/evaluation on authorized compatible hardware, or record an explicit maintainer disposition.
- [ ] Evaluate a registered segmentation candidate and incumbent on a representative, authorized, scientist-verified holdout; review metrics and audit records; promote an eligible candidate; then roll back and confirm the restored selection.
- [ ] Record scientist sign-off and any limitations of the representative dataset and thresholds.
- [ ] Obtain explicit maintainer approval before merge, tag, publication, or personal-machine installation.

Until those gates are completed, the verified status is: code integrated **PASS**, automated CI **PASS**, MSI/CAB **PASS**, installed interactive GUI **BLOCKED**, NVIDIA GPU **BLOCKED**, scientific acceptance **BLOCKED**, ready for approval **BLOCKED**.
