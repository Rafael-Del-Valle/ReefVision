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
3. **Camera JPEG:** Test actual original JPEGs from Canon EOS RP and Sony A7R III, with explicit consent to use those fixtures. Include `.jpg`, `.jpeg`, `.JPG`, `.JPEG`, mixed-case suffixes, EXIF orientation 1/3/6/8, Unicode names, and filenames containing spaces. Verify thumbnail, full-resolution preview, EXIF orientation, import/reopen, and no original-file mutation. Archive fixture hashes before and after.
4. **Read-only external PowerShell console:** Start a real local training job on user-owned weights/dataset. Open the separate PowerShell observer and verify it displays the correct job ID, live timestamped logs, and actual box/cls/dfl losses when the selected training architecture emits them. Compare displayed values against source job logs. Close or crash the observer; training must continue uninterrupted. Confirm observer cannot issue pause, stop, delete, shell injection, or filesystem writes to training artifacts.
5. **GPU/scientific acceptance:** On a Windows machine with the intended NVIDIA GPU, record `nvidia-smi`, driver/CUDA/PyTorch versions, inference/training output, memory use, and a known held-out scientific fixture. Verify class mapping, annotation immutability, QC uncertainty, experimental-unit attribution, and dataset/model provenance. Do not report mAP, timing, or agreement without fixture identity and actual measurements.

## Evidence ledger

| Candidate SHA | Gate | Outcome | Evidence |
| --- | --- | --- | --- |
| `cfaa4e2e70b6ebb190d6397cbebb5aacc32dfcc9` | Camera/gallery Actions | PASS (automated only) | [run 42404476072](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/42404476072) |
| `cfaa4e2e70b6ebb190d6397cbebb5aacc32dfcc9` | General CI | FAIL: frontend formatting; backend passed | [run 42404476071](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/42404476071) |
| Not yet recorded | Clean MSI/CAB install, WebView2, physical camera, PowerShell observer, GPU/science | UNVERIFIED | Attach reproducible logs and screenshots before release |

A passing subset on an older SHA is not a release gate for a newer SHA. Do not merge, tag, publish, or install a release without explicit owner approval.
