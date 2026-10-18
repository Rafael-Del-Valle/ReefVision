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

## Outstanding acceptance

Run Ruff, mypy, backend/frontend/E2E and migration/backwards-compatibility checks
at the actual commit SHA; independently verify scientific semantics and review gating;
add reviewer assignment/comment/bulk actions, dense-object rendering, onboarding and
Windows installer/start/update validation, and installed GUI/hardware acceptance.

Version 1.7 monitoring and **revised** 1.8 scientific modalities remain untouched.
Do not merge, tag, release, download pretrained weights or deploy paid hosting.
