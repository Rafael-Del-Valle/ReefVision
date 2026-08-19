# ReefVision 1.0 Release Evidence

This checklist separates software correctness, package readability, installed-Windows behavior, and scientific validation. `PASS` means evidence has actually been produced; it does not transfer between categories.

## Automated software gate

| Evidence | Status | Current evidence |
| --- | --- | --- |
| Backend lint and format | PASS | Local Ruff and Ruff format gate at `0771ca2`; focused recheck required after segmentation/classification preparation changes |
| Backend strict typing | PASS | Local mypy gate at `0771ca2`; focused recheck required after segmentation/classification preparation changes |
| Backend tests | PASS | 267 tests passed locally before segmentation/classification preparation changes; focused recheck required |
| Project Exchange and typed 3D regressions | PASS | Focused restart-safe exchange and 3D workflow tests passed locally |
| Alembic round trip | PASS | Blank database upgrade to `0024`, downgrade to base, and re-upgrade passed |
| Frontend format and typecheck | PASS | Local Prettier and TypeScript gates passed |
| Frontend unit tests | PASS | 89 tests passed locally |
| Frontend Chromium E2E | PASS | 7 tests passed locally |
| Frontend production build | PASS | Vite production build passed locally |
| Hosted GitHub Actions | BLOCKED | Jobs receive no runner because of the repository/account billing or spending-limit restriction |

## MSI package verification

| Evidence | Status | Current evidence |
| --- | --- | --- |
| Windows MSI build | PASS | `ReefVision_1.7.0_x64_en-US.msi` plus eight nonempty external cabinets |
| Administrative extraction | PASS | 18,924 files extracted; longest path 184 characters; Error 1304 not reproduced |
| Required packaged resources | PASS | Desktop executable, sidecar, catalog, Alembic config, 25 migrations, and bundled-model manifest verified |
| Packaged backend self-test | PASS | Provider imports, OpenAPI construction, and migrated SQLite creation passed |
| Clean-install harness unit tests | PASS | 11 path-safety, command, report, skip, failure, and cleanup-boundary assertions passed |

Administrative extraction is not clean installation evidence.

## Clean Windows machine

Run `scripts/acceptance-windows-clean-install.ps1` only from an elevated PowerShell session on a disposable Windows VM or machine with no existing ReefVision registration. The harness writes structured evidence to `.artifacts/windows-clean-acceptance-*/report.json`.

| Evidence | Status | Required evidence |
| --- | --- | --- |
| Clean MSI install and shortcuts | NOT RUN | Disposable-machine harness report |
| First desktop launch and backend startup | NOT RUN | Isolated acceptance data root, migrated database, responsive packaged API |
| Project/image/annotation creation | NOT RUN | Synthetic image and durable IDs in harness report |
| Restart and persistence | NOT RUN | Same project, image, and annotation after desktop restart |
| Project Exchange export | NOT RUN | Nonempty inspectable archive with manifest |
| Upgrade from a previous MSI | SKIPPED | Previous installer has not been supplied; do not infer success |
| Uninstall | NOT RUN | Binaries, shortcuts, and registration removed |
| User-data retention after uninstall | NOT RUN | Isolated acceptance data remains after uninstall |

Example current-release run:

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
| Coral detection training and inference | PASS | 16 real APAL coral-ova images and 305 YOLO boxes; YOLO11 nano, 2 CUDA epochs, registered checkpoint, 96 held-out pending proposals, and restart inference |
| Coral segmentation training and inference | NOT RUN | Real-data harness prepared; requires a genuine YOLO polygon coral dataset and hardware execution |
| Coral classification training and inference | NOT RUN | Real-data whole-image harness prepared; requires a genuine biological train/val/test class-folder dataset and hardware execution |
| SAM2 CPU | PASS | Verified `sam2_b.pt` executed through production Smart Mask provider on CPU |
| SAM2 CUDA | PASS | Verified `sam2_b.pt` executed on RTX 4060 Laptop GPU with no CPU fallback |
| Depth Anything CPU | PASS | Verified Depth Anything V2 Small snapshot executed through the production provider on CPU |
| Depth Anything CUDA | PASS | Verified Depth Anything V2 Small snapshot executed on RTX 4060 Laptop GPU with no CPU fallback |
| Unavailable-device recovery | PASS | Production device resolver rejected `cuda:99` without fallback |
| CUDA out-of-memory recovery | NOT RUN | No explicit production recovery contract; unsafe real OOM was not attempted |
| ByteTrack benchmark against scored footage | NOT RUN | Scored-footage validation remains outstanding |
| BoT-SORT benchmark against scored footage | NOT RUN | Scored-footage validation remains outstanding |
| Active Learning equal-budget comparison | NOT RUN | Scientific comparison remains outstanding |
| Physical and metric-depth calibration validation | NOT RUN | Calibration validation remains outstanding |

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

Real coral instance-segmentation acceptance is prepared in
`scripts/acceptance_coral_segmentation.py`. The harness refuses box-only YOLO labels,
requires explicit train/validation/test polygon splits, preserves source image and
label hashes in an isolated ReefVision data root, trains through the task-aware
segmentation worker, registers the resulting segmenter, requires held-out polygon-mask
proposals, accepts one through ReefVision's normal human-review path, and verifies both
the registered model and accepted mask after application restart. The segmentation
exporter now uses paths relative to `data.yaml`, matching the portable contract already
proven by real detection acceptance. This evidence row remains `NOT RUN` until a
genuine biological polygon dataset and hardware execution produce a JSON report.

Example future segmentation hardware run:

```powershell
.\.venv\Scripts\python.exe .\scripts\acceptance_coral_segmentation.py `
  --dataset C:\path\to\real-coral-yolo-segmentation `
  --output .\.artifacts\coral-segmentation-acceptance-<timestamp> `
  --biological-context "Real coral imagery with manually verified polygon masks"
```

Real biological whole-image classification acceptance is prepared in
`scripts/acceptance_coral_classification.py`. It requires explicit
`train/<class>`, `val/<class>`, and `test/<class>` directories with at least two
classes represented in every split. The harness creates human-verified image labels
in a dedicated ground-truth label set, freezes an immutable ReefVision dataset,
materializes the production classification dataset, trains and automatically registers
a classifier, runs held-out top-k inference, records held-out top-1 accuracy as evidence,
reviews one prediction into a separate model-review label set so the ground truth is not
overwritten, and verifies the model and reviewed label after application restart. The
classification row remains `NOT RUN` until real biological data and hardware execution
produce a JSON report.

Example future classification hardware run:

```powershell
.\.venv\Scripts\python.exe .\scripts\acceptance_coral_classification.py `
  --dataset C:\path\to\real-biological-classification `
  --output .\.artifacts\coral-classification-acceptance-<timestamp> `
  --biological-context "Real biological imagery with manually verified image-level classes"
```

Synthetic software tests do not establish biological accuracy, tracking quality, calibration accuracy, or hardware-provider readiness.
