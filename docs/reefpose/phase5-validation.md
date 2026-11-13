# ReefPose Phase 5 validation

Date: 2026-11-12
Branch: `feature/reefpose-core`
Approved design commit: `2e1ee52d`

## Delivered vertical slice

Phase 5 adds a species-independent biological movement and event-counting layer over the
scientist-reviewed Phase 4 identity state. Migration `0042` persists immutable measurement
runs, scalar series and samples, event-detection runs, and append-only event revisions. It
does not rewrite pose observations, animal identities, annotations, or verified datasets.

The pure CPU engine calculates distance, angle, prior-valid-sample displacement, velocity,
direction, angular velocity, full-chain turning-per-arc-length curvature, body-axis
orientation, relative movement, and anatomical span extension. Each
sample retains source frame/time, confidence, pixel value, optional calibrated value and
unit, validity, missing-data flags, and source observation revisions. Source identity,
schema, video, calibration, configuration, and environment snapshots are integrity-hashed.

The deterministic event detector uses explicit open/close hysteresis, duration, amplitude,
separation, refractory, confidence, smoothing, and gap policies. Complete and partial
cycles are distinct. Partial, rejected, or unreviewed events never contribute to confirmed
counts. Scientist confirmation, rejection, removal, manual additions, and boundary changes
create append-only revisions; boundary changes validate real, valid endpoints and recompute
classification, peak, amplitude, duration, confidence, and quality rules from the bound
samples without promoting partial cycles that lack an observed baseline.

Two persisted asynchronous jobs provide progress, cancellation, startup recovery,
deduplication, atomic failure rollback, and stale-input rejection. The immutable input
manifest includes every selected current Phase 4 observation and its content. Reviewed JSON
and deterministic CSV ZIP packages contain measurements, current confirmed events,
per-individual summaries, full revision history, source provenance, units, configurations,
file hashes, and package hashes. Exploratory measurements remain visibly separate from
scientist-reviewed scientific results.

Workflow Builder now executes the typed sequence pose inference → identity association →
identity review → anatomical measurement → event detection → event review → managed
export. It invokes the production jobs, pauses at scientist review, persists child lineage,
rejects stale/unreviewed inputs, pins approval to the exact append-only event-revision
digest, and supports saved-workflow replay. The prior default workflow template remains
unchanged for compatibility.

The Video Tracking Workspace exposes scientific/exploratory mode, reviewed identity and
individual selection, stable landmark IDs, distance/angle configuration, asynchronous
status and cancellation, saved-run reload, an accessible gap-aware SVG time series,
event markers, thresholds, event/frame navigation, confirmation/rejection/boundary edits,
revision history, confirmed counts, evaluated duration, frequency, mean amplitude, and
reviewed exports.

## Deterministic fish-gape evidence

The synthetic fixture contains 12 source-coordinate frames at 10 Hz with gape distances
`[1, 2, 7, 9, 8, 2, 1, 7, 10, 9, 2, 1]` pixels. With open threshold 6 and close threshold
3, the expected complete cycles are frames 2–5 and 7–10.

- Automatic detector output: 2 complete candidates, 0 partial candidates.
- Expected count: 2; detected count: 2; count error: 0 (100% count agreement).
- After explicit GUI review: 2 scientist-confirmed complete cycles.
- Event history after review: 5 revisions (2 automatic, 1 boundary correction, and 2
  confirmations).
- Corrected first event: frames 1–5 with deterministically recomputed amplitude 7 pixels.
- Measurement samples exported: 12.

This proves deterministic computational and workflow behavior only. It is not evidence of
agreement with independent human annotation or biological validity on real fish.

## Live Chromium acceptance

The guarded Playwright test
`apps/web/tests/e2e/reefpose-phase5-live.spec.ts` passed against an isolated Alembic `0042`
database, FastAPI, the real background worker, Vite, and Chromium. The test used the
reproducible engineering seed in `scripts/seed_phase5_live_acceptance.py` and performed:

1. Created a three-landmark stable-ID fish schema and a 12-frame verified pose track.
2. Ran production identity association and confirmed the identity through the GUI.
3. Selected upper/lower jaw landmarks and queued the production measurement job.
4. Displayed the persisted gape time series and queued hysteresis detection.
5. Navigated the workspace to an event frame, changed the first start boundary to frame 1,
   and verified its recomputed amplitude before confirming both complete cycles.
