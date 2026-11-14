# ReefPose Phase 3B validation

Date: 2026-11-12  
Branch: `feature/reefpose-core`  
Starting commit: `50ecd1b2fa5bb7c5bb1fa06f5d2a514cd45bd768`

## Delivered vertical slice

Phase 3B adds durable asynchronous scientific pose comparisons without replacing the
Phase 3A synchronous ReefPose evaluation path. One comparison job evaluates one to
twelve compatible registered models against the same immutable, scientist-verified
held-out pose dataset. The worker records frame/model progress, supports cooperative
cancellation and startup requeue, prevents duplicate active requests, retains partial
completed children, and clears its deduplication key only at a terminal state.
Recovery independently recomputes every completed child result hash and revalidates
checkpoint size/hash, provider identity, schema identity, configuration, and dataset
manifest. This closes the crash window between committing a child run and updating
the parent report without repeating inference or trusting stale report data.

The provider boundary normalizes source-pixel poses from native ReefPose and
schema-bound Ultralytics checkpoints. Zero detections are valid misses; multiple
animals, landmark-count mismatches, schema mismatches, and unavailable runtimes are
structured exclusions. Ultralytics confidence is not mislabeled as landmark
visibility. The pinned SLEAP runtime was unavailable, so SLEAP is reported as an
explicit exclusion rather than producing fabricated metrics.
When Ultralytics omits per-landmark confidence, ReefVision records calibration as
unavailable instead of fabricating confidence 1.0. External pose models resolve
schema identity through the authoritative model-schema binding.

Reports include checkpoint and provider identities, dataset and landmark-schema
identity, thresholds, denominators, per-landmark metrics, normalized-error
distributions, confidence calibration, metric availability/reasons, runtime values,
software/device provenance, warnings, exclusions, and a canonical SHA-256. JSON and
CSV exports are available.

Workflow Builder now provides an executable `pose_model_evaluation` node with one
frozen-dataset input, multiple model inputs, persisted configuration, production child
job execution, workflow run/node identities, cancellation propagation through the
normal job system, and a typed comparison artifact. Model Hub provides multi-model and
dataset selection, compatibility/leakage filtering, live persisted progress,
cancellation, reloaded-job discovery, metric cards, error-distribution charts,
calibration, exclusions, warnings, and export links.
The comparison UI also provides an aggregate cross-provider metric table,
per-landmark results, calibration and normalized-error visualizations, latency and
throughput, plus progress/cancellation controls for every active comparison.

## Validation evidence

Backend:

- ReefPose focused suite: 76 passed, 2 opt-in GPU tests skipped in the CPU-default run.
- Worker/model regressions: 28 passed.
- Workflow focus: 19 passed, 1 opt-in GPU training test skipped.
- Final full API suite, with `PYTHONPATH` pinned to this worktree and a short Windows
  temp root: 1,457 passed, 40 skipped, 6 failed.
- All six failures are optional pose-interoperability cases requiring absent
  `sleap-io==0.9.2`; no dependency was installed. A classification fixture initially
  hit Windows path-length limits under pytest's default deep temp root and passed with
  the documented short-root procedure.
- Ruff: passed.
- Mypy: passed for 431 source files.
- Alembic head: `0040`; the focused migration test and 0039→0040→0039→0040 round trip
  passed during Task 1 validation.

Frontend:

- Full Vitest suite: 95 files, 501 tests passed.
- Focused Model Hub and Workflow tests: 19 passed.
- TypeScript project check: passed.
- Prettier check: passed.
- Production build: passed; Vite reported the existing large-chunk advisory.
- Automated component tests exercised the GUI workflow. A manual packaged-desktop GUI
  session was not performed, so this is component/integration evidence rather than a
  claim of manual GUI acceptance.

## RTX 3090 synthetic engineering evidence

The verified PyTorch 2.5.1+cu121 environment completed both native evaluation and an
asynchronous two-model comparison on `NVIDIA GeForce RTX 3090`:

- comparison job: `6a52fb38-8006-474e-bd92-160eb79e6991`
- two persisted evaluation runs
- progress: 2/2
- report SHA-256: `5d1fdfc998c900fe74daa3c292cf2e0b3b301aaeaec826dafb22a686b62e6345`
- peak allocated GPU memory: 9,822,208 bytes
- native one-model latency: 153.783 ms/image
- native one-model throughput: 6.503 images/second

These are synthetic engineering fixtures. They do not validate biological accuracy or
publication-quality performance. The requested PyTorch 2.11+cu128 environment still
fails to import because Windows Application Control blocks `torch\lib\shm.dll` with
error 4551. No security control was changed.

## Remaining limitations

- Real SLEAP scoring remains unavailable until the repository's pinned optional
  runtime is installed and a validated still-image adapter is enabled.
- Scientific accuracy requires independent annotated animal datasets, sufficient
  sample sizes, species/condition stratification, and statistical analysis.
- ReefPose-S remains single-animal. Phase 3B deliberately excludes multi-animal output
  rather than selecting an arbitrary instance.
- The comparison UI renders persisted aggregate and per-landmark evidence; richer
  interactive filtering and statistical significance views can follow without
  changing report contracts.
- No packaged desktop/manual end-to-end GUI session was recorded in this milestone.

