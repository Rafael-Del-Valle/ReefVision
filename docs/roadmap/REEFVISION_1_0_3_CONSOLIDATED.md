# ReefVision 1.0.3 — consolidated usability and stability release

Status: **IN DEVELOPMENT**. This release consolidates the original 1.0.3–1.0.9 usability roadmap into one Windows desktop patch. Prior patch plans are scope groupings, **not** claims that their functionality is complete.

Baseline: approved ReefVision 1.0.2 main line, with the candidate first-open viewport fix from PR #72. Do not import the independent 1.1 environmental/oceanographic branch.

## Required release scope and evidence

- [ ] **P0 Image display and import:** first-open Gallery and annotation editor always show correct pixels, viewport bounds and aligned overlays; switching, wheel zoom, pan, fit, DPI/resizing and cold/warm cache remain stable on a Windows MSI. Preserve original images and raw pixel coordinates. Import and thumbnail/display/decode each supported extension: `.jpg`, `.jpeg`, `.jpe`, `.jfif`, `.jfi`, `.jif` (including uppercase), `.png`, `.tif`, `.tiff`, `.webp`, `.bmp`, `.dib`, static `.gif`. Check CMYK JPEG, EXIF variants, corrupt/truncated files, duplicate hashes, and explicit errors. Animated GIF and unsupported camera RAW/HEIC/JPEG2000 must not silently lose data.
- [ ] **P1 Gallery and projects (former 1.0.3):** folder/batch import status, duplicate reporting, thumbnail fallback, reliable focus/scroll/navigation, filtering, multi-select and bulk organization, last-image resume.
- [ ] **P2 Precision annotation (former 1.0.4):** magnification, fit/actual-size, geometry snapping, underlying-item selection, bulk class edits, masks/polygons/boxes, keyboard+mouse pointer correctness, large-annotation performance, undo/redo and safe persisted copy/paste.
- [ ] **P3 Review and QA (former 1.0.5):** reviewer-safe status transitions, human/model overlays, configurable review thresholds and queues, review flags, comparison, persistence and auditable verification decisions.
- [ ] **P4 Video and pose usability (former 1.0.6):** reliable video timeline/frame/keyframe navigation, responsive playback, track identity and repeated-keypoint correction, pose review, behavior visualization, safe exports.
- [ ] **P5 Calibration, measurements and export (former 1.0.7):** scale-bar detection with manual confirmation and per-image provenance, calibrated lengths/areas/counts, scientific QC, source-pixel consistency and QGIS/CSV/mask/data interchange.
- [ ] **P6 Workspace, accessibility and live training (former 1.0.8):** dockable/detachable panels, remembered per-project layout, dual-monitor and high-DPI support, keyboard accessibility; view live training metrics in-app; an explicit Windows button opens a restricted read-only PowerShell monitor for the selected training run without starting another model training process. Validate one active/completed/failed run and unavailable-terminal behavior.
- [ ] **P7 Stability and release acceptance (former 1.0.9):** crash/recovery behavior, autosave and conflict safety, active jobs, migrations, data backup/restore, installer MSI/CAB/checksums, offline Windows clean install/upgrade, startup, relaunch, GPU/CPU training, and real interactive GUI acceptance.

## Development / validation policy

1. Check whether each feature already exists before rewriting it; preserve proven earlier code and add only missing behavior.
2. Implement as small reviewed changes with deterministic regression tests. Passing CI alone is not physical Windows/RTX acceptance.
3. Preserve original imagery, mask geometry, scientific provenance, classification labels, verified-vs-predicted boundaries, and saved projects.
4. Keep development in `develop/reefvision-1.0.3-consolidated` and its draft PR. No release, merge, tag, or published installer until all P0–P7 evidence is accepted and the owner authorizes publication.
5. If a feature cannot be validated in an automated runner, document its specific Windows acceptance procedure and label the gate **UNVERIFIED**, not PASS.


