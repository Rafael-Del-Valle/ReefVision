# ReefVision 1.6 — QC workflow integration (development)

**Status:** draft implementation, not release acceptance. Master coordination: issue #76.

## Existing support audited against main `9278d45e`

- Label class management and operation history already exist (migrations 0011–0013).
- Per-user and project class visibility preferences already persist (migration 0012).
- Existing QC review queues persist ranking, confidence thresholds, filters, and item
  start/complete/skip/return actions (migration 0007 and review-queue service).
- Workflow Builder already supports typed graph validation, persisted runs/artifacts,
  and human-review gates. This increment extends rather than replaces those contracts.
- Unmerged 1.0.3 draft PR #73 includes viewer/JPEG/onboarding/training-console changes;
  1.1 PR #71 and 1.2 PR #74 are isolated, not incorporated.

## New incremental behavior

- Executable `qc_review_queue` node accepts `project_reference` and produces a typed
  `review_queue_reference` artifact.
- Calls the same `ReviewQueueService` as the standalone API; no duplicate ranking algorithm.
- Records queue ID, project/run/node IDs, QC source run, scoring formula/version,
  input checksums, and **dimensionless** priority score units.
- Output is explicitly `requires_researcher_review`, never verified ground truth.
- Persists queue once per workflow node; retries reuse it only for unchanged settings.
- Tests cover standalone and saved graph execution, typed artifact persistence, reuse,
  foreign-project rejection, and changed-parameter rejection.

## 1.6 bulk QC triage increment

- A manual `POST /api/v1/review-queues/{queue_id}/items/bulk` endpoint can
  start, skip (with reason) or return up to 100 queue items at once.
- Preflight validates every item and its queue/project membership before changing
  anything; the batch commits once or rejects without partial transitions.
- Exact retries are idempotent. Bulk completion/annotation approval is intentionally
  unsupported: this is triage, not a substitute for researcher verification.
- The standalone batch acts on the same durable queue IDs produced by the executable
  `qc_review_queue` Workflow Builder node. Saved runs and their typed reference
  artifacts are unchanged. Audit-identity persistence and reviewer assignments remain pending.
- API regressions cover state transitions, duplicate retries, cross-queue isolation,
  atomic failure, and preservation of unverified image annotations.

## 1.6 saved queue priority-order integrity

- Workflow retries must preserve the deterministic priority order used by
  `ReviewQueueService`: descending score, followed by image ID for ties.
- The earlier checksum covers image IDs and scores but excludes rank positions.
  The additional validation rejects swaps without recalculating live QC
  measurements or changing reviewer state, comments, or assignments.
- Standalone unit regression covers swapped ranks and ties; a saved executable
  Workflow Builder graph creates a queue with two media items, detects ranking
  tampering, and confirms that a restored queue can be retried.
- Approval remains researcher-controlled; saved workflow artifacts retain typed
  `review_queue_reference` output and provenance.

## 1.6 saved QC source provenance integrity

- Queue creation stores the resolved QC run in the queue record and its
  configuration, including when the request omits an explicit run.
- Executable Workflow Builder retries now require those saved identifiers to
  agree. This rejects a changed source configuration without querying live QC
  observations, changing reviewer decisions, or automatically approving work.
- Isolated regression tests cover changed/missing/invalid source configuration
  and a valid automatically resolved run. The existing saved-graph regression
  now checks failed validation and successful retry after restoration.
- The deterministic rank check was separately reformatted for Python CI.
  These changes require exact-head CI and Windows acceptance.

## 1.6 saved scientific summary integrity

- The queue scope checksum protects saved image IDs and scores, but does not
  cover the separately persisted QC summary. Saved Workflow Builder retries now
  reconstruct mean priority, severity counts, split counts and top-ten image
  order from saved items; inconsistent summaries fail closed.
- No live annotations are re-read or rescored, and reviewer states, assignments
  and comments remain editable. Both empty queues and zero-valued summaries
  are supported.
- Unit regressions cover missing/nonfinite/boolean mean, corrupted counts,
  invalid top-ten order and empty queues. The executable saved-workflow test
  tampers with the summary, checks rejection, restores it, and verifies reuse.
- Exact-head CI, migration compatibility, Windows installed GUI and real
  scientific-data acceptance are still required.

## 1.6 QC mean type narrowing and invalid-value regressions

- The existing summary validator uses an explicit numeric `isinstance` check
  before `math.isfinite` so strict mypy can narrow `Any | None` safely.
- Boolean, string, null, NaN and infinite averages are still rejected; valid
  finite integer and floating-point averages remain accepted. No coercion or
  silent change to scientific scoring is introduced.
- A new standalone regression test exercises nine numeric and invalid cases;
  the existing executable saved-workflow test exercises this validator during
  retry. Exact-head CI and installed Windows validation remain outstanding.

## Outstanding acceptance

Run Ruff, mypy, backend/frontend/E2E and migration/backwards-compatibility checks
at the actual commit SHA; independently verify scientific semantics and review gating;
add reviewer assignment/comment/bulk actions, dense-object rendering, onboarding and
Windows installer/start/update validation, and installed GUI/hardware acceptance.

Version 1.7 monitoring and **revised** 1.8 scientific modalities remain untouched.
Do not merge, tag, release, download pretrained weights or deploy paid hosting.

## 1.6 dense-object editor viewport increment

- Image-space viewport culling now limits SVG nodes for annotation boxes,
  prediction proposals, and masks with known bounds; an inclusive 32-pixel
  screen-space margin prevents boundary flicker. Unknown or malformed geometry
  is retained instead of silently hidden.
- Display-only filtering preserves the full annotation document, saved counts,
  selection, review queues, bulk prediction actions, and Workflow Builder artifacts.
  Panning and zooming recompute visibility; resetting the view restores objects.
- Regression coverage includes coordinate transforms, boundary cases, invalid
  metadata, 10,000 dense boxes, and the actual editor pan/reset flow.
- Still requires installed-Windows GUI profiling with real dense coral images,
  large raster masks and GPU/CPU hardware. This is not a release acceptance claim.
