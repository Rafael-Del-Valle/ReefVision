# ReefVision 1.0.1 — Pre-release acceptance and handoff

**Status:** Release HOLD. The earlier installer candidate passed the recorded
acceptance below, but PR #44 now contains additional annotation-intelligence
changes that require fresh exact-head CI and installed-desktop validation. Keep
the PR in draft and do not merge, tag, or publish without explicit maintainer
approval.

## 1.0.1 patch highlights

- SAM 2.1 Tiny, Small, Base+, and Large optional checkpoint download when a
  user selects that variant; provenance, checksum verification and retry.
- Shift+1: image-wide proposals using the explicitly promoted detector when one
  is active, otherwise bounded full-image SAM generation. Shift+2: non-destructive
  refinement of exactly one selected saved mask. SAM box prompting remains a
  separate action; ordinary number-key class selection is preserved.
- Pending proposal masks support paint/erase correction, undo/redo, class
  assignment and explicit acceptance or rejection. They are excluded from
  verified counts and training data until accepted.
- Verified-annotation learning creates immutable, group-safe dataset snapshots,
  queues local training, evaluates detector candidates on held-out groups, and
  requires explicit promotion. Promotion and rollback are audited; evaluation
  outputs cannot be accepted as annotations.
- Class discovery from local .pt metadata; acceptance persists native project
  annotations with model provenance.
- COCO boxes/masks and YOLO detection/segmentation import with class names,
  including unused categories; retain external metadata.
- Confidence-based review with a configurable default cutoff of 50%; only
  predictions at or below the cutoff appear for review, and no proposal is
  considered human-verified without an explicit acceptance.

## Automated acceptance evidence

- Tested source commit: `d74b603c407ba8312fc270e90c81065d086749fd`
- Successful installer build and **separate clean Windows runner**:
  https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/38181922418
- Successful backend/frontend CI:
  https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/38181922403
- Successful full scientific/software acceptance:
  https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/38181922399
- Successful standalone live SAM 2.1 acceptance:
  https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/38181922294
- Windows acceptance report artifact:
  https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/38181922418/artifacts/11719011541
- Installer artifact (MSI, six external CAB files, build provenance):
  https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/38181922418/artifacts/11717564456

**Windows acceptance report:** PASS for MSI installation; shortcuts; first
launch; frontend-to-backend connection; migration status; catalog policy;
real SAM 2.1 Tiny checkpoint download, inference and human-accepted mask;
COCO/YOLO imports; confidence review; saved annotations; desktop restart;
project exchange; uninstall; and user-data retention. The packaged SAM
inference completed in approximately 8.6 seconds on the acceptance runner.

**MSI:** `ReefVision_1.0.1_x64_en-US.msi`
**SHA-256:** `EB73C952D3C3FF16AABC64DBEDE7AFAAD218BE1EDAB5AD5E36F8F167FF9916FD`
**External media:** `rv1.cab` through `rv6.cab`. Keep the CAB files
alongside the MSI when distributing or installing; the MSI depends on them.
The MSI ProductVersion and packaged API both reported `1.0.1`.

The acceptance test ran with Python, Node.js and Rust absent from the
installed application's PATH. The model catalog exposed 25 architectures
and zero bundled pretrained checkpoints. The optional SAM Tiny checkpoint
was fetched into isolated user cache as part of the test.

## PR #44 annotation-intelligence validation

Source validation for the current PR work includes a real SAM 2.1 Tiny
full-image proposal run, focused backend coverage for proposal generation,
refinement, verified learning, held-out evaluation and model inference, the full
frontend unit/E2E/build suite, and an Alembic upgrade/downgrade/upgrade cycle.
The exact commands and counts are maintained in the PR description and issue
#48 progress log so this document does not imply that the earlier MSI exercised
the newly added keyboard and mask-editing workflows.

Instance-segmentation annotations with holes remain blocked from the existing
polygon-only training path rather than flattened. Candidate evaluation and
guarded promotion in the Improve Predictions panel currently cover detector
models. Automatic retraining remains opt-in; ReefVision does not silently train
or activate a model from newly verified data.

## Remaining acceptance boundaries

- [ ] Fresh exact-head core CI for the annotation-intelligence changes (Ruff,
      mypy, pytest, frontend formatting, TypeScript, Vitest, Playwright,
      production build).
- [x] Software/provider acceptance on pinned Windows Python.
- [x] Separate clean-machine MSI lifecycle, including SAM and persistence.
- [x] MSI version, six external CAB files and cryptographic artifact digests.
- [ ] Direct **installed desktop GUI** operator smoke test of full-image Shift+1,
      selected-mask Shift+2, proposal paint/erase and undo/redo, Accept Visible,
      explicit candidate promotion/rollback, and the floating review dialog.
      The earlier automated MSI test exercised the packaged API, not these new
      keyboard/mouse interactions.
- [ ] Optional upgrade-in-place test from a compatible prior MSI; the clean
      install workflow passed `-SkipUpgrade`.
- [ ] Explicit maintainer approval for any merge, tag or public release.

The successful acceptance URLs above refer to the tested source commit. Any
subsequent source or release-documentation change needs fresh latest-commit
validation before the final approval decision. Artifact URLs expire according
to GitHub Actions retention (the installer and evidence were scheduled to
expire around 2026-10-25).