## Manual acceptance record — pending physical Windows evidence

The automated CI suite is necessary but cannot establish the following installed-app behaviors. Record the exact candidate commit, Windows build, WebView2 runtime, camera model/sample hash, and installer artifact checksum for every run. Keep original scientific images immutable; use copies for testing.

| Gate | Reproducible procedure | Pass evidence | Current disposition |
| --- | --- | --- | --- |
| Cold image / gallery | Clean-launch installed MSI, open a project with one image and then a multi-image gallery; wheel over the strip when it both fits and overflows, switch images, resize and change DPI | Screen recording with image identity, stable pixels and overlays, no page drift; Ctrl+wheel unaffected | UNVERIFIED |
| Camera JPEG | Import real `.jpg`, `.jpeg`, `.jpe`, `.jfif`, `.jfi`, `.jif` and uppercase samples including EXIF orientation and CMYK; verify original SHA-256 before/after and raw-pixel annotations; include TIFF and PNG control samples | Camera/sample provenance, hashes, decode/thumbnail screenshots, explicit rejection evidence for malformed media | UNVERIFIED |
| Live console | Start a CPU training job with local user-trained weights; open the external PowerShell monitor during and after the job; close the monitor mid-run | Read-only job ID, real epoch/box/cls/dfl loss log excerpts, unchanged job PID/state and uninterrupted completion | UNVERIFIED |
| Installer | On a disposable Windows test environment, validate signed/hashed MSI and any external CAB, clean install, launch, relaunch, upgrade and uninstall without modifying real projects | Build SHA, checksums, install logs, WebView2 version, screenshots and retained data checks | UNVERIFIED |
| Scientific regression | Reopen a representative project and compare original hashes, mask coordinates, calibration snapshots, experimental-unit assignments, verified annotations and export provenance | Reproducible before/after comparison with documented QC and uncertainty | UNVERIFIED |

RTX 3090 GPU acceptance is **DEFERRED** until hardware is operational; it is not implied by CPU testing or CI. Do not mark the release ready while any required acceptance gate is unverified.

### Optional installed-MSI real camera JPEG evidence

On an **owner-approved disposable Windows VM only**, the clean-install acceptance
script now accepts `-CameraFixturePath` for a local representative camera JPEG.
Example (do not run on a machine with an existing ReefVision installation):

```powershell
.\scripts\acceptance-windows-clean-install.ps1 `
  -InstallerPath 'C:\staging\ReefVision_1.0.3_x64_en-US.msi' `
  -AcceptanceRoot 'C:\reefvision-clean-acceptance' `
  -DisposableTest `
  -CameraFixturePath 'C:\camera-fixtures\DSC_0001.JPEG'
```

The optional test imports the file into the isolated installed backend,
checks its reported source-pixel dimensions, compares its original SHA-256
with the bytes served by the API, verifies the source file is unchanged,
and requests the display rendition (requiring PNG for non-neutral EXIF
orientation). The evidence report records `camera_jpeg: PASS` only after
these checks; omitting the fixture records `SKIPPED`. This does **not**
establish interactive WebView2 behavior, thumbnail alignment, or coverage
of every camera codec/alias. Keep those gates **UNVERIFIED** until physically
tested. Do not use private camera imagery in CI or upload it externally.

### Training console acceptance details

For each CPU run, capture the immutable training run ID, start/end UTC timestamps, model configuration and locally registered checkpoint identity. Confirm the external PowerShell process only polls a loopback read-only endpoint, rejects malformed run IDs, and does not spawn a second training process. Compare epoch and box/classification/distribution-focal loss values against the original job log at matching steps; distinguish absent metrics from zero values. Close the console during an active epoch and verify the training PID, status transitions, checkpoints and final metrics remain unchanged. Repeat for completed, failed, and unavailable-terminal cases. Do not claim GPU acceptance from this CPU exercise.

## First development slice

