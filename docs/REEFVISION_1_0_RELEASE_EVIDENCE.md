# ReefVision 1.0 Release Evidence

This checklist separates software correctness, package readability, installed-Windows behavior, and scientific validation. `PASS` means evidence has actually been produced for the code/package under discussion; old evidence is retained as baseline context but is not promoted to the current head after relevant code or dependency changes.

## Automated software gate

| Evidence | Status | Current evidence |
| --- | --- | --- |
| Backend lint and format | RECHECK REQUIRED | A complete local Ruff/Ruff-format gate passed before the segmentation/classification/tracking/Active-Learning/Scale-Assistant preparation. The current head adds calibration services, schemas, tests, and acceptance harnesses and has not yet received the full local gate. |
| Backend strict typing | RECHECK REQUIRED | A complete local mypy gate passed before the current release-evidence and Scale Assistant changes. Re-run strict typing on the current head. |
| Backend tests | RECHECK REQUIRED | 267 tests passed on the earlier release-hardening baseline. New Scale Assistant, Project Exchange, packaged-runtime, segmentation/classification/tracking/Active-Learning, and calibration tests have since been added. |
| Project Exchange and typed 3D regressions | BASELINE PASS / RECHECK REQUIRED | Restart-safe exchange and calibrated 3D workflow regressions passed on the earlier baseline. A new Scale Assistant calibration/profile round-trip regression now also requires execution. |
| Alembic round trip | BASELINE PASS / RECHECK REQUIRED | Blank database upgrade to `0024`, downgrade to base, and re-upgrade passed on the earlier baseline. No new database migration was required for image-scale calibration because accepted calibration/profile metadata lives on `ImageAsset.metadata_json`; rerun the migration gate on the current head. |
| Frontend format and typecheck | RECHECK REQUIRED | The previous frontend passed Prettier and TypeScript. The current head now includes the Scale Assistant UI/API and new tests, so the frontend gate must be rerun. |
| Frontend unit tests | RECHECK REQUIRED | 89 tests passed on the earlier baseline. New Scale Assistant review and stale-image safety tests have been added since then. |
| Frontend Chromium E2E | BASELINE PASS / RECHECK REQUIRED | 7 E2E tests passed on the earlier baseline; rerun after current UI changes. |
| Frontend production build | BASELINE PASS / RECHECK REQUIRED | Vite production build passed on the earlier baseline; rerun on the current head. |
| Hosted GitHub Actions | BLOCKED | Jobs receive no runner because of the repository/account billing or spending-limit restriction. No hosted result should be inferred for the current head. |

### Current-head local software gate

Use the ReefVision Python 3.12 virtual environment, not the global Anaconda Python:

```powershell
.\.venv\Scripts\python.exe -m ruff check apps/api
.\.venv\Scripts\python.exe -m ruff format --check apps/api
.\.venv\Scripts\python.exe -m mypy apps/api/reefvision
.\.venv\Scripts\python.exe -m pytest apps/api/reefvision/tests -q

npm --prefix apps/web run format:check
npm --prefix apps/web run typecheck
npm --prefix apps/web test -- --run
npm --prefix apps/web run build
```

Also execute the focused Scale Assistant regressions before release:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  apps/api/reefvision/tests/test_image_scale_calibration.py `
  apps/api/reefvision/tests/test_scale_calibration_contract.py `
  apps/api/reefvision/tests/test_image_scale_project_exchange_v1.py -q
