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

## First development slice

- Candidate first-open viewport effect fix inherited from PR #72.
- Additional JPEG filename aliases and BMP/static GIF ingestion plus browser-safe CMYK JPEG/BMP/GIF conversion. Explicit non-destructive rejection of animated GIFs.
- Per-training-run Windows PowerShell monitor polls ReefVision's local read-only status endpoint and displays live stage/epoch/metrics. Run identifiers are validated before a shell is spawned.
- Synchronized version source metadata for staging 1.0.3.

**None of these changes is production validated merely by its presence in Git.** Automated and installed GUI verification remain mandatory.
