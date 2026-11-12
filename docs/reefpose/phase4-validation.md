# ReefPose Phase 4 validation

Date: 2026-11-12  
Branch: `feature/reefpose-core`  
Starting commit: `735b3011684d7e113b22ca368d7ad7b4db7ad6f8`

## Delivered vertical slice

Phase 4 adds an auditable identity-association layer over the existing immutable pose
`VideoTrack` output. It does not rewrite provider predictions or replace ReefVision's
single-animal annotation model. The canonical database records stable animal identities,
source-coordinate observations, per-candidate association decisions and score components,
occlusion intervals, append-only corrections, immutable verified truth, and evaluation
runs. Migration `0041` is reversible and preserves existing video tracks.

The dependency-free association engine uses deterministic Hungarian assignment with
geometric proximity, bounding-box overlap, landmark similarity, constant-velocity motion,
detection confidence, configurable gates, bounded gaps, and deterministic tie-breaking.
It records every selected and rejected candidate. The baseline deliberately makes no
claim of appearance-based re-identification after long occlusions.

The persisted worker supports progress, cancellation, rollback of incomplete output, and
JSON/CSV export. Scientist operations include reassign, split, merge, interval swap,
accept, and reject; each creates a revision with before/after hashes. Corrections that
would create two current observations for one identity and frame are rejected before any
revision is written, with swap recommended for exchanged identities.

Identity evaluation reports ID precision, ID recall, IDF1, switches, fragmentation,
per-identity coverage, spatial match denominators, and association success/failure. It is
kept separate from landmark-localization accuracy and requires immutable
scientist-verified truth. Synthetic truth is explicitly labeled as engineering evidence.

Workflow Builder provides executable typed nodes for pose inference → association →
scientist review → identity evaluation → provenance-preserving export. Saved workflow
replay invokes the real services and reproduces managed artifacts. The visual editor
exposes this sequence as the `Multi-animal pose identity evaluation` template.

The Video Tracking Workspace displays simultaneous skeletons, stable identity labels,
schema/run/hash provenance, low-confidence score components, correction controls,
scientist state, correction history, cancellation, and exports. Completion-triggered
query refresh prevents a fast worker completion from leaving an empty identity cache.

## Live GUI acceptance

The guarded Playwright test
`apps/web/tests/e2e/reefpose-phase4-live.spec.ts` passed against actual Vite, FastAPI,
Alembic revision `0041`, and the real background worker in an isolated local data store.
It performed the following through the rendered React application and production APIs:

1. Created one stable-ID pose schema and two compatible three-frame pose tracks.
2. Queued deterministic association from the Video Tracking Workspace.
3. Waited for the persisted worker run and displayed two identities and both skeletons.
4. Applied an interval identity swap through the GUI.
5. Reloaded the application and reopened correction revision 2.
6. Created immutable verified synthetic identity truth and ran identity evaluation.
7. Exported the corrected results and reproducibility hashes.

Final acceptance evidence:

- Playwright: 1 passed in 4.9 seconds.
- Association run: `e5f9ad48-7555-4e6a-b5fe-6bfe7e663692`, completed.
- Two stable identities, six current observations, and ten audited candidate decisions.
- Correction: `4c3cfcba-e6d5-4389-a9eb-42716803ae82`, `swap`, revision 2.
- Evaluation: `c3da43f2-aaca-49b4-9fe3-5410c5d7d2e0`.
- Result SHA-256: `2ed7c30366ef58e9e32c9d6ab7c49a8ebbb59f89c3c3a1ea54789b80db98e473`.
- ID precision/recall/IDF1: 0.667 / 0.667 / 0.667.
- Identity switches: 2; fragmentation: 0; per-identity spatial coverage: 1.0.
- The intentionally swapped first frame caused the non-perfect identity score and two
  switches, demonstrating that correction state is included in evaluation.

This is actual Chromium GUI acceptance against live services, not mocked component data.
The synthetic empty media container was sufficient for identity-panel validation because
the scientific inputs were source-coordinate pose observations; video decoding itself was
already covered by the preserved pose-inference suites. Native packaged Tauri acceptance
was not performed.

## Automated validation

Backend:

- Phase 4 and affected compatibility suites: 59 passed and two opt-in GPU evaluation
  cases skipped after the final integrity review fixes.
- Existing pose/video/workflow compatibility suites passed during milestone tasks.
- Alembic disposable database: upgrade to 0041, downgrade to 0040, and re-upgrade to 0041
  passed; the migration test also verifies existing `VideoTrack` preservation.
- Ruff: passed.
- Mypy: passed for 438 source files.
- Final full API collection under a short Windows temp path: 1,487 passed, 40 skipped,
  and six failures. All six are the previously documented real pose-interoperability tests
  requiring absent optional `sleap-io==0.9.2`; no dependency was installed and no other
  failure occurred.

Frontend:

- Vitest: 96 files, 508 tests passed, including persisted-run cancellation and the
  completed-run cache regression.
- TypeScript project check: passed.
- Prettier check: passed.
- Production Vite build: passed; the existing large-chunk advisory remains.
- Live Playwright acceptance: 1 passed.

## RTX 3090 synthetic engineering evidence

PyTorch 2.11.0+cu128 imported successfully with CUDA 12.8 on the NVIDIA GeForce RTX 3090.
A deterministic native ReefPose-S CUDA/AMP benchmark (128×128, four keypoints, batch four,
20 inference iterations, ten training steps, seed 1337) produced:

- 657,016 trainable parameters.
- Mean inference latency: 1.418 ms per batch; 2,821.09 images/second.
- Inference peak allocated memory: 17,608,704 bytes.
- Training throughput: 10.13 steps/second and 40.54 images/second.
- Training peak allocated memory: 37,984,256 bytes.
- Final synthetic loss: 0.231436.

The requested environment does not contain pytest, so the opt-in pytest CUDA cases could
not be invoked there. Direct model inference/training benchmark execution and a CUDA tensor
smoke test both succeeded without changing Windows security settings. Association itself
is deterministic CPU code; GPU use belongs to the upstream pose model.

These numbers are synthetic engineering measurements. They do not validate biological
accuracy, identity reliability, generalization, or publication-quality performance.

## Remaining limitations

- Real multi-animal biological videos with independent identity labels are still required.
- The baseline has no learned appearance embedding and must not be described as reliable
  long-gap re-identification.
- The GUI reports conflicting reassignments from the backend; a richer preview of the
  affected identity/frame range remains a useful refinement.
- Identity evaluation currently reports deterministic point metrics; stratification by
  density/gap length and confidence intervals remain future scientific work.
- The GUI shows current-frame skeletons and correction history, but richer track lanes,
  undo-as-compensating-action, and side-by-side affected-frame previews remain useful
  refinements.
- Optional SLEAP interoperability remains unavailable in the verification environment.

## Recommended Phase 5

Implement transparent biological movement measurements and event counting over
scientist-reviewed identity tracks: per-landmark displacement/velocity, body-axis and
joint-angle time series, explicit missing/occluded intervals, researcher-defined event
thresholds, manual event review, and immutable measurement provenance. Validate with
hand-calculated synthetic trajectories first, then a small independently annotated real
animal video set before any learned behavior classifier or biological performance claim.
