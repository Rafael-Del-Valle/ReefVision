# ReefVision 1.0.1 pre-release acceptance and handoff

**Status: HOLD.** Automated software acceptance passed on the integrated scientific candidate. Installed interactive GUI acceptance, NVIDIA GPU acceptance, representative scientific validation, and explicit maintainer approval remain required.

**Candidate branch:** `feat/segmentation-evaluation-gui-20261013`

**Validated code-bearing commit:** `7bd298fbfa26164f6b6a14b3fb7d6ed5e8a18590`. The following documentation-only child records its immutable evidence; the draft PR records the current exact head and live checks.

**Draft PR:** [#68](https://github.com/Rafael-Del-Valle/ReefVision/pull/68), based on the complete 1.0.1 annotation branch in [#44](https://github.com/Rafael-Del-Valle/ReefVision/pull/44), with provenance hardening from [#70](https://github.com/Rafael-Del-Valle/ReefVision/pull/70).

**Publication policy:** Do not merge, tag, publish, replace release assets, or install on the maintainer's personal computer without explicit approval. Preserve `v1.0.1-rc.1` and its published assets.

## Implemented behavior

- Optional SAM 2.1 Tiny, Small, Base+, and Large checkpoint acquisition is explicit, verified by revision and SHA-256, cancellable, and recoverable. ReefVision does not bundle unrelated pretrained detector weights.
- Shift+1 creates image-wide proposals with the active local detector or bounded full-image SAM generation. Shift+2 refines exactly one selected saved mask without changing the original until acceptance. Box-prompt SAM and bare numeric class shortcuts remain separate.
- Pending proposals support class assignment, edit, accept, reject, Accept Selected, and Accept Visible. Unapproved and evaluation-only outputs cannot become verified counts or training examples.
- Local `.pt` registration retains task, label schema, checkpoint digest, and provenance. COCO and YOLO import preserve source association, stable identities, geometry, labels, and external metadata.
- Verified-only learning snapshots are immutable and group safe. Segmentation evaluation uses source-pixel instance masks, class-aware one-to-one matching, mask AP50, precision, recall, count MAE, signed count bias, and per-class support. A successful zero-proposal inference remains a valid scored result with zero recall and measured count error.
- Candidate and incumbent evaluation are bound to the same immutable holdout. Queue children carry exact model, checkpoint digest, dataset ID, split, manifest digest, parent evaluation ID, task, project, evaluation-only state, and source-image list; finalization rejects missing, fabricated, or mismatched provenance after database serialization and worker execution.
- The direct completed-evaluation API accepts only trusted parentless jobs with the same exact immutable provenance. It rejects queue-created children, so a queued job cannot be detached from its persisted evaluation parent.
- Segmentation promotion and rollback require explicit operator identity, reason, confirmation, current active-state checks, eligibility, matching project/task/schema/lineage, and a verified checkpoint digest. They do not change the active detector.

## Exact-head automated evidence

Code-bearing commit `7bd298fbfa26164f6b6a14b3fb7d6ed5e8a18590` completed **25/25 GitHub checks successfully** on October 14, 2026.

| Gate | Verified result | Evidence |
| --- | --- | --- |
| Backend | Ruff PASS; strict mypy PASS on 403 files; 1,169 passed, 32 skipped, 1 warning | [Full acceptance run 38500660514](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/38500660514) |
| Scientific regression | 117 passed, 1 warning; direct and queued lineage modes plus real database round-trip covered | Same full acceptance run |
| Database | Canonical Alembic upgrade, downgrade to base, and upgrade through revision 0037 PASS | Same full acceptance run |
| Frontend | Prettier and TypeScript PASS; 395 Vitest tests in 87 files PASS; production build PASS | Same full acceptance run |
| Browser E2E | 11 passed, 1 configured OSM skip | Same full acceptance run |
| SAM providers | Live SAM 2.1 checkpoint/CPU inference, pinned Windows providers, and native Windows Python 3.12 PASS | Same full acceptance run |
| Windows package | Independent MSI/CAB build PASS | [Installer artifact 11866965156](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/38500660483/artifacts/11866965156), archive digest `sha256:7a39f25d72320c58ec2baccc5fe3a3f146e24d8c1bc6f2de14cc0244e1ae972e` |
| Disposable Windows lifecycle | Install, launch, persistence, packaged SAM CPU inference, uninstall, and retained data PASS | [Build run 38500660483](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/38500660483) and [evidence artifact 11867340545](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/38500660483/artifacts/11867340545), digest `sha256:7de02d82b61c737345680bf879bd0db7eda32cc8c3bd034cfacdfe3fde035713` |
| Independent release package | Acceptance workflow independently built and verified the release package | [Artifact 11867825491](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/38500660514/artifacts/11867825491), digest `sha256:f6e676663140b1056aee16806bf062674ac1aee1f097d90c6dcf7dee1f8cb10c` |

The lifecycle run tested `ReefVision_1.0.1_x64_en-US.msi` with SHA-256 `19A396FFA86ABD531A5AE36896702EF4FB9DB6FC9F1CE6FE80B1D0972A93098A`. Its MSI Media table required five external cabinets, and all five were present:

- `rv1.cab` — `C416943251F05AE652FEC7C712FB3311E1D6BAE188B7D4D0A355AB6B8D07612D`
- `rv2.cab` — `192D245F48A864682A4BAF1F821A807C46BC7325323282C9648BED8654AD0A2A`
- `rv3.cab` — `3B8D4C49F1C9AD5FE27EBD4905B0C5C2E2C4575E27312E0D8A425A7C4E11FE16`
- `rv4.cab` — `F5F2B140B3F8D7D1B309D05C8B0AE8EF1C680426384ECC93132F590E4EFA4741`
- `rv5.cab` — `7D2F89C375DCB6F0D91E8BC33BA2CF8C81C290D72749C7F160F75375B23622BC`

Use only the MSI and cabinets from artifact `11866965156`; the independent acceptance artifact is a separate build. Automated installation and browser E2E do not establish interactive mouse/keyboard acceptance, NVIDIA execution, or scientific validity on representative research data.

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