6. Reloaded ReefVision and observed all five append-only event revisions.
7. Exported reviewed JSON and verified two confirmed complete events and 12 samples.

Acceptance evidence:

- Playwright: 1 passed in 9.6 seconds (test body 9.2 seconds).
- Project: `cad1bef0-edd8-4573-9568-0e9b1de594c6`.
- Measurement run: `cd3d96ef-de6f-4a0b-b2b6-081339f07385`.
- Measurement result SHA-256:
  `98fc5894aef6b68dedc3012d87c6e2600a499d9efd74ffa83e8f10f51b6bdf36`.
- Event run: `d68b8c65-c580-4052-a8df-9f6aeeae3df6`.
- Event result SHA-256:
  `50ff6be80a34757146f742a0fd5db788d3e9f667e327e0294ace83f544da9bce`.

The media file in this engineering fixture is a metadata-only placeholder because video
decoding is not part of scalar measurement acceptance; source-coordinate pose rendering,
jobs, review, persistence, reload, and export all used production services. Native packaged
Tauri acceptance was not performed.

## Automated validation

Backend:

- Phase 5 plus affected Phase 4/workflow/job suites: 52 passed.
- Migration `0042` upgrade/downgrade/re-upgrade and compatibility tests: 7 passed.
- Full API collection: 1,512 passed, 40 skipped, 6 failed in 14m17s using a short
  Windows `--basetemp` path to avoid legacy path-length failures in unrelated deep export
  fixtures.
- The six failures are all pre-existing real pose-interoperability cases in
  `test_pose_interoperability_runtime.py` requiring absent optional `sleap-io==0.9.2`
  (five format round trips and one self-contained SLP export). No dependency was installed.
- Ruff: passed.
- Strict mypy: passed for 445 source files.

Frontend:

- Vitest: 97 files, 512 tests passed.
- TypeScript project check: passed.
- Prettier check: passed.
- Production Vite build: passed; the existing large-chunk advisory remains.
- Live Chromium acceptance: 1 passed.

## CPU and CUDA evidence

`scripts/benchmark_reefpose_phase5.py` measured a deterministic 10,000-frame synthetic
gape series on CPU:

- Measurement calculation: 0.063533 s, 157,398 samples/s.
- Event detection: 0.003731 s, 2,680,390 samples/s.
- Eligible complete cycles: 166; partial cycles: 1.
- Deterministic result SHA-256:
  `4a04cd5dae0fb4218e5d9dc41969f10245452fd6f9a2a03e17571fe8ef2a9366`.

Phase 5 scalar formulas intentionally run on CPU; GPU acceleration would add complexity
without scientific benefit at this scale. Upstream availability was nevertheless verified:
PyTorch `2.11.0+cu128`, CUDA 12.8, one NVIDIA GeForce RTX 3090, CUDA available. No model
weights were downloaded and no GPU accuracy claim is made.

## Remaining scientific limitations

- No real labeled animal dataset has been used to estimate event precision/recall,
  inter-observer agreement, threshold robustness, or biological construct validity.
- Two-dimensional measurements inherit camera perspective, calibration, occlusion, pose,
  and identity errors; calibrated units are only as valid as their calibration snapshot.
- Thresholds are explicit scientist configuration, not automatically learned or validated
  across species, individuals, conditions, or frame rates.
- The GUI's direct definition editor currently exposes distance and angle; the full formula
  family is available through the engine/workflow contracts and should receive dedicated
  domain-specific UI affordances rather than a generic unsafe formula editor.
- Manual event addition/removal is available through append-only service/API contracts;
  the current GUI emphasizes automatic candidates, confirmation/rejection, and boundary
  correction.
- Learned behavior classification, multi-camera 3D kinematics, uncertainty propagation,
  and cohort-level statistics remain out of scope.

## Recommended next milestone

Phase 6 should be a real-data scientific validation and study-management milestone:
freeze independently annotated multi-species videos; measure pose/identity/event agreement
with blinded reviewers; quantify calibration and threshold sensitivity; add inter-observer
and uncertainty reports; and expose the remaining formula/manual-event controls in the GUI.
Only after that baseline should ReefPose train behavior classifiers or report biological
conclusions.