- Candidate first-open viewport effect fix inherited from PR #72.
- Additional JPEG filename aliases and BMP/static GIF ingestion plus browser-safe CMYK JPEG/BMP/GIF conversion. Explicit non-destructive rejection of animated GIFs.
- Per-training-run Windows PowerShell monitor polls ReefVision's local read-only status endpoint and displays live stage/epoch/metrics. Run identifiers are validated before a shell is spawned.
- Synchronized version source metadata for staging 1.0.3.

**None of these changes is production validated merely by its presence in Git.** Automated and installed GUI verification remain mandatory.

## 2026-10-22 laptop sprint evidence (PR #81)

Release decision: **HOLD — not release-ready.** The sprint implementation and automated
quality gates passed and the final laptop-only addendum closed the technical CPU
segmentation gap, but physical Windows MSI/GUI acceptance is still unverified and the
RTX 3090 matrix is deferred. The synthetic segmentation run proves software execution,
not representative scientific accuracy. No release, merge, tag, installer publication,
or branch deletion is authorized by this record.

### Roadmap status

| Group                                         | Status         | Evidence and remaining acceptance                                                                                                                                                                                                                                                                                                                                                                 |
| --------------------------------------------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| P0 Image display and import                   | **UNVERIFIED** | Automated import/display coverage passed, including raw-pixel overlay alignment and a regression for non-neutral EXIF JPEGs. The original image bytes and metadata remain unchanged while the browser display rendition is orientation-free. Physical MSI checks for every supported extension, DPI/resizing, cold/warm cache, and corrupt-file UX remain outstanding.                            |
| P1 Gallery and projects                       | **UNVERIFIED** | Gallery first-open and long-scroll Playwright tests passed. The complete folder/batch import, focus, filtering, bulk organization, and last-image-resume matrix has not been physically exercised in the MSI.                                                                                                                                                                                     |
| P2 Precision annotation                       | **UNVERIFIED** | Automated editor tests passed, including raw source-pixel mask rendering/editing and invalid-geometry rejection. Full mouse/keyboard, snapping, performance, copy/paste, undo/redo, and high-DPI physical acceptance remains outstanding.                                                                                                                                                         |
| P3 Review and QA                              | **UNVERIFIED** | Revision-checked track-mask review persistence and relevant automated UI/API tests passed. The complete reviewer queue, threshold, comparison, audit, and installed interactive workflow has not been physically accepted.                                                                                                                                                                        |
| P4 Video and pose usability                   | **UNVERIFIED** | Detection, segmentation, and hybrid fusion code is automated-test ready. Class-aware fusion accepts only mutual unique-best overlaps and leaves equal-overlap crossing ambiguities unmatched for review. Physical playback/timeline/pose/export acceptance remains outstanding.                                                                                                                   |
| P5 Calibration, measurements and export       | **UNVERIFIED** | The full backend and browser suites passed without a sprint-specific P5 regression. That is not a substitute for physical scale-bar, measurement, scientific QC, and interchange acceptance.                                                                                                                                                                                                      |
| P6 Workspace, accessibility and live training | **UNVERIFIED** | Training metrics now retain all available train/validation loss series, and the exact **Open Training Console** action launches a restricted, read-only status monitor without starting training. Unit/UI/build checks passed; active/completed/failed run display, unavailable-terminal behavior, detachable panels, dual-monitor, DPI, and keyboard accessibility remain physically unverified. |
| P7 Stability and release acceptance           | **BLOCKED**    | Automated gates, migration round-trip, production build, clean installer build, administrative extraction, extracted-desktop/backend launch, migration, project persistence, and Project Exchange passed. Physical clean install/upgrade/relaunch/uninstall and interactive P0-P7 GUI acceptance still require a disposable Windows host. RTX 3090 checks are **DEFERRED**.                       |

### Sprint feature readiness

- **Detection training — PASS on CPU:** a real two-epoch laptop run completed training,
  validation, checkpoint creation, model registration, held-out inference, and proposal
  creation.
