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