```

## MSI package verification

The last verified MSI predates the current Scale Assistant packaging change. ReefVision now pins `opencv-contrib-python==4.12.0.88` instead of base `opencv-python` so the desktop package can expose `cv2.aruco`, and the packaged sidecar self-test now fails if that module is absent. Therefore the old MSI remains useful baseline evidence but is not current-head package evidence.

| Evidence | Status | Current evidence |
| --- | --- | --- |
| Windows MSI build | REBUILD REQUIRED | Earlier `ReefVision_1.7.0_x64_en-US.msi` plus eight nonempty external cabinets built successfully, but it predates the contrib/runtime change. |
| Administrative extraction | BASELINE PASS / RECHECK REQUIRED | Earlier package extracted 18,924 files; longest path 184 characters; Error 1304 was not reproduced. Repeat after the current package rebuild. |
| Required packaged resources | RECHECK REQUIRED | Desktop executable, sidecar, catalog, Alembic config, migrations, and bundled-model manifest were verified previously. Current package must additionally pass the Scale Assistant `cv2.aruco` self-test. |
| Packaged backend self-test | RECHECK REQUIRED | The self-test now validates provider imports, OpenAPI construction, migrations, and the OpenCV-contrib ArUco runtime. The current package has not yet been rebuilt/run. |
| Clean-install harness unit tests | BASELINE PASS / RECHECK REQUIRED | 11 path-safety, command, report, skip, failure, and cleanup-boundary assertions passed previously; rerun on current head. |

Administrative extraction is not clean installation evidence.

## Clean Windows machine

Run `scripts/acceptance-windows-clean-install.ps1` only from an elevated PowerShell session on a disposable Windows VM or machine with no existing ReefVision registration. The harness writes structured evidence to `.artifacts/windows-clean-acceptance-*/report.json`.

| Evidence | Status | Required evidence |
| --- | --- | --- |
| Clean MSI install and shortcuts | NOT RUN | Disposable-machine harness report from the rebuilt current-head installer |
| First desktop launch and backend startup | NOT RUN | Isolated acceptance data root, migrated database, responsive packaged API, and successful packaged self-test |
| Project/image/annotation creation | NOT RUN | Synthetic image and durable IDs in harness report |
| Restart and persistence | NOT RUN | Same project, image, and annotation after desktop restart |
| Project Exchange export | NOT RUN | Nonempty inspectable archive with manifest |
| Upgrade from a previous MSI | SKIPPED | Previous installer has not been supplied; do not infer success |
| Uninstall | NOT RUN | Binaries, shortcuts, and registration removed |
| User-data retention after uninstall | NOT RUN | Isolated acceptance data remains after uninstall |

Example current-release run after rebuilding the MSI:

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\acceptance-windows-clean-install.ps1 `
  -InstallerPath .\apps\web\src-tauri\target\x86_64-pc-windows-msvc\release\bundle\msi\ReefVision_1.7.0_x64_en-US.msi `
  -AcceptanceRoot C:\reefvision-disposable-acceptance `
  -DisposableTest