- **Segmentation training — PASS for technical CPU execution:** a deterministic,
  byte-distinct two-class synthetic dataset used 20 training, 5 validation, and 5
  held-out images. A 25-epoch CPU run completed training and validation, registered the
  checkpoint, produced 44 valid pending held-out polygon proposals, persisted an
  explicitly accepted mask, and repeated inference after restart. Dataset
  representativeness and scientific segmentation acceptance remain **UNVERIFIED**.
- **Detection tracking — PASS for automated readiness:** existing tracker execution and
  API persistence passed the video suite.
- **Segmentation tracking — PASS for automated readiness:** source-pixel masks persist,
  render on exact frames, validate, and save through revision-checked APIs.
- **Hybrid tracking — PASS for automated readiness:** detector and segmenter trackers run
  independently, then fuse same-class identities only when overlap evidence is mutually
  unique. Ambiguous crossings remain separate instead of receiving arbitrary IDs.
- **Image import/loading — PASS for automated readiness:** import/display tests passed;
  non-neutral EXIF JPEG display no longer lets browser orientation diverge from raw-pixel
  overlays. Installed physical codec/viewport acceptance remains **UNVERIFIED**.

### Fresh automated evidence

- Ruff: **PASS** (663 Python files formatted/checked).
- mypy strict package check: **PASS** (409 source files).
- Pytest: **PASS** — 1,204 passed, 32 skipped, 1 Starlette deprecation warning.
  Skips are opt-in/live-model integration cases, not newly failing tests.
- Prettier and lockfile consistency: **PASS**.
- TypeScript: **PASS**.
- Vitest: **PASS** — 93 files, 456 tests.
- Production web build: **PASS** (non-blocking large-chunk advisory only).
- Playwright: **PASS** — 13 passed, 1 skipped (opt-in live OSM demo).
- Alembic isolated upgrade -> downgrade -> upgrade: **PASS**, current revision `0037`
  (`head`). No migration was added by this sprint.
- Rust training-console run-ID validation: **PASS** — 1 test.

### Windows installer evidence

The clean tree at source commit `df40f6afc359c45c115a435ae46dc1544018ebba`
produced the Windows x64 WiX MSI and five required external CAB files. Administrative
extraction found 19,728 files, the desktop executable, backend sidecar, Pydantic core,
all 38 migration files, and no bundled model weights; the packaged backend self-test
passed. The MSI depends on all five CABs and they must be distributed together.

| Artifact                         |       Bytes | SHA-256                                                            |
| -------------------------------- | ----------: | ------------------------------------------------------------------ |
| `ReefVision_1.0.3_x64_en-US.msi` | 219,992,431 | `750fc140bef6a8e0b85d4c3bf3d915e9959f27fa47756efdb9d4406b8fe11f97` |
| `rv1.cab`                        | 614,173,680 | `d8b541a7f6516235a31a6a6b4fd1fbfcabaf36c889d5bbab1462576c0fe4faef` |
| `rv2.cab`                        | 389,032,911 | `27325450bddab5690fb164b22e154abb04eaf14f1629e7f0914d787bcc5cf959` |
| `rv3.cab`                        | 735,884,498 | `9d9e67f1171a5af4a042fc687a65f2224801c9102f564e3437111a10d3cc699e` |
| `rv4.cab`                        | 353,162,953 | `b384b635377276af4482495132ec324435c22a57231e8093716deab821ba51f1` |
| `rv5.cab`                        | 608,327,808 | `a52cde9a3d6ac4a73e32b55dfbef56403b6a6cfc4824f1febdde0015091ac929` |

Physical clean install, upgrade from 1.0.2, installed-application relaunch, console
interaction, project/image/video GUI interaction, and uninstall were **not performed**
in this laptop sprint and remain **UNVERIFIED**.

### Final laptop-only acceptance addendum

