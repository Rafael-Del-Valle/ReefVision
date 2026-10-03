# Phase 5 runtime validation — 2026-10-02

Status: final complete-backend validation in progress. No commit, push, merge,
tag, version bump, MSI build, or stash modification was performed.

Branch: `feat/scientist-ready-phase5-sleap-io-20261002`.
Starting/current HEAD: `00bae62d4bd1cc13bd4c652fb0d3a180f60413b0`.
Phase 6 was not started. Canonical schemas and persistence remain ReefVision-owned;
there are no new migrations.

## Changes

- `pyproject.toml`: optional `interoperability = ["sleap-io==0.9.2"]` extra.
- `apps/api/reefvision/api/routes/videos.py`: runtime-capability endpoint.
- `apps/api/reefvision/schemas/pose_interoperability.py`: typed capability response.
- `apps/api/reefvision/services/pose_interoperability.py`: runtime guidance,
  correct visibility/confidence conversion, source integrity validation, native
  evidence retention, stricter schema/frame checks and atomic imports.
- `apps/api/reefvision/storage/pose_exchange.py`: temporary artifact lifecycle
  and embedded SLP frames.
- `apps/api/reefvision/storage/pose_nwb.py`: real NWB bridge, ImageSeries media,
  checksum-bound semantic restoration and sparse-frame compatibility corrections.
- `apps/api/reefvision/storage/pose_exchange_text.py`: strict COCO/DLC/YOLO
  conversions, media/reference contracts, package validation and sidecars.
- `apps/api/reefvision/tests/conftest.py`: existing integration convention extended
  with explicit `--pose-interop-integration` opt-in.
- `apps/api/reefvision/tests/test_pose_interoperability.py`: fast adapter/API tests
  updated for real SLEAP point representation and DLC package content type.
- Added test modules: `test_pose_interoperability_validation.py`,
  `test_pose_interoperability_runtime.py`, `test_pose_exchange_text.py`, and
  `test_pose_nwb_runtime.py` beneath `apps/api/reefvision/tests/`.
- `apps/web/src/features/video/VideoTrackingWorkspace.tsx` and its test: DLC ZIP
  label and accurate media/provenance guidance; preserved initial formatting.
- `apps/web/src/features/video/poseInteroperabilityApi.ts`: preserved existing
  formatting-only changes.
- `docs/TESTING.md`, `docs/POSE_INTEROPERABILITY.md`, and this report: test entry
  point, scientific contracts, limitations and validation evidence.

Normal ReefVision installation remains independent of SLEAP-IO. The optional
runtime was installed only into the existing development virtual environment.
Capability checks cover missing, wrong-version and broken runtime imports.

## Runtime evidence

| Dependency | Executed version |
| --- | --- |
| SLEAP-IO | **0.9.2** |
| pynwb | 4.2.0 |
| ndx-pose | 0.4.0 |
| hdmf | 6.2.0 |
| h5py | 3.16.0 |
| Ultralytics | 8.3.228 |

| Format | Round-trip result and independent validation |
| --- | --- |
| SLP | Real `sleap_io` write/load/API import passes; source frame, skeleton, repeated mapping, track, coordinates, occlusion and confidence verified. Embedded RGB pixels remain exact and readable after deleting synthetic source media. |
| NWB | Real SLEAP-IO write/load plus `pynwb.validate` passes. Numeric pose series, measured timestamps, embedded ImageSeries, sparse frames, track/visibility restoration and stale-data rejection verified. |
| Ultralytics pose | ZIP includes matching PNG/label pairs and class/keypoint metadata. Installed Ultralytics label verifier and dataset loader accept the package from another working directory. Occluded x/y and 0/1/2 visibility survive. |
| COCO keypoints | Independent JSON Schema and semantic assertions validate image/category references, keypoint counts/values, visibility, boxes/areas and skeleton indexing. API roundtrip passes; image references are explicitly unavailable. |
| DeepLabCut | Standard multi-header CSV parsed with pandas; ZIP sidecar binds source mapping, occlusion and native evidence to the data. API roundtrip passes; missing references are warned about. |

Tests use synthetic temporary assets and no dataset downloads. Ultralytics font
download is disabled in its dataset-check test; configuration/cache directories
are temporary. Optional runtime tests remain skipped during normal fast runs.

## Losses and supported import scope

- All exports remain marked lossy. Repeated-landmark identity, temporal association
  confidence, identity breaks and correction history are supplementary evidence,
  not native external pose fields. Imports do not recreate immutable history.
