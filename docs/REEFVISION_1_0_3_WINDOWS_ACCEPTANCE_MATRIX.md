# ReefVision 1.0.3 — Windows release-blocker acceptance matrix

Status: **NOT RELEASE-READY**. This is a reproducible evidence checklist, not a claim that the tests have passed. Keep original datasets immutable and run acceptance against a disposable test project. Record the exact tested commit SHA, Windows build, driver, GPU, camera files, installer hash, timestamp, and operator for each result.

## Automated gates (must all pass on the same candidate SHA)

| Gate | Evidence required |
| --- | --- |
| Frontend | `npm run format:check`, typecheck, unit tests, and production build all successful |
| Backend | API, database migrations (upgrade and rollback where supported), immutable originals, and training job API tests successful |
| Rust / desktop | Rust tests and Tauri build successful; no unapproved network downloads |
| Workflow Builder | Typed saved graph round-trip, invalid-edge rejection, executable node integration, and provenance persistence tests successful |
| Browser | Chromium first-image load, gallery scroll/wheel and selection retention, page boundaries, and JPEG alias tests successful |
| Windows packaging | MSI and CAB produced by the same SHA, with SHA-256 hashes and installer logs archived |

## Windows GUI and real-camera acceptance (manual; evidence mandatory)

1. **Clean install:** Use a fresh Windows 11 VM or machine with no prior ReefVision app data. Install the exact candidate MSI without developer tools. Capture installer logs, CAB verification, file hashes, WebView2 runtime version, and screenshot of the launched application. Confirm offline launch and clean uninstall/reinstall.
2. **Initial image:** Import a small immutable fixture set containing one image and a multi-page set. Open the project from a cold launch; the first image must render in the viewport without manually selecting a thumbnail. Scroll the gallery with the wheel and scrollbar, switch pages, reopen the project, and verify the selected image and viewport remain synchronized.
3. **Camera JPEG:** Follow the [physical-camera, extension-routing and duplicate negative-control cohorts](acceptance/REEFVISION_103_WINDOWS_RELEASE_EVIDENCE.md#separate-physical-camera-and-alias-routing-cohorts). Use distinct, owner-approved unmodified Canon EOS RP and Sony A7R III captures where available; preserve native filenames and extensions. Test `.jpg`, `.jpeg`, `.jpe`, `.jfif`, `.jfi`, `.jif`, upper/mixed case, EXIF orientation 1/3/6/8, Unicode names and spaces using separately inventoried alias fixtures where needed. Never count renamed copies as independent captures. Record unavailable camera models or fixture characteristics as coverage gaps, not passes. Verify thumbnail, full-resolution preview, EXIF orientation, import/reopen and no source mutation using the decoded pre/post inventories and independently retained baseline SHA-256.
4. **Read-only external PowerShell console:** Start a real local training job on user-owned weights/dataset. Open the separate PowerShell observer and verify it displays the correct job ID, live timestamped logs, and actual box/cls/dfl losses when the selected training architecture emits them. Compare displayed values against source job logs. Close or crash the observer; training must continue uninterrupted. Confirm observer cannot issue pause, stop, delete, shell injection, or filesystem writes to training artifacts.
5. **GPU/scientific acceptance:** On a Windows machine with the intended NVIDIA GPU, record `nvidia-smi`, driver/CUDA/PyTorch versions, inference/training output, memory use, and a known held-out scientific fixture. Verify class mapping, annotation immutability, QC uncertainty, experimental-unit attribution, and dataset/model provenance. Do not report mAP, timing, or agreement without fixture identity and actual measurements.

## Evidence ledger

| Candidate SHA | Gate | Outcome | Evidence |
| --- | --- | --- | --- |
| `cfaa4e2e70b6ebb190d6397cbebb5aacc32dfcc9` | Camera/gallery Actions | PASS (automated only) | [run 42404476072](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/42404476072) |
| `cfaa4e2e70b6ebb190d6397cbebb5aacc32dfcc9` | General CI | FAIL: frontend formatting; backend passed | [run 42404476071](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/42404476071) |
| `47e5170bac2319d5b3e9ea17d291235aeb72c7b7` | Camera/gallery Actions | PASS (2 jobs; Chromium and Windows generated JPEG regression only) | [run 45925906703](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/45925906703) |
| `47e5170bac2319d5b3e9ea17d291235aeb72c7b7` | General CI | PASS (3 jobs: backend, frontend, Windows acceptance collector) | [run 45925906728](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/45925906728) |
| Not yet recorded | Candidate MSI/CAB build and clean install | UNVERIFIED | Collector success is not evidence that the installer was built or installed. Record candidate artifact hashes, logs and machine identity. |
| Not yet recorded | Installed WebView2 initial-image/gallery and real camera | UNVERIFIED | Browser automation and generated JPEG fixtures do not certify installed WebView2 or original camera compatibility. |
| Not yet recorded | Actual training observer and process continuity | UNVERIFIED | Capture same-job source logs, loss observations and PID/checkpoint progress before and after closing the observer. |
| Not yet recorded | Physical GPU and scientific acceptance | UNVERIFIED | Record held-out fixture identity, experimental units, uncertainty and actual hardware/software measurements. |

A passing subset on an older SHA is not a release gate for a newer SHA. Do not merge, tag, publish, or install a release without explicit owner approval.