- The Windows workflow no longer hard-codes `1.0.2`. It derives the semver and artifact
  slug from `tauri.conf.json`, checks the MSI ProductVersion, requires exact CAB/media
  membership, rejects unexpected model weights, and validates clean-tree/source-commit
  provenance plus all recorded payload hashes. Focused workflow tests passed.
- CPU segmentation technical acceptance passed in 40.5 seconds. Evidence is retained at
  `C:\rv103-final-seg-acceptance\report.json`; the registered checkpoint SHA-256 is
  `81508398dbb694ba2e24d1f3b9ff565950bbea48161842563ec138fed5a0bdbf`.
- The existing 1.0.3 MSI was administratively extracted to an isolated directory without
  installing or overwriting ReefVision 1.0.2. The extracted 1.0.3 backend applied all
  migrations in a private data root, exposed 25 scratch architectures and zero
  pretrained/downloadable models, persisted a project/image/annotation across restart,
  and produced a 16,799-byte Project Exchange archive with 56 entries, media, and a
  manifest.
- The first physical extracted-desktop launch was correctly rejected by ReefVision's
  single-instance guard because the user's installed 1.0.2 desktop was running. That
  production session was not closed or modified. After it ended independently, the
  extracted 1.0.3 desktop launched visibly and responsively against the marker-gated
  private data root; its bundled backend reported version 1.0.3, an up-to-date schema,
  and the persisted acceptance project and annotation. The native controller exposed no
  Windows-app interaction surface, and Windows Sandbox is unavailable, so install,
  upgrade, uninstall, shortcuts, the PowerShell monitor window, and all mouse/keyboard
  GUI observations remain **UNVERIFIED** rather than inferred from process, backend, or
  browser tests.
- No new migration was introduced. The MSI/CAB payloads remain the exact clean-tree
  `df40f6afc359c45c115a435ae46dc1544018ebba` artifacts listed above; later commits only
  change acceptance workflow/tests/scripts and documentation.

### Required follow-up matrix

1. On a clean supported Windows host, keep the MSI and all five CAB files together;
   verify install, first launch, project creation/open, the P0-P7 interactive workflows,
   relaunch/recovery, upgrade from 1.0.2, and uninstall.
2. Use an authorized representative, scientist-verified segmentation dataset to evaluate
   biological performance and held-out mask quality. The laptop synthetic run must not
   be cited as scientific accuracy evidence.
3. On the target RTX 3090 host, verify NVIDIA driver/CUDA compatibility, detection and
   segmentation training, CUDA inference, checkpoint reload, hybrid tracking throughput,
   VRAM behavior, cancellation/recovery, and performance benchmarks. These checks are
   **DEFERRED**, not failed.

The technical CPU segmentation blocker is closed. The remaining non-GPU release blocker
is physical clean-install and interactive GUI acceptance on a disposable Windows host;
representative segmentation is a separate scientific-validation gap rather than an
observed software defect. Sprint commits are on
`fix/reefvision-training-architecture-picker-20261022` in draft PR #81; the final
documentation commit follows the installer build commit recorded above.

## 2026-10-23 release-readiness continuation (PR #81)

Release decision remains **HOLD — not release-ready**. Development verification on the
current PR tree is green, a reproduced segmentation inference blocker is fixed, and the
Windows workflow now performs a real disposable-runner upgrade from the published 1.0.2
installer. Those results do not substitute for representative biological validation,
the RTX 3090 matrix, or installed interactive P0–P7 acceptance.

### Continuation changes and evidence

- The PR integrated the latest consolidated 1.0.3 base, including bounded WebView2
  gallery-media recovery. Gallery timeout/replacement coverage, the first-open viewport
  Playwright regression, full TypeScript, and the full frontend suite pass.
- Instance-segmentation inference now validates provider output per prediction. A
  malformed polygon is skipped and recorded only when valid proposals survive; if all
  returned predictions are invalid, the job still fails and cleans up pending proposals.
  This closes the observed failure where a small number of self-intersecting Ultralytics
  contours discarded every valid held-out proposal.
