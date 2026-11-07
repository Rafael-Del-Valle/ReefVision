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
- Training run: `a43db311-7bc3-4030-8908-e750ffcb0b42`
- Training job: `1af2f373-100c-4290-b792-89d19ac98139`
- Registered model: `6ebd9eb8-9dc2-4378-aa90-ed0f7cad61e1`
- Best checkpoint SHA-256: `3a346cadc791c671b3cdea226bd9a0dedb9dced0bdb487aca1ba865fdf6b1ac7`
- End-to-end train/register/inference wall time: 2.1645 seconds
- Peak allocated GPU memory: 18,968,064 bytes (18.09 MiB)
- Registered inference result: one detection with two source-image-coordinate keypoints on a 96x64 synthetic image
- Final synthetic selection loss: 0.1654775888

This is an engineering fixture only. It does not validate biological or scientific accuracy.

## Automated validation

- Native Workflow, cancellation/resume, schema drift, rollback, registration, inference, saved replay, Phase 1, existing Phase 10C, and Ultralytics initialization/compatibility: `75 passed`.
- Phase 1 plus registered provider tests in the dependency-complete verification environment: `39 passed`.
- Explicit RTX 3090 vertical slice: `1 passed`.
- Ruff lint: passed for all `apps/api` files.
- Ruff format check: passed for all `apps/api` files after formatting the Phase 2A changes.
- Mypy: passed for all 419 backend source files.

Repository-wide pytest result: `1392 passed, 38 skipped, 13 failed` in 713.95 seconds.

The 13 failures are not Phase 2A regressions:

- Six pose-interoperability integration failures require optional `sleap-io==0.9.2`, which was intentionally not installed into the verification environment.
- Seven unrelated failures were Windows deep-temporary-path failures in segmentation training, skeleton export/records/skeletonization, annotated-video export, and telemetry upload. Rerunning those exact seven tests with `--basetemp C:\rvpt` produced `7 passed`.

The GPU-only environment `C:\AI-Projects\venvs\reefpose` remains unchanged. It has PyTorch/CUDA but lacks pytest, SQLAlchemy, and the rest of ReefVision's service dependencies. Service tests ran in the isolated `C:\AI-Projects\venvs\reefpose-phase2a-verification` environment. Frontend checks were invoked but could not start because `apps/web/node_modules` is absent (`prettier`, `tsc`, and `vitest` not found); no frontend files changed in Phase 2A.

## Remaining integration work

- Add a provider selector and provider-specific configuration form to the Workflow Builder GUI; the executable graph contract already accepts `provider_id=reefpose`.
- Add Model Hub presentation for native training/resume details and ReefPose-specific metrics.
- Decide whether generic background-job recovery should expose a UI action for cancelled ReefPose runs; the service retry contract is implemented.
- Validate accuracy, calibration, and generalization with real labeled animal datasets before any scientific-performance claim.
- Consider enabling Windows long paths or shortening the repository-wide pytest temporary root in CI.
