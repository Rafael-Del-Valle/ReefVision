# ReefVision 1.0 Release Evidence

This checklist separates software correctness, package readability, installed-Windows behavior, and scientific validation. `PASS` means evidence has actually been produced; it does not transfer between categories.

## Automated software gate

| Evidence | Status | Current evidence |
| --- | --- | --- |
| Backend lint and format | PASS | Local Ruff and Ruff format gate at `0771ca2` |
| Backend strict typing | PASS | Local mypy gate at `0771ca2` |
| Backend tests | PASS | 267 tests passed locally |
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
| Coral detection training and inference | NOT RUN | Biological validation remains outstanding |
| Coral segmentation training and inference | NOT RUN | Biological validation remains outstanding |
| Coral classification training and inference | NOT RUN | Biological validation remains outstanding |
| SAM2 CPU | PASS | Verified `sam2_b.pt` executed through production Smart Mask provider on CPU |
| SAM2 CUDA | PASS | Verified `sam2_b.pt` executed on RTX 4060 Laptop GPU with no CPU fallback |
| Depth Anything CPU | BLOCKED | No verified Depth Anything V2 checkpoint is cataloged or staged |
| Depth Anything CUDA | BLOCKED | No verified Depth Anything V2 checkpoint is cataloged or staged |
| Unavailable-device recovery | PASS | Production device resolver rejected `cuda:99` without fallback |
| CUDA out-of-memory recovery | NOT RUN | No explicit production recovery contract; unsafe real OOM was not attempted |
| ByteTrack benchmark against scored footage | NOT RUN | Scored-footage validation remains outstanding |
| BoT-SORT benchmark against scored footage | NOT RUN | Scored-footage validation remains outstanding |
| Active Learning equal-budget comparison | NOT RUN | Scientific comparison remains outstanding |
| Physical and metric-depth calibration validation | NOT RUN | Calibration validation remains outstanding |

Hardware evidence generated 2026-08-19 on Windows 11 with PyTorch 2.5.1+cu121,
Transformers 4.57.2, and an NVIDIA GeForce RTX 4060 Laptop GPU (8 GiB VRAM):
`.artifacts/model-provider-acceptance-20260819T200343Z/report.json`. The deterministic
synthetic input establishes provider and hardware execution only, not biological accuracy.
Depth Anything remains relative monocular depth and is not metric physical depth unless
separately calibrated.

Synthetic software tests do not establish biological accuracy, tracking quality, calibration accuracy, or hardware-provider readiness.
