# ReefPose Phase 2A Validation

Validated on 2026-11-07 on branch `feature/reefpose-core`.

## Implemented vertical slice

The existing Workflow Builder path now supports:

`Frozen Pose Dataset -> Train Pose Model (provider=reefpose) -> Register Trained Model`

The training node executes the native Phase 1 ReefPose-S PyTorch trainer. It revalidates the immutable dataset manifest and exact landmark schema at execution, supports random initialization and provider-matched registered checkpoints, reports epoch progress, cooperatively cancels, resumes cancelled native runs from a non-registrable checkpoint, preserves the historical best checkpoint, and persists metrics/logs/reproducibility/artifact provenance. Only a completed best checkpoint can be registered.

The existing Ultralytics provider remains the default when `provider_id` is omitted. Its YOLO11 configuration and execution path were not replaced.

## RTX 3090 acceptance evidence

Command:

```powershell
$env:REEFPOSE_RUN_GPU_TESTS='1'
C:\AI-Projects\venvs\reefpose-phase2a-verification\Scripts\python.exe -m pytest apps/api/reefvision/tests/test_workflow_pose_training_phase10.py::test_native_reefpose_cuda_workflow_registration_and_inference -q -s
```

Result: `1 passed`.

- Device: NVIDIA GeForce RTX 3090
- PyTorch: 2.11.0+cu128
- CUDA runtime reported by PyTorch: 12.8
- Precision: CUDA AMP
- Synthetic fixture: one immutable verified pose sample, two landmarks, 64x64 network input, one training epoch
- Training run: `0cc58f2c-bb80-430f-b1d6-3e38872696e5`
- Training job: `44f06b39-d550-405b-8930-cccf31ec66ee`
- Registered model: `939efef0-7ab4-4b6c-b8dd-d75c0df8ce00`
- Best checkpoint SHA-256: `3ade9bbe4fac5088aa1fc3a8b6ebffff44cac184af945bbaae5abade22759881`
- End-to-end train/register/inference wall time: 2.0757 seconds
- Peak allocated GPU memory: 18,968,064 bytes (18.09 MiB)
- Registered inference result: one detection with two source-image-coordinate keypoints on a 96x64 synthetic image
- Final synthetic selection loss: 0.1709549725

This is an engineering fixture only. It does not validate biological or scientific accuracy.

## Automated validation

- Native Workflow, cancellation/resume, schema drift, rollback, registration, inference, saved replay, Phase 1, existing Phase 10C, Ultralytics initialization/compatibility, and existing semantic/segmentation dispatch: `73 passed, 1 skipped` (the explicit CUDA test is the skip).
- Phase 1 plus registered provider tests in the dependency-complete verification environment: `39 passed`.
- Explicit RTX 3090 vertical slice: `1 passed`.
- Ruff lint: passed for all `apps/api` files.
- Ruff format check: passed for all `apps/api` files after formatting the Phase 2A changes.
- Mypy: passed for all 419 backend source files.

Repository-wide pytest result with a short Windows temporary root: `1402 passed, 38 skipped, 7 failed` in 702.53 seconds.

The seven failures are not Phase 2A regressions:

- Six pose-interoperability integration failures require optional `sleap-io==0.9.2`, which was intentionally not installed into the verification environment.
- One unrelated annotation event-ordering assertion failed in the full run and passed immediately when rerun alone (`1 passed`). The test orders multiple same-clock events by timestamp and UUID, so this is a pre-existing nondeterministic ordering failure.

An earlier default-temporary-root run also exposed seven unrelated Windows deep-path failures in segmentation training, skeleton export/records/skeletonization, annotated-video export, and telemetry upload. Those exact tests passed with `--basetemp C:\rvpt`; the final full run used the short root and did not reproduce them.

## Independent review corrections

The final read-only review identified and drove regression coverage for recovery and reproducibility edge cases. The corrected implementation now routes retried pose jobs through the normal worker, verifies the queued split-manifest hash and both dataset hashes, preserves historical-best checkpoints plus prior logs and metrics across cancellation, treats registered checkpoints as weight-only initialization, honors seed zero before model construction, and completes post-training finalization retries without rerunning an already-complete epoch range.

The GPU-only environment `C:\AI-Projects\venvs\reefpose` remains unchanged. It has PyTorch/CUDA but lacks pytest, SQLAlchemy, and the rest of ReefVision's service dependencies. Service tests ran in the isolated `C:\AI-Projects\venvs\reefpose-phase2a-verification` environment. Frontend checks were invoked but could not start because `apps/web/node_modules` is absent (`prettier`, `tsc`, and `vitest` not found); no frontend files changed in Phase 2A.

## Remaining integration work

- Add a provider selector and provider-specific configuration form to the Workflow Builder GUI; the executable graph contract already accepts `provider_id=reefpose`.
- Add Model Hub presentation for native training/resume details and ReefPose-specific metrics.
- Decide whether generic background-job recovery should expose a UI action for cancelled ReefPose runs; the service retry contract is implemented.
- Validate accuracy, calibration, and generalization with real labeled animal datasets before any scientific-performance claim.
- Consider enabling Windows long paths or shortening the repository-wide pytest temporary root in CI.