- Uncertain/visible and out-of-frame/absent distinctions may collapse in native
  fields; the canonical values remain in provenance. Imported observations get
  new IDs, review-required status and the selected target identity class.
- SLP instance scores may round to float32; YOLO normalization can incur floating
  roundoff. Pose boxes are derived rather than round-tripped as canonical boxes.
- SLP/NWB embed only annotated decoded frames, not the whole encoded video.
  COCO/DLC explicitly permit unavailable image references with source SHA/frame
  mappings. YOLO carries lossless PNGs and never silently skips required images.
- NWB without verified source mapping, bare DLC CSV, and YOLO packages without
  the required ReefVision manifest are rejected. This deliberately narrows the
  formerly permissive readers to prevent silent corruption. Plain SLP and
  standard COCO can use explicit source-frame confirmation.
- YOLO train/val aliases describe an exchange dataset; create leakage-safe
  independent splits before training/evaluation. Arbitrary external fields outside
  the documented pose contract are not claimed to survive.

See [POSE_INTEROPERABILITY.md](POSE_INTEROPERABILITY.md) for the complete per-format
contract and the distinction between native fields and supplementary metadata.

## Failures and atomicity

Covered failures include missing/broken/incompatible SLEAP-IO, malformed SLP,
invalid extension/format, missing or changed source media, incompatible/duplicate
skeleton nodes, ambiguous repeated occurrences, invalid/fractional frames,
out-of-bounds coordinates, duplicate track instances, required dimensions missing,
corrupt/traversal ZIPs, missing packaged images and stale sidecars. A simulated
write failure after schema creation confirms rollback. Failed imports report the
file/format, that nothing was imported, atomicity, and corrective guidance.

## Validation results

| Check | Result |
| --- | --- |
| Backend formatting (`ruff format --check apps/api`) | PASS — 542 files |
| Ruff (`ruff check apps/api`) | PASS |
| mypy (`mypy -p reefvision`) | PASS — 340 source files |
| Focused Phase 5 suite with opt-in | PASS — **71 tests** (41 real-runtime, 30 fast) |
| Same focused suite without opt-in | PASS — 30 tests, 41 intentionally skipped |
| Complete backend suite with real-runtime opt-in | PENDING FINAL RUN; earlier full run: 870 passed, 3 skipped |
| Frontend Prettier | PASS |
| TypeScript | PASS |
| Focused pose/interoperability Vitest | PASS — 31 tests in 4 files |
| Complete frontend Vitest | PASS — **294 tests in 64 files** |
| Production build | PASS |
| Playwright | PASS — 9 tests; 1 live-map test skipped |
| Alembic isolated upgrade/downgrade/upgrade | PASS |
| `git diff --check` | PASS |

The full-suite skips are external-data WhaleDrone integration tests requiring
separate opt-in. No Phase 5 real-runtime test is skipped in the opted-in run.
An independent review found and verified closure of unknown-confidence conversion,
NWB sparse-frame mapping, DLC error guidance, portable YOLO YAML and independent
COCO-validation issues.

## Remaining warnings

- Existing Starlette/httpx TestClient deprecation.
- Vite reports the main minified bundle exceeds 500 kB; build succeeds.
- Playwright reports `NO_COLOR`/`FORCE_COLOR` environment overlap.
- NWB writer compatibility filters only exact known deprecated upstream
  constructor fields during that call; independent reads and validation pass.
- A broader-than-CI `ruff check .`/format scan found pre-existing issues in utility
  scripts and a root-level test. The required backend `apps/api` scope is clean;
  unrelated files were not reformatted.
- Git may report CRLF-to-LF normalization for the edited service; no whitespace
  errors were found.

## Working tree and stash

All task changes remain uncommitted and unstaged. New files are source, tests and
Markdown documentation; no datasets, binaries, caches or test artifacts are in
the change list. Validation logs/build outputs remain ignored.

The three original frontend changes were compared to Prettier-normalized HEAD
before functional UI edits and were semantically equivalent. The latest safety
stash, `stash@{0}` (`pre-phase5-split-import-test-format`, object
`34a3299ba8e83bfeaf7669fb5e611dc5073417e5`), contains only formatting changes to
those three files; its changes are redundant with the preserved formatting.
Its older surrounding code must not replace the corrected branch content.
All 25 existing stashes remain untouched. No stash was applied, dropped or cleared.
