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
validate the existing reviewer assignment/comment/bulk actions and dense-object
rendering on installed Windows; complete onboarding, command start/update and
installed GUI/hardware acceptance.

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

## 2026-10-23 — Windows MSI updater integration (Track D)

- The installed `update-reefvision` command now locates the MSI/CAB bundle rather
  than selecting an NSIS `*-setup.exe`. Its MSI helper is installed alongside
  managed command support scripts, with missing-asset preflight.
- A local MSI must come from the exact repository build-output directory with
  no linked path ancestors. Before caching the path (`--build-only`) or stopping
  the application, the command verifies SHA-256 build provenance against the
  checked-out Git SHA, the MSI ProductVersion, and external CAB Media-table set.
- Installation uses Windows Installer with an MSI log. It no longer overwrites
  or deletes portable backend trees. `--clean-build` fails closed pending a
  validated artifact-only cleanup. No pretrained weights are downloaded.
- New Windows disposable-fixture regression checks MSI path confinement,
  junction rejection, sentinel preservation, helper deployment, and the
  verification-before-stop/NSIS-removal command contract. Windows packaging CI
  now invokes this regression before the build.
- **Evidence:** commits `42e4a5cb`, `ae098277`, `27dd1762`,
  `14800253`, `95e1e8bd`, `fdb3e5f0`, `87abe6a1`.
  Previous head `c22981bb` passed Windows packaging/provenance and
  19 of 20 workflow runs; its remaining acceptance run was in progress at
  inspection. **New exact-head CI is pending**; native Windows MSI upgrade
  and installed GUI acceptance have not been performed. No release claim.
- The older NSIS/portable helper functions remain defined for compatibility
  but are no longer invoked by the updater. Audit remaining external callers
  before removing them.

## 2026-10-23 — MSI engine/log preflight and restart-safe updater (Track D)

- Before terminating a running ReefVision desktop, `update-reefvision` now
  checks that the Windows Installer executable exists and prepares a managed
  log directory with no symlink/junction ancestor or file collision. An unsafe
  log path fails closed while leaving the running application untouched.
- Per-update log filenames include a random identifier to avoid collisions.
  Windows Installer exit code `3010` (restart required) records the log and
  exits without premature desktop-version verification or relaunch; post-reboot
  acceptance remains the researcher's responsibility.
- Native Windows disposable-fixture regressions cover safe/unsafe log paths,
  junction rejection, and the updater's verification/engine/log-preflight-before-
  stop and reboot-deferral contracts. No user research assets are modified.
- **Evidence:** commits `895eb47f` and `521c2f6d`. The preceding head
  `39a279dc` had 20/20 successful Actions workflows including the Windows
  installer build and isolated installation harness. The new exact-head
  Windows checks and full installed-GUI/upgrade acceptance are still required.

## 2026-10-23 — Pin install-only MSI to verified build digest (Track D)

- **Gap found in the existing implementation:** `--build-only` stored the MSI
  SHA-256, but `--install-only` did not check it. If its cached path disappeared,
  the command silently selected the newest MSI by timestamp. The provenance
  manifest is not a signed authorization mechanism, so this fallback could
  install a different local artifact than the one previously approved.
- `Assert-ReefVisionCachedMsi` now validates the recorded 64-digit SHA-256,
  enforces the existing exact build-directory and junction restrictions, and
  compares the actual file digest case-insensitively before any process stop.
  `--install-only` requires a pinned path and digest; an absent or changed
  build fails closed with instructions to run `--build-only` again.
- The existing full MSI/CAB provenance and Media-table checks still run after
  the pinned-digest check. No user assets are deleted, and no network access or
  pretrained models are required.
- Native Windows regression fixtures exercise the valid pinned case, modified
  digest, missing digest, wrong directory, and updater wiring without installing
  an MSI. The Windows packaging workflow already runs this test file.
- **Acceptance:** source committed to the isolated draft PR; exact-head Windows
  CI and a real interactive Windows upgrade/rollback remain mandatory. A
  passing packaging job does not establish installed-GUI acceptance.

## 2026-10-23 — SQLAlchemy 2 / SQLite Alembic revision persistence (Track D)

- **Reproduced root cause:** Windows packaging and Linux full backend CI showed
  Alembic executing all migrations through 0038 while a *new connection* saw
  `alembic_version` as `None` (or the older revision). SQLite DDL can survive
  while SQLAlchemy 2 rolls back Alembic's implicit revision DML on closing
  `engine.connect()` without an explicit commit.
- `apps/api/migrations/env.py` now uses `engine.begin()` to commit the
  revision marker on successful migrations, and roll back pending DML on
  failures. The existing 0038 collision guard still executes before any
  migration. No database stamping, asset deletion, or lineage rewrite.
- Corrected two legacy desktop migration mocks: a synthetic 0038 stamp must
  include the expected 1.6 review schema; a mocked successful upgrade must
  produce the post-upgrade revision and schema.
- Added real SQLite 0038→0037→0038 regression checking both persisted revision
  markers and the review table across independent database connections, in
  addition to the existing fresh/restart regression.
- **Local evidence:** a minimal isolated Alembic + SQLAlchemy 2.0 SQLite
  upgrade→downgrade→upgrade smoke test passed with `engine.begin()`. This
  verifies the transaction mechanism, **not** the complete ReefVision migration
  history. Full exact-head CI, Windows MSI/installed GUI and 1.1/1.6 lineage
  reconciliation remain outstanding. Version 1.6 stays DRAFT / HOLD.