- A fresh deterministic 20/5/5 synthetic technical dataset completed a 25-epoch CPU
  segmentation lifecycle in 35.1 seconds. It registered checkpoint SHA-256
  `1f9e8aa1dc94a698a1e0ce0feede0ee6f70c6c82dbae16c7550335d67c711023`,
  retained 43 valid held-out polygon proposals, explicitly accepted and persisted one
  mask, and passed restart inference. Two invalid restart contours were reported and
  skipped while nine valid proposals persisted. Evidence is retained at
  `C:\Windows\Temp\rv103-seg-final-out\report.json`. Dataset representativeness and
  scientific segmentation acceptance remain **UNVERIFIED**.
- The disposable Windows job now runs two isolated harness passes: a candidate-only
  fresh install, launch, persistence/relaunch, and uninstall; then an audited 1.0.2 to
  candidate upgrade. It downloads the published 1.0.2 MSI and five CABs, pins its
  audited source commit and provenance SHA-256, verifies every payload hash and MSI
  ProductVersion, and verifies the packaged API version changes from 1.0.2 to 1.0.3
  during upgrade. The two paths use distinct marker-gated data roots and evidence.
  Local preflight tests and 44 PowerShell safeguard assertions pass. The user's
  installed ReefVision application was not modified.
- The hosted Windows build/install/upgrade result is authoritative only when the final
  PR SHA's checks complete successfully. Interactive mouse/keyboard, DPI, dual-monitor,
  training-console-window, and complete P0–P7 observations remain **UNVERIFIED** even
  when the headless disposable-runner job passes.

### Fresh local quality gates

- Ruff application scope: **PASS** — 666 Python files formatted and lint-clean.
- mypy strict package check: **PASS** — 409 source files.
- Pytest: **PASS** — 1,264 passed, 32 documented opt-in/live integration skips, one
  Starlette deprecation warning.
- Segmentation/import/export/dataset focused suite: **PASS** — 170 tests.
- Lockfile, Prettier, and TypeScript: **PASS**.
- Vitest: **PASS** — 93 files, 460 tests after the latest gallery-base merge.
- Playwright: **PASS** — 13 passed, 1 skipped (opt-in live OSM demo); focused first-open
  gallery viewport also passed independently.
- Production web build: **PASS** — existing non-blocking large-chunk advisory only.
- Alembic isolated upgrade -> downgrade -> upgrade: **PASS**, current revision `0037`
  (`head`). No migration was added by this continuation.
- Rust training-console run-ID validation: **PASS** — 1 test.

### Remaining required release evidence

1. Complete installed, interactive P0–P7 acceptance on a clean supported Windows host,
   including real mouse/keyboard navigation, DPI/resizing, relaunch/recovery, shortcuts,
   the detached PowerShell training monitor, and representative project/media workflows.
2. Evaluate held-out masks on an authorized representative, scientist-verified coral
   segmentation dataset with usable ground truth. Synthetic technical execution is not
   a biological-performance result.
3. Run the explicitly deferred RTX 3090 matrix: NVIDIA driver/CUDA compatibility,
   detection and segmentation training/inference, checkpoint reload, hybrid tracking,
   throughput/VRAM, cancellation/recovery, and performance benchmarks.

No merge, release, tag, installer publication, branch deletion, or rollback is
authorized by this continuation record.

## 2026-10-26 final release-completion sprint (PR #81)

Release decision remains **HOLD — software candidate validated, physical and
representative-science gates outstanding**. PR #81 now cleanly integrates the current
`develop/reefvision-1.0.3-consolidated` base and remains a draft. No GPU validation,
release publication, tag, or merge was performed.

### Final software changes

- Windows rendition publishing now retries transient destination replacement failures
  with bounded exponential backoff. Deterministic regression coverage exercises the
  Windows `PermissionError` path, and concurrent display/thumbnail stress coverage no
  longer reproduces the intermittent import failure.
