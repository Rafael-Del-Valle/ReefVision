# ReefPose Phase 2B Validation

Validated on 2026-11-07/08 on branch `feature/reefpose-core`, building on Phase 2A commit `0531b3a06c69523f0c167d422fb1ba7999316b85`.

## Implemented GUI vertical slice

The existing Workflow Builder pose-training node now exposes native ReefPose without replacing the Phase 1 model or Phase 2A trainer. The GUI supports provider selection, verified frozen datasets, exact schema compatibility, random or compatible-checkpoint initialization, epochs, batch size, input dimensions, learning rate, workers, device, precision, CUDA readiness, cancellation, and compatible resume.

Persisted workflow/job state supplies epoch progress, train/validation losses when present, learning rate, device/precision, current/best checkpoint, cancellation state, and errors. Completed native checkpoints appear in Model Hub with architecture, keypoint count, schema identity/revision/hash, dataset/training provenance, configuration, metrics, and checkpoint integrity. “Use in Pose Tracking” selects the registered model, and native ReefPose video inference now produces source-coordinate keypoints through the existing machine-track and pose-review controls.

Workflow completion invalidates both Model Hub and video-tracking model caches. A delayed workspace command remains pending until the newly registered checkpoint is actually available, preventing inference from silently using the previous compatible model.

Native checkpoint anatomy is enforced at both schema-binding and video-job boundaries: a same-count landmark reorder or a source schema identity/revision/hash mismatch is rejected before inference. Provider discovery also treats a missing or unloadable Torch/CUDA runtime as an unavailable capability instead of breaking Model Hub bootstrap, and the ReefPose capability descriptor now accurately advertises the implemented single-animal video path.

## Actual live GUI acceptance

The guarded Playwright test `apps/web/tests/e2e/reefpose-phase2b-live.spec.ts` exercised the rendered React application against live Vite and FastAPI services with the real background worker and an isolated synthetic dataset. It performed:

1. Open project and Workflow Builder.
2. Select the frozen verified pose dataset.
3. Select ReefPose, CUDA, AMP, one epoch, batch one, and 64×64 input.
4. Save and execute the workflow.
5. Wait for persisted workflow success.
6. Resolve the workflow's exact `model_reference` artifact.
7. Inspect that exact checkpoint's ReefPose anatomy/provenance in Model Hub.
8. Select that exact checkpoint for Pose Tracking.
9. Submit video inference on CUDA device 0 and assert the request uses the same model ID.
10. Wait for the exact tracking job to complete, select its machine-generated track, and display its two landmarks and repeated-tentacle schema in the source-coordinate review UI.

Latest acceptance evidence:

- GPU: NVIDIA GeForce RTX 3090; PyTorch 2.11.0+cu128; CUDA 12.8.
- Workflow run: `78463290-8932-42a9-9e19-98c1d3ca8379`, succeeded in about 2.97 seconds.
- Registered model: `c0ca85cf-4806-4e03-820d-85a12e989774` (`pose-from-scratch pose 6f878103`).
- Checkpoint SHA-256: `a7887ddd628e453f5d9a6fde740c97214440a7d0083f302b05844f17bdd2cbf1`.
- Checkpoint size: 10,543,819 bytes.
- Training: CUDA AMP, one synthetic sample, two repeated anatomical landmarks, one epoch, selection/train loss `0.4947185516`; no independent validation dataset.
- Tracking job: `5eca2193-0e09-4f2f-b3e6-d961b1555c1e`, explicitly bound to the newly registered model, CUDA device 0.
- Tracking result: 30 decoded frames, 18 retained observations, one machine track, 18 pose keyframes, 36 persisted temporal landmark observations.
- Playwright result: `1 passed` in 13.2 seconds on the final post-commit run after the checkpoint-anatomy integrity fixes.

The Windows computer-control harness could not run a separate manual desktop walkthrough because its current browser URL-policy guard stops Windows browser automation. The acceptance above is nevertheless an actual rendered-browser workflow against live local services, not mocked component data. No desktop-only claim is made.

All fixtures and losses above are synthetic engineering evidence. They do not validate biological accuracy, generalization, calibration, or scientific fitness.

## Automated validation

- Frontend Vitest: 93 files, 491 tests passed after the final cache/command fix.
- Frontend TypeScript: passed.
- Frontend Prettier: passed.
- Frontend production build: passed. Vite reports the existing 1.17 MB main-chunk size warning.
- Frontend lockfile policy: passed; `npm ci` did not change the lockfile. npm reported two moderate and two high audit findings; no automatic audit fix was applied.
- Backend ReefPose/provider/video/workflow focus: 57 passed, one explicit GPU test skipped in the CPU-default invocation.
- Explicit Phase 2A CUDA train/register/image-inference test: passed on the RTX 3090 with 18,968,064 peak allocated bytes.
- Backend Ruff format: 691 files formatted.
- Backend Ruff lint: passed.
- Backend mypy: 419 source files passed.

The full backend suite in the dependency-complete verification environment produced `1397 passed, 38 skipped, 13 failed` with pytest's default long Windows temporary root. Investigation classified the failures as follows:

- Six pose-interoperability runtime failures require optional `sleap-io==0.9.2`, which is intentionally absent from the isolated verification environment.
- Seven segmentation/skeleton/video-export/telemetry tests consistently failed with Windows deep-path `FileNotFoundError`/`WinError 3`. The exact seven tests passed (`7 passed`) when rerun with the short isolated base temp `C:\rv2b-phase2b-20261108`, confirming a Windows path-length verification limitation rather than a ReefPose regression.

## Remaining limitations and Phase 2C recommendation

- Scientific performance remains unvalidated without real, independently held-out labeled animal data.
- ReefPose-S remains a single-animal model; native video execution assigns the single animal a stable provider track ID and does not solve multi-animal identity association.
- The GUI shows persisted losses and metrics but does not yet provide per-keypoint accuracy, calibration, model comparison, or promotion gates on a held-out biological validation set.
- The full packaged Tauri desktop should receive a manual acceptance pass when Windows browser/desktop automation is available.
- Windows CI should use a short pytest base temp or enable long paths; optional interoperability should run in its dedicated `sleap-io==0.9.2` job.

Recommended Phase 2C: add a scientifically explicit evaluation and promotion workflow—held-out immutable validation datasets, per-keypoint distance/PCK-style metrics in source coordinates, confidence calibration, model-to-model comparison, and a human-approved promotion gate—then validate it with a small real labeled animal dataset while preserving the synthetic engineering suite.