```

Add `-PreviousInstallerPath C:\path\to\previous\ReefVision.msi -PreviousInstallerSupportsIsolatedAcceptance` only when the previous build implements the same marker-gated isolated data-root contract. Without a previous installer, upgrade is explicitly `SKIPPED — previous installer not supplied`; an older build that cannot isolate its data root is unsafe for this harness and requires a disposable VM snapshot plus manual evidence.

## Scientific and hardware validation

| Evidence | Status | Current evidence |
| --- | --- | --- |
| Coral detection training and inference | PASS | 16 real APAL coral-ova images and 305 YOLO boxes; YOLO11 nano, 2 CUDA epochs, registered checkpoint, 96 held-out pending proposals, and restart inference. This proves software execution, not biological performance. |
| Coral segmentation training and inference | NOT RUN | Real-data harness prepared; requires a genuine YOLO polygon coral dataset and hardware execution. |
| Coral classification training and inference | NOT RUN | Real-data whole-image harness prepared; requires a genuine biological `train/val/test/<class>` dataset and hardware execution. |
| SAM2 CPU | PASS | Verified `sam2_b.pt` executed through production Smart Mask provider on CPU. |
| SAM2 CUDA | PASS | Verified `sam2_b.pt` executed on RTX 4060 Laptop GPU with no CPU fallback. |
| Depth Anything CPU | PASS | Verified Depth Anything V2 Small snapshot executed through the production provider on CPU. |
| Depth Anything CUDA | PASS | Verified Depth Anything V2 Small snapshot executed on RTX 4060 Laptop GPU with no CPU fallback. |
| Unavailable-device recovery | PASS | Production device resolver rejected `cuda:99` without fallback. |
| CUDA out-of-memory recovery | NOT RUN | No explicit production recovery contract; unsafe real OOM was not attempted. |
| ByteTrack benchmark against scored footage | NOT RUN | Production comparison harness is prepared for real video plus manually scored bounding-box tracks. |
| BoT-SORT benchmark against scored footage | NOT RUN | Same shared-detector/scored-footage harness will evaluate the production BoT-SORT path. |
| Active Learning equal-budget comparison | NOT RUN | Production uncertainty acquisition versus deterministic random sampling at the identical annotation budget is prepared. Active Learning is not required to win for software correctness. |
| Physical and metric-depth calibration validation | NOT RUN | Known-distance 2D and independently supplied metric-depth 3D validation harness is prepared. Relative monocular depth is never accepted as metric evidence. |
| Scale Assistant ruler accuracy | NOT RUN | Software detector/regression coverage exists; real rulers with independently known spacing must quantify scale error across orientation, lighting, image resolution, and perspective. |
| Scale Assistant ArUco/ChArUco accuracy | NOT RUN | Current provider stack now requests OpenCV contrib and the package self-test requires `cv2.aruco`; real printed references must still validate scale/homography error. |
| Perspective-corrected coral measurement accuracy | NOT RUN | Validate polygon area/perimeter/TLE on independent planar targets at known oblique views. Raster masks intentionally remain scalar unless a future workflow explicitly resamples them. |
| Camera/setup profile repeatability | NOT RUN | Validate repeated same-setup images and deliberate setup changes; reuse requires exact resolution plus explicit researcher confirmation. |
| Scale Assistant Project Exchange round trip | TEST PREPARED | Regression verifies source calibration homography/provenance, remapped profile-source image IDs, scalar-only reused profiles, and independence of the imported project. Execute in the current-head backend gate. |

Hardware evidence generated 2026-08-19 on Windows 11 with PyTorch 2.5.1+cu121,
Transformers 4.57.2, and an NVIDIA GeForce RTX 4060 Laptop GPU (8 GiB VRAM):
`.artifacts/model-provider-acceptance-20260819T202023Z/report.json`. The deterministic
synthetic input establishes provider and hardware execution only, not biological accuracy.
Depth Anything remains relative monocular depth and is not metric physical depth unless
separately calibrated.

Depth Anything used official model `depth-anything/Depth-Anything-V2-Small-hf` at
revision `5426e4f0f36572d16453bbda7a8389317b1bef99`. ReefVision verified all three
managed snapshot files (99,175,385 bytes total). CPU load plus inference took 11.885
seconds; CUDA load plus inference took 0.660 seconds and peaked at 207,890,944 bytes.

Coral detection acceptance used the local APAL `InitialModel` dataset: 11 train,
3 validation, and 2 test images (205/60/40 boxes), all 3840×2160, with the `Egg`
class. ReefVision trained YOLO11 nano from scratch for two epochs on the RTX 4060
in 39.096 seconds, peaking at 401,026,560 allocated CUDA bytes. The deliberately
bounded run reported precision, recall, mAP50, and mAP50-95 of 0; this is a software
execution PASS, not a scientific-performance claim. The registered model produced
96 pending proposals on two held-out images at the recorded 0.001 smoke threshold
and loaded successfully in a fresh application instance. Full hashes, lineage,
configuration, metrics, and IDs are in
`.artifacts/coral-detection-acceptance-20260819-170915/report.json`.

## Prepared real-data acceptance harnesses

Real coral instance-segmentation acceptance is prepared in
`scripts/acceptance_coral_segmentation.py`. The harness refuses box-only YOLO labels,
requires explicit train/validation/test polygon splits, preserves source image and
label hashes in an isolated ReefVision data root, trains through the task-aware
segmentation worker, registers the resulting segmenter, requires held-out polygon-mask
proposals, accepts one through ReefVision's normal human-review path, and verifies both
the registered model and accepted mask after application restart. The segmentation
exporter uses paths relative to `data.yaml`, matching the portable contract already
proven by real detection acceptance.

Real biological whole-image classification acceptance is prepared in
`scripts/acceptance_coral_classification.py`. It requires explicit
`train/<class>`, `val/<class>`, and `test/<class>` directories with at least two
classes represented in every split. It freezes human ground truth in a dedicated label
set, trains and registers a production classifier, runs held-out top-k inference, records
held-out top-1 accuracy, reviews one prediction into a separate model-review label set,
and verifies restart persistence.

Real fish-tracking comparison is prepared in `scripts/acceptance_fish_tracking.py`.
The same registered detector checkpoint and thresholds are used for production ByteTrack
and BoT-SORT jobs, and both are evaluated against the same manually scored track truth.

The equal-budget detection Active Learning experiment is prepared in
`scripts/acceptance_active_learning_detection.py`. It compares the production
`uncertainty` acquisition path with deterministic random sampling using the identical
annotation budget, then retrains both arms independently against the same held-out test
set. The observed metric delta is evidence; a positive delta is not a software-pass
requirement.

Known-distance/metric-depth validation is prepared in
`scripts/acceptance_physical_calibration.py`. It compares calibrated 2D track analytics
and camera-intrinsics plus externally supplied metric-depth 3D analytics with independent
expected values under explicit tolerances and verifies persistence after restart.

Synthetic software tests do not establish biological accuracy, tracking quality,
calibration accuracy, or hardware-provider readiness.