- Camera originals now recognize Windows' distinct `EOPNOTSUPP` code when a removable
  filesystem cannot create hard links. Cleanup of locked invalid staging artifacts is
  best-effort and logged, so one Windows sharing violation cannot abort later files in a
  batch or hide already completed per-file results.
- The installer gate accepts the two observed valid WiX layouts (five or six contiguous
  external CABs), derives its final size partition from the files actually emitted, and
  continues to require exact MSI Media membership, version, provenance, payload hashes,
  required sidecar/runtime files, and the absence of unintended model weights.
- Video pose hydration preserves an asynchronously restored pose selection on initial
  load while synchronously clearing it when the selected video actually changes. This
  prevents both lost initial state and stale cross-video imports.
- The annotation editor now times out an eventless WebView2 full-image stall, exposes an
  immediate retry, and blocks saving, status verification, and prediction review while
  only a thumbnail preview is available.
- The detached PowerShell monitor ignores null and non-finite partial-epoch samples,
  scans backward to the latest real loss, and keeps per-epoch history authoritative over
  stale summary values for box, classification, DFL, and segmentation losses.
- The consolidated raw-source-pixel image contract, EXIF warning fallback, gallery
  first-open recovery, training architecture selection, loss monitoring, annotation
  review boundaries, polygon persistence/export, and detection/segmentation/hybrid
  tracking implementations remain intact.

### Fresh local evidence

- Ruff lint and format: **PASS** — 667 Python files.
- Strict mypy package check: **PASS** — 408 source files.
- Pytest: **PASS** — 1,360 passed, 32 documented opt-in/live integration skips,
  and one Starlette deprecation warning.
- Alembic isolated upgrade -> downgrade -> upgrade: **PASS**, current revision `0037`
  (`head`).
- Frontend lockfile, Prettier, and TypeScript: **PASS**.
- Vitest: **PASS** — 93 files, 478 tests.
- Playwright: **PASS** — 13 passed, 1 documented opt-in live-OSM skip.
- Production web build: **PASS** — existing non-blocking chunk-size advisory only.
- Scientific/dataset/segmentation/calibration/import-export suite: **PASS** — 191 tests.
- Focused image/training/video/installer backend regression suite: **PASS** — 195 tests.
- Windows clean-install harness safeguards: **PASS** — 44 assertions.
- Rust training-console opaque run-ID validation: **PASS** — 1 test.

A fresh 25-epoch CPU-only synthetic segmentation lifecycle completed in 56.64 seconds.
It preserved immutable source bytes, registered checkpoint SHA-256
`c75ff1a30f870e5ce30f72b7d2c5b2359d9b0a4f87876314a031e922c4abe379`,
created 55 valid pending polygon proposals across five held-out images, explicitly
accepted and persisted one verified mask, and passed restart inference. PyTorch reported
zero peak VRAM and the configured training device was `cpu`. Evidence is retained at
`C:\Windows\Temp\rv103-seg-20261026-final2\report.json`. This is technical synthetic
regression evidence, not representative coral-polyp accuracy evidence.

### Remaining release gates

1. Complete installed, interactive P0–P7 acceptance on a clean supported Windows host,
   including real mouse/keyboard navigation, DPI/resizing, shortcuts, the detached
   training monitor, representative media workflows, relaunch/recovery, and uninstall.
2. Evaluate held-out masks on an authorized representative, scientist-verified coral
   dataset. No such dataset was present in the repository or configured Models directory,
   so biological performance remains **BLOCKED**, not inferred from synthetic geometry.
3. Run the explicitly deferred RTX 3090 matrix when that hardware is operational. GPU
   training/inference, CUDA compatibility, throughput, VRAM, and performance remain
   **DEFERRED** rather than failed.

The final pushed SHA's GitHub checks are authoritative for the reproducible MSI/CAB build
and disposable-runner fresh-install/upgrade acceptance. A passing hosted job still does
not substitute for the physical interactive gate above.
