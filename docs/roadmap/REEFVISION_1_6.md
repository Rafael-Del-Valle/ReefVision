## 2026-10-30 — First-run existing-project keyboard handoff (Track D)

- Audited the current 1.6 branch against main and the earlier 1.0–1.5
  roadmap: class visibility, QC coordination, dense-object viewport rendering,
  typed executable saved QC workflows, and project creation already exist.
  This change fixes a remaining **keyboard accessibility** gap in onboarding
  rather than duplicating scientific functionality.
- **Choose an existing project** now transfers keyboard focus, after the
  onboarding dialog unmounts, to the first existing project in the local
  launcher. With no saved projects, focus moves to **New project**. The
  onboarding focus trap no longer restores focus behind the launcher.
  No project is created, selected or changed by this navigation.
- Added application-level regression checks for both project-present and
  project-empty handoffs, including absence of implicit project POSTs.
  Existing project creation still requires explicit form submission.
- Extended the failing frontend CI diagnostic to print the exact Prettier diff
  for all frontend files, rather than a stale hard-coded shortlist. Applied
  the exact formatting fix for `OnboardingModal.test.tsx` shown by CI job
  123928724320 (run 41014842961). This is diagnostic-only and does not
  silently format or commit source files in CI.
- **Acceptance HOLD:** exact-head CI, native Windows installed-GUI keyboard
  acceptance, Windows MSI upgrade/rollback, independent 1.1/1.6 Alembic
  revision-0038 reconciliation, and representative biological-data checks.
  Existing Workflow Builder typed QC/review-gate behavior is unchanged.
  No merge, release, model download, deployment or user-data deletion.

## 2026-10-30 — First-run project handoff regression and CI formatting gate (Track D)

- Inspected draft PR #77, master issue #76, version branches, existing onboarding/project-management implementation and exact-head Actions run 41003937711. Backend lint, mypy, pytest and migrations passed; frontend stopped at Prettier in `OnboardingModal.test.tsx` before typecheck, tests, E2E or build.
- Corrected the exact frontend formatting failure. Added application-level regressions for first-run **Choose an existing project** (show existing projects, no project creation or create dialog) and **Create a project** (no POST before explicit form submit; exactly one POST with the selected project name and blank template after submit). These test the existing project-management handoff without adding another workflow subsystem.
- Existing typed, saved, executable QC Workflow Builder and manual researcher-review gates are unchanged. No migration, project records, scientific assets or local model weights were modified.
- **HOLD:** new-head CI, 1.1/1.6 Alembic 0038 collision, native Windows MSI upgrade/rollback and installed-GUI, representative biological-data acceptance. A GitHub-hosted frontend test pass is not equivalent to Windows installed-GUI validation.

## 2026-10-29 — First-run project access from onboarding (Track D)

- Audited the existing 1.6 onboarding, project launcher, class visibility, QC
  and executable Workflow Builder integrations before changing the UI.
- First-run help previously disabled class/QC/workflow actions until a project
  was selected but offered no direct way to create or choose one. Added explicit
  **Create a project** and **Choose an existing project** actions when no
  project is active. These route through the existing Home/project-creation
  UI; they never create a project without researcher confirmation.
- Added focused frontend regressions for both actions, dismissal semantics,
  and project-scoped visibility. The create-project action now hands keyboard
  focus to the existing creation dialog's project-name input rather than
  restoring focus behind the new modal; a modal-to-modal focus regression
  covers this transition. No database migration, model download, scientific
  record mutation or Workflow Builder node change.
- **HOLD:** frontend CI and installed Windows GUI acceptance still required;
  the independent 1.1/1.6 Alembic revision-0038 collision, MSI upgrade/rollback
  and biological validation remain unresolved.

## 2026-10-28 — SQLite integrity errors are not all retryable (Track D)

- Inspected the isolated 1.6 PR #77, issue #76, branch scope, existing
  class/QC/Workflow Builder implementation and run 40807532420. Backend
  failed Ruff formatting in the QC adapter and SQLite contention regression;
  frontend passed. No other version branch was integrated.
- The QC adapter previously converted **every** SQLAlchemy IntegrityError
  during queue creation into a concurrency retry. This could hide unrelated
  database constraint defects as benign collisions. The adapter now converts
  only a real SQLite PRIMARY KEY failure on `review_queues.id` into the
  existing controlled retry, and propagates all other integrity errors.
  The SQLITE_BUSY/LOCKED handling remains separate and narrow.
- Added real SQLite extended-error-code tests for the deterministic queue
  identity versus an unrelated UNIQUE constraint, plus an executable saved
  `project_source -> qc_review_queue` regression proving unrelated integrity
  failure is not swallowed. The same saved graph still tests lock recovery,
  typed dimensionless output, human-review gate, reviewer-comment preservation
  and unchanged unverified annotations. Fixed both exact CI-reported Ruff
  formatting failures from run 40807532420.
- No migration, cross-version merge, auto-approval, pretrained weights,
  deployment or research-data deletion. **HOLD:** exact-head CI, native
  multi-process/Windows SQLite testing, 1.1/1.6 Alembic 0038 reconciliation,
  MSI upgrade/rollback, installed GUI and representative biological data.

## 2026-10-28 — Stable workflow QC ownership under competing writers (Track D)

- Audited existing class/visibility, QC, dense-editor, onboarding and executable
  Workflow Builder scope against main and 1.6. The immediate gap was a race:
  two workers could both miss a workflow owner's queue and insert distinct
  UUIDv4 review queues before either committed. Replay then rejected ambiguous
  ownership, but the database had already accumulated duplicate evidence.
- New workflow-owned queue creation derives a stable UUIDv5 primary key from
  the project and persisted workflow run/node owner. SQLite's existing
  `review_queues.id` primary key now arbitrates competing first-writer
  insertions **without changing an applied Alembic migration**. Standalone,
  regenerated and preexisting workflow queues retain their original IDs.
- An insertion collision now rolls back the failed SQLAlchemy session and
  raises an explicit retryable validation error; it cannot silently create
  replacement scientific evidence. On retry, the existing queue must still
  pass all saved source, digest, typed output and researcher-review checks.
- Added standalone duplicate-insert/independent-queue regression and a real
  saved `project_source -> qc_review_queue` graph regression that verifies
  stable IDs, dimensionless output, researcher comment preservation, failure
  on ownership-damaged evidence and successful replay after restoration.
- **Limit:** this prevents duplicate IDs for *new* workflow-owned queues;
  legacy random-ID queues and manually altered databases still require the
  existing duplicate-owner fail-closed check. No cross-process simultaneous
  Windows/SQLite load test has yet been run. Exact-head backend/frontend CI,
  Windows MSI/installed-GUI, biological-data acceptance and the independent
  1.1/1.6 revision-0038 conflict remain release blockers. No auto-approval.

# ReefVision 1.6 — QC workflow integration (development)

## 2026-10-28 — Saved QC cross-signal scientific consistency (Track D)

- Inspected 1.6's existing queue generator, versioned integrity validator, executable
  saved Workflow Builder node, standalone regression suite and CI at predecessor
  `3915dd55`. The exact-head backend job failed at Ruff formatting in
  `workflow_review_queue_integrity.py:209,236`; frontend passed.
- Repaired the two CI-reported formatting differences and strengthened **v3-only**
  persisted scientific evidence validation: a nonzero stale-review-age signal
  cannot coexist with an image marked reviewed, and when pending predictions
  exist, the minimum-confidence deficit cannot be lower than the
  mean-confidence deficit. Both rules reproduce the existing deterministic
  queue generator, not live rescoring or an external model.
- Added re-signed, internally score-consistent contradiction regressions and
  valid positive cases, retaining mutable reviewer decisions. Updated the
  existing valid pending-count tests to reflect real confidence ordering.
  The existing persisted `project_source -> qc_review_queue` regression
  exercises this shared validator on saved-run replay; full exact-head CI
  is still required to confirm compatibility.
- **HOLD:** independent 1.1/1.6 Alembic 0038 reconciliation, exact-head
  lint/type/backend/frontend/E2E, Windows MSI upgrade/rollback and installed
  GUI, and representative biological-data validation. No merge/release.


**Status:** draft implementation, not release acceptance. Master coordination: issue #76.


## 2026-10-28 — Canonical saved QC scientific references (Track D)

- Audited 1.0–1.5 overlap and the existing 1.6 QC queue generator, versioned
  snapshot validator, executable Workflow Builder adapter and saved-run tests.
  No new review-queue implementation, schema revision or cross-branch merge.
- The v3 queue generator already saves sorted, unique class/model/QC-issue ID
  lists, a lowercase SHA-256 input fingerprint and one of three QC severities.
  Previously, a corrupted queue could re-sign its own item-evidence digest
  after inventing malformed reference lists or a false severity; score and
  normalization checks alone did not catch that change.
- New v3-only replay validation rejects non-list, unsorted, duplicate, blank
  or non-string reference IDs, malformed input fingerprints and unsupported
  QC severities. This checks canonical evidence shape, **not** whether a
  referenced model/class/issue is scientifically authentic. Historical v2
  snapshots retain their prior compatibility contract.
- Added standalone parameterized corruption and v2 compatibility tests, plus
  a real saved `project_source -> qc_review_queue` regression: re-signing
  out-of-order model IDs must fail without changing an in-progress researcher's
  review; restoring the original evidence must permit typed, review-required
  replay with the same queue ID. No auto-approval or live rescore.
- Also corrected two exact Ruff-format failures from CI run 40773023885
  (`workflow_review_queue_integrity.py:369` and
  `test_workflow_review_queue_integrity_16.py:691`).
- Acceptance remains HOLD until new-head CI, independent 1.1/1.6 Alembic
  0038 reconciliation, native Windows MSI upgrade/rollback and installed GUI,
  and representative biological-data validation are completed.


## 2026-10-28 — Saved QC output binding and fail-closed recovery (Track D)

- Inspected the existing 1.6 Workflow Builder adapter, standalone review-queue
  endpoints, prior tests, 1.0–1.5 overlap and exact-head Actions results.
  At predecessor `5c3d05db`, frontend CI passed, but backend CI stopped at
  Ruff formatting in `test_workflow_queue_creator_namespace_16.py`.
- A completed saved QC node already records its typed output artifact ID.
  Previously, removing or changing its queue's internal workflow owner could
  cause a retry to generate a replacement queue rather than reject missing
  original scientific evidence. A re-signed output artifact could also claim
  another queue ID without being checked against the saved queue.
- On retry, when a persisted output binding exists, require exactly one
  matching `review_queue_reference` artifact with valid digest, producer,
  port, run, project and **original queue ID**. Reject absent, reassigned,
  forged or ambiguous evidence without creating a new queue. The initial
  interrupted-create path with no saved output remains supported.
- Extended the existing real saved-workflow + standalone API regression to
  simulate reassigned queue ownership and re-signed forged queue references,
  then restore the original evidence and confirm idempotent replay. Fixed the
  precise predecessor Ruff formatting failure in the same test file.
- This is integrity protection, **not** atomic cross-worker queue creation.
  No database migration, reviewer auto-approval, pretrained weights or
  changes to unverified annotations. Exact-head backend/frontend CI and
  native Windows/scientific acceptance remain required before release.

## 2026-10-28 — Independent saved QC runs and duplicate-owner regression (Track D)

- Inspected draft PR #77, master issue #76 and exact-head backend CI run
  40737911861. Frontend passed; backend failed only at Ruff formatting
  of the new duplicate-queue regression's artifact filter (line 71).
- Corrected the CI-reported formatting and extended the real saved
  `project_source -> qc_review_queue` regression: execute the same
  persisted graph twice for one project, retain separate typed
  `review_queue_reference` outputs and queue IDs, then inject duplicate
  ownership into the first run. The first retry must reject ambiguous
  evidence; the independent second run must remain retryable without
  creating a new queue or altering reviewer comments.
- The existing production adapter already scopes queue ownership by
  project and workflow run/node identity. This is additional regression
  coverage, not a new locking guarantee. Concurrent creation across
  workers still requires a database-level atomicity design and migration
  compatibility review before claiming race freedom.
- Exact-new-head backend pytest, Ruff, mypy and full Windows/biological
  release acceptance are pending. No user assets or annotations were
  altered, and no automated research approval was introduced.

## 2026-10-28 — Oversized JSON QC evidence fails closed (Track D)

- Audited exact-head CI and found backend Ruff formatting failure in the
  existing v3 QC regression file; frontend format/type/unit/E2E/build checks
  passed at head `7bd1d155`. Corrected the missing blank line.
- The saved `qc_review_queue` validator used `math.isfinite` directly on
  Python integers from persisted JSON. An integer above floating-point range
  (for example `10**400`) raises `OverflowError` rather than producing
  a controlled scientific-integrity rejection. This could abort an interrupted
  saved Workflow Builder retry with an unhandled server error.
- Centralized finite-number validation now rejects booleans, NaN/Inf, invalid
  types and unrepresentable integers across v2/v3 raw and normalized signals,
  score components, configured weights/thresholds, item scores and summaries.
  Existing legitimate finite evidence and historical unversioned queue
  compatibility remain unchanged. No live rescoring, scientific annotation
  mutation or automatic human approval is introduced.
- Added nine standalone regression cases (seven v2 evidence locations,
  one v3 pending-count case and one re-signed aggregate-weight overflow case).
  The latter guards individually finite JSON integer weights whose combined
  total cannot be represented as a finite floating-point number. Saved
  executable Workflow Builder retry
  coverage remains in `test_workflow_review_queue_16.py`; the same
  validator is called by that adapter before any queue reuse.
- **Acceptance:** exact-new-head Ruff, pytest, mypy and Windows acceptance
  are required. Do not interpret a prior passing frontend job as full release
  readiness; 1.1/1.6 Alembic 0038 reconciliation, native MSI upgrade/rollback,
  installed GUI and representative biological-data validation remain open.

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

## 2026-10-27 — Saved QC producer-output reciprocity (Track D)

- The executable `qc_review_queue` node already checked the signed project
  source payload, successful `project_source` producer and QC consumer's saved
  input binding. A missing reciprocal *producer output* binding could still
  leave a plausible-looking source artifact accepted on interrupted replay.
- The adapter now requires the source ID to be the exact persisted output
  artifact list of its `project_source` node. This is the existing single-output
  node contract; no migration, scientific rescoring or reviewer-state change.
- Added standalone invalid-source cases for absent and substituted producer
  outputs. The saved executable Workflow Builder regression also mutates both
  output bindings, requires rejection before queue reuse, then restores the
  original producer evidence and verifies safe retry.
- These are development changes only. Exact-head CI and installed Windows
  MSI/GUI/scientific acceptance remain pending; no merge or release.

## 2026-10-27 — Saved QC source edge and producer provenance

- Audited the existing executable `qc_review_queue` adapter and Workflow Builder
  job runner. The runner resolves typed edges, but the adapter's direct/retry
  path previously checked only the source JSON digest and workflow-run ID.
- The adapter now also requires a completed `project_source` producer in the
  same run, the `project` output port, and the exact source artifact ID
  recorded in the saved QC node's input binding. Valid-looking substituted
  artifacts cannot reuse an existing researcher-reviewed queue.
- The real saved executable graph regression corrupts the producer port,
  producer identity, saved edge binding and producer completion state, verifies
  fail-closed rejection, restores each record and confirms safe queue reuse.
  This does not alter scoring, researcher actions, biological observations,
  database schema or historical reviewer events.
- Development only: exact-head CI, native Windows MSI/GUI acceptance,
  representative biological datasets and independent 1.1/1.6 migration
  reconciliation remain outstanding. No release approval.

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

## 1.6 QC scoring-weight normalization contract (pending exact-head CI)

- Audited the existing standalone `ReviewQueueCreateRequest`, deterministic scoring
  service, v2 saved-snapshot validator and executable `qc_review_queue` node.
- The standalone API now rejects NaN/infinite weights, all-zero weight vectors
  and finite individual weights whose sum overflows. Positive finite vectors
  with selected zero-weight signals remain supported. This prevents meaningless
  or undefined dimensionless priority normalization before any queue is created.
- Versioned saved Workflow Builder queue retries reject a re-signed all-zero
  scoring configuration even if scores, scientific explanations, scope digest
  and item-evidence digest have been made mutually consistent. Historical
  unversioned snapshots retain their prior compatibility path.
- Added schema/API regressions, a re-signed scientific snapshot corruption
  regression and a persisted executable-workflow positive-weight assertion.
  Repaired the Ruff blank-line failure reported on the previous HEAD.
- These are **pushed development changes, not release acceptance**. Exact-head
  CI, full backend/frontend/E2E, migration compatibility and installed Windows
  acceptance remain outstanding.

## 1.6 actor-labeled bulk triage audit (pending exact-head CI)

- Audited the existing class visibility, QC bulk API, coordination-event persistence,
  saved `qc_review_queue` Workflow Builder node and frontend bulk triage controls.
  Class creation and per-user/project visibility already exist; this iteration
  addresses the remaining bulk-triage audit gap instead of duplicating them.
- Start/skip/return bulk actions now append per-item server-generated events
  within the **same database transaction** as actual review-state transitions.
  Events carry a self-reported local actor label; skip events retain the reason.
  Exact idempotent retries create no additional events.
- The manual bulk UI now requires a reviewer label. Older API clients remain
  compatible through an explicit `local_user` fallback. These labels are
  **not authenticated identities**, and triage never verifies biological data.
- Public comment/assignment requests cannot forge server-generated triage
  events. Existing assignments remain separate from triage state changes.
- Standalone API regressions cover audit persistence, repeat requests, invalid
  actors and forged-event rejection. The saved executable Workflow Builder
  regression manually triages its generated queue and verifies the typed
  review-required artifact can still be retried without scientific mutation.
  Frontend tests cover reviewer-label payloads and retry behavior.
- This is a development increment, **not release acceptance**. The new tests
  and Windows GUI have not yet been validated at this commit.

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

## 2026-10-23 — First-run onboarding keyboard usability and QC guidance

- Reused the existing `OnboardingModal` and `App` first-run/help entry points;
  no duplicate onboarding subsystem or 1.0.3 changes were imported.
- The modal now focuses its Close button on entry, wraps Tab/Shift+Tab
  between its controls, supports Escape, and restores the previously focused
  element on exit when it still exists. These are display/accessibility
  changes only; no project, model, annotation, or review data is modified.
- The research card explains persistent class visibility, manual QC
  assignment/comments/bulk triage, and saved typed Workflow Builder QC queues.
  It explicitly states that priority ranking does not verify model predictions.
- A focused frontend regression covers entry/exit focus, keyboard wrapping,
  and the researcher-approval message. The already executable
  `qc_review_queue` node and its saved-workflow tests remain authoritative;
  onboarding text is not itself an executable scientific capability.
- **Validation limits:** local TypeScript/TSX syntax transpilation was
  available, but frontend dependency installation/Vitest/Prettier and an
  interactive installed-Windows keyboard test were not available in this
  runtime. Exact-commit GitHub Actions and installed-GUI acceptance must pass
  before treating this increment as accepted.

## 2026-10-23 — Onboarding focus containment follow-up

- Audited the existing onboarding keyboard fix rather than duplicating it. Its
  dialog-level Tab handler correctly wraps first/last buttons, but cannot catch
  focus redirected to a background control outside the dialog.
- A document `focusin` listener now redirects external focus to the dialog's
  Close button while onboarding is mounted, and is removed before restoring the
  previously focused control on either dismissal path. This changes only UI
  focus; research assets, class visibility, reviewer state and workflow data
  remain untouched.
- A new frontend regression exercises background focus escape, permanent
  dismissal, focus restoration, and listener cleanup. Existing Tab/Escape and
  QC/Workflow Builder guidance regressions remain in place.
- **Acceptance:** source and test committed to the isolated 1.6 draft branch;
  exact-head frontend CI and native installed-Windows GUI/keyboard acceptance
  must still pass. No release or scientific approval claim.

## 2026-10-23 — QC review scope isolation and stale-selection safety

- Audited the existing standalone QC dashboard and executable saved `qc_review_queue`
  node; this change does **not** add a competing workflow implementation.
- Previously a selected queue ID could outlive a project or dataset-scope change,
  causing the item query to request the prior scope's queue while the new list
  was loading. A dataset-version scope without a selected version also fell
  back to project-wide queue/runs queries.
- Item requests and selected-queue callbacks now fail closed unless the ID is
  present in the loaded scope. Project, dataset-version and queue navigation
  clear transient quick-review/coordination selections and reset pagination.
  Missing dataset-version selection disables both QC source-run and queue
  requests. A newly created queue selection survives an empty old cache list
  until refresh, preserving the existing create-and-review flow.
- Added pure scope/cache regressions and React Query dashboard regressions for
  project navigation and dataset-version selection. Scientific annotations,
  reviewer decisions, persisted queue IDs and typed Workflow Builder artifacts
  are unchanged.
- **Evidence:** commits `e70fcdeb`, `92bc67cd`, `0ccd8d9f`,
  `896bc6f1`, `2aaa9cfa`, `50b9774f`; GitHub source read-back verified.
  The previous head `7aba59df` completed 20/20 GitHub Actions successfully.
  Exact new-head CI and installed-Windows GUI remain unverified at commit time.
  No release acceptance is claimed.

## 2026-10-23 — Saved QC scoring-provenance integrity (Track D)

- Audited the already executable `qc_review_queue` Workflow Builder node and
  existing standalone queue generator; retained the same deterministic scoring
  service rather than adding a duplicate workflow path.
- New queues store `scoring_provenance_sha256` alongside the existing scope
  digest. It covers the persisted formula identifier/version, QC ruleset,
  scoring weights, confidence threshold, and resolved QC source configuration.
- Saved-workflow retries reject scoring metadata drift and item-level weight
  disagreement without rescoring observations or modifying human review state.
  The validator also rejects nonfinite/negative/boolean weight metadata.
- Older saved queues lacking this additional digest remain readable when their
  existing scoring metadata and item weights are internally consistent; the
  additional tamper detection is not retroactively guaranteed for old records.
- Added unit corruption/legacy-compatibility regressions and a persisted,
  executable Workflow Builder retry regression for altered formula provenance.
- **Validation:** source and tests committed on the isolated 1.6 draft branch.
  Full exact-head CI and installed-Windows/scientific acceptance are required;
  no release, merge or researcher-approval claim is made.


## 2026-10-23 — Full immutable QC item evidence digest (Track D)

- **Audited existing support:** standalone QC queue generation, the executable
  `qc_review_queue` Workflow Builder node, persisted typed queue references,
  scoring-configuration digest and saved retry integrity already existed.
- **Gap:** the queue-level scope digest covered image IDs and numeric scores but
  not saved per-image signal values, contribution explanations, original input
  fingerprints or scientific class/model/QC references. An explanation could
  change without invalidating a saved workflow retry.
- New standalone and workflow-generated queues now record
  `item_evidence_sha256` over immutable item identity, rank, score, original
  input checksum, class/model/QC references, normalized and raw signals, score
  breakdown, source severity/split and reason summary. Ordering is by image ID
  for deterministic verification independent of database query order.
- Saved Workflow Builder retries validate that digest **without rerunning
  inference or recomputing live QC**. Reviewer states, comments, assignments
  and skip reasons are intentionally excluded and remain editable.
- Legacy queues lacking the additional digest remain readable under the older
  checks. This is **consistency/replay detection**, not a signed or external
  audit log: someone able to rewrite both data and hashes can defeat it.
- Unit tests cover altered evidence, legacy compatibility and mutable review
  state; standalone API and persisted-workflow tests check the new digest and
  reject modified explanations. Exact-head CI and installed Windows/scientific
  acceptance remain required. No merge or release authorization.


## 2026-10-23 — Exact-head QC integrity CI repair and retry determinism

- Inspected draft PR #77 at `035e22b` and all 20 exact-head GitHub Actions
  workflows: 17 successful, three failing (CI, Pose Workflow Validation,
  ReefVision 1.0 Acceptance). All three failed at backend Ruff before the
  scientific regression suite, not at a scientific assertion.
- Ruff logs identified `I001` (an extra blank line after imports) and
  `SIM102` (nested evidence-digest condition) in
  `workflow_review_queue_integrity.py`. Corrected both without changing
  digest inputs, legacy compatibility, review approval, or persisted data.
- Added two focused regression tests: persisted scientific evidence remains
  invariant under ORM row-order changes, and reviewer coordination fields
  remain mutable without invalidating immutable QC evidence.
- Commits: `9981f80989e53eef89b0d68c442c34a258525994`,
  `7e4c724f505077049337b5e164772b6d6e315f01`.
- Exact-new-head CI and native Windows installed-GUI/upgrade tests remain
  mandatory. No claim of newly passing tests until CI completes. No merge,
  release, or automatic approval.

## 2026-10-23 — Finite QC scientific evidence on saved Workflow Builder retries

- Audited existing standalone `ReviewQueueService`, the typed persisted
  `qc_review_queue` node, and v2 scientific-evidence digests before editing.
- **Gap:** Python's JSON encoder can represent NaN/Infinity, while a
  checksum alone does not establish whether saved raw signals, normalized
  signals or contribution numbers are scientifically valid.
- For v2 saved queues, retries now reject nonfinite/boolean raw signals,
  nonfinite/out-of-range normalized signals, incomplete raw/normalized
  signal keys, and malformed/nonfinite contribution metadata. Normalized
  scores must remain in [0, 1]; raw count signals may legitimately exceed 1.
- Older unversioned queues retain their historical compatibility path.
  Reviewer decisions remain editable, and the workflow never auto-approves
  model predictions or re-runs inference.
- Added focused corruption regressions plus an actual saved executable
  Workflow Builder retry regression for a NaN raw signal and restoration.
  Native Windows GUI, cross-version Alembic and full release acceptance
  remain outstanding.

## 2026-10-24 — Saved QC scoring semantics on Workflow Builder retry

- **Audited existing behavior first:** the versioned v2 snapshot already required
  finite numeric signals, independent scoring/evidence digests, stable ranks,
  scientific summary consistency, and editable reviewer coordination. The
  missing invariant was that an individually well-formed and re-signed score
  breakdown could disagree with its saved raw/normalized signals, configured
  weights, or total score.
- The v2 replay validator now checks exact per-signal membership, unique
  breakdown components, stored raw values, six-decimal normalized values,
  weights, two-decimal weighted contributions, deterministic component order,
  and the aggregate score. It uses **persisted evidence only** and never
  re-runs inference or changes review decisions.
- Unit regressions deliberately recompute the evidence digest after ten
  types of semantic corruption; a separate case re-signs both the score scope
  and evidence while adjusting the summary. A saved executable Workflow
  Builder regression likewise re-signs a modified breakdown and requires
  retry rejection, followed by a restored successful retry.
- Historical unversioned queues remain on their existing compatibility
  validation path. No database migration, model acquisition, or new workflow
  node was required.
- **Validation at implementation time:** prior exact head `3e34dc89` had
  20/20 successful GitHub Actions workflows. New code/tests were pushed on
  the isolated 1.6 draft PR, but their exact-head CI was queued; native Windows
  installed-GUI, upgrade/rollback and scientific dataset acceptance remain
  **HOLD**.

## 2026-10-24 — Complete configured-signal coverage on saved QC retries

- Audited the existing 1.6 standalone QC scorer and executable, persisted
  `qc_review_queue` Workflow Builder node. The scorer emits a value and
  explanation for **every** configured weight; the v2 replay validator had
  allowed a subset of those signals.
- Versioned saved queues now require the exact configured signal set in both
  raw and normalized evidence. A queue with re-signed digests, zeroed scores,
  and omitted scientific signals cannot pass retry validation.
- Added a regression that deliberately removes all scoring signals from a
  saved snapshot and re-signs both the queue scope and item evidence; it must
  fail closed. Legacy unversioned snapshots retain their historical path.
- Fixed the exact Ruff I001 import-order error identified by CI at
  `f81d925000ea452df5e2f8c8546a4d479331ee67` (17/20 passing; CI,
  Pose, and 1.0 Acceptance blocked on that same error).
- No model inference, reviewer approval, migration, or dataset changes.
  Exact new-head CI, native Windows installed-GUI/upgrade/rollback, and
  cross-version Alembic lineage acceptance remain required. **HOLD.**

## 2026-10-24 — Repair persisted QC bulk-triage audit migration

- **Pre-edit audit:** isolated draft PR #77 at `e12c9a89`; its exact-head
  GitHub Actions completed 17/20 successfully. The CI, Pose and 1.0 Acceptance
  workflows failed at Ruff formatting in the new bulk-audit regression. The
  existing 0038 migration also declared a CHECK permitting only `comment`,
  `assign`, `unassign`, while the already-implemented atomic bulk triage
  service writes `triage_start`, `triage_skip`, `triage_return`.
  An upgraded SQLite database would reject these events at commit time.
- **Fix:** apply the precise Ruff formatting correction and add an **additive**
  Alembic `0039_review_queue_triage_event_types` successor. It retains the
  original applied 0038 migration unchanged, rebuilds the SQLite CHECK using
  Alembic batch operations, and preserves existing review history, unique
  request constraints, indexes and foreign keys.
- **Safety:** downgrades refuse to proceed while any triage events exist rather
  than deleting or disguising researcher audit history. New regression tests
  exercise legacy-event preservation, all three server triage types, unknown
  event rejection, unique-request preservation, index/foreign-key integrity,
  and downgrade refusal/restoration.
- **Local isolated evidence:** 2/2 SQLite/Alembic migration regressions passed
  on Python with SQLAlchemy 2.0.50 and Alembic 1.18.4; Python compile checks
  passed. The complete ReefVision checkout was unavailable locally due to
  GitHub DNS resolution. Exact-head repository CI, installed Windows GUI/MSI
  upgrade, and full scientific acceptance remain mandatory; no release claim.
- **Cross-version caveat:** 1.1 and 1.6 independently own different 0038
  migrations. This additive 0039 is safe only on the isolated 1.6 lineage.
  Resolve the 0038 collision and retest both upgrade paths before integrating
  version branches. Never rewrite an already-applied migration in place.


## 2026-10-24 — Orphan-safe QC triage migration and durable audit regressions

- Inspected existing 0038/0039 migrations, migration-lineage guard, persisted QC
  events, saved executable `qc_review_queue` Workflow Builder integration,
  and exact-head CI before editing. This preserves existing class visibility,
  reviewer decisions, queue artifacts, and all independent version branches.
- The 0039 migration now **fails before table recreation** if any audit event
  refers to a missing queue, item, or project. Older SQLite databases may have
  foreign-key enforcement disabled; silently copying orphan events would break
  the biological review trail. The error preserves the original database for
  explicit researcher repair; it never deletes or rewrites those events.
- Three parameterized regression cases exercise each missing parent, confirm
  failed upgrades preserve the event and old event-type constraint, then repair
  the parent reference and complete the upgrade. A separate file-backed SQLite
  regression enables FK enforcement and checks preserved cascade relationships,
  event persistence after reopening, refusal to downgrade active triage history,
  safe downgrade after explicit fixture cleanup, and restored legacy checks.
- The previous exact head `aa1d7147` finished **17/20 Actions successful**;
  CI, Pose Workflow Validation and ReefVision 1.0 Acceptance failed on Ruff
  I001 in the new migration regression. The final style commit `9c3b5ff3`
  restores canonical import ordering and removes the extra blank line before
  a module constant; 20 exact-head workflow runs were registered and still
  queued/pending at inspection. **No new CI pass is claimed.**
- An isolated local SQLite/Alembic/SQLAlchemy smoke reproduction passed the
  orphan-refusal/repaired-upgrade and FK-preserving upgrade/downgrade paths;
  it is **not** a complete ReefVision repository test. Full CI, 1.1/1.6 0038
  collision reconciliation, actual MSI upgrade/rollback, installed Windows GUI
  and representative scientific acceptance remain **HOLD**.

### 2026-10-24 — QC audit migration cross-scope preservation

- The existing 0039 preflight rejected missing review-event parent rows, but independently valid queue, item, and project IDs could still be combined into a scientifically misleading cross-project audit event. Foreign keys alone do not enforce the matching queue/project scope.
- Upgrade preflight now also requires `event.review_queue_id == item.review_queue_id`, `event.project_id == item.project_id`, and `event.project_id == queue.project_id`. Any mismatch fails **before** SQLite table recreation; no events are deleted, remapped, or automatically approved.
- Four new parameterized corruption/repair regressions cover existing-but-mismatched queue, item, project, and paired queue/item references; existing orphan, preservation, upgrade/downgrade, and file-backed SQLite cases remain. Exact Ruff formatting corrections to the prior regression file were applied.
- An isolated Python sqlite3 query smoke reproduced 6/6 valid/orphan/cross-scope outcomes. This does **not** establish that repository pytest, Ruff, or migration integration tests pass. Exact-head GitHub Actions results must be checked.
- Version remains **HOLD** pending full CI, cross-version Alembic 0038 reconciliation, scientific Workflow Builder acceptance, and native Windows MSI upgrade/rollback and installed-GUI validation. No completion marker or release authorization.


### 2026-10-24 — Desktop migration 0039 CI repair and at-head lineage safety

- Inspected draft PR #77 and #71, master issue #76, prior roadmap and exact-head CI at `5b4cdfb1`. The 1.6 branch remains isolated from 1.1's incompatible `0038` migration.
- **Observed CI failure:** 18/20 Actions workflows succeeded; backend CI and 1.0 Acceptance failed with the same three regressions (1299 backend passed, 32 skipped, 3 failed). Two real desktop migration assertions and one mocked upgrade fixture still expected `0038` after additive `0039` became head.
- Updated real SQLite fresh/restart and `0037` downgrade/re-upgrade tests to require persisted revision `0039`; corrected the mocked upgrade fixture to report `0039`.
- Closed an additional startup safety gap: the desktop lineage guard now validates review-event table columns and incompatible scientific tables for **both** stamped `0038` and already-at-head `0039` databases. Parameterized native/foreign-lineage tests exercise both revisions, including no mutation on refusal; the at-head runtime fixture includes the expected table.
- **Isolated validation:** four SQLite/SQLAlchemy smoke cases (native vs incompatible schema for each revision) passed. This is a local reproduction, not full ReefVision pytest or native Windows validation. New exact-head CI was queued at inspection; no CI pass is claimed.
- **HOLD:** still requires exact-head backend/frontend/E2E/Windows checks, cross-version Alembic reconciliation, native installed-GUI MSI upgrade/rollback, and representative scientific/Workflow Builder acceptance. No release/completion marker.

## 2026-10-24 — Stale 0039 QC event constraint safety

- Inspected the 1.6 `0038`/ `0039` migrations, the read-only desktop
  lineage guard, and the exact previous-head Actions logs. Backend CI,
  pose validation and 1.0 acceptance all stopped at Ruff E501 in
  `test_migration_lineage_guard_16.py`; the offending line was split.
- A database could report Alembic `0039` while retaining the older named
  `ck_review_queue_item_event_type` constraint from `0038`. The
  read-only startup guard now rejects a **present but obsolete** named
  event-type CHECK before Alembic or desktop startup can write to it.
  It does not stamp a revision, recreate a table or delete audit history.
- Standalone SQLite regression fixtures cover genuine `0038`, obsolete
  `0039` and valid `0039` CHECK expressions and verify retained
  version markers and event rows. A separate isolated SQLAlchemy/SQLite
  reproduction passed 3/3 cases; the committed repository tests still
  require exact-head CI confirmation.
- **Limit:** this narrowly scoped check does not yet authenticate a
  missing or renamed CHECK constraint; full schema verification and
  cross-version Alembic reconciliation remain release blockers.
- No changes to Workflow Builder's existing executable `qc_review_queue`
  node, its saved runs or researcher approval gates. No merge or release.


## 2026-10-24 — Missing or renamed 0039 audit CHECK protection

- Inspected exact-head `9afd33ff` Actions results: 17/20 workflows passed;
  backend CI, Pose Workflow Validation and ReefVision 1.0 Acceptance failed at
  Ruff RUF043 in the 1.6 migration-lineage regression. The regex match is now
  explicitly raw.
- Extended the read-only desktop/Alembic lineage guard: a database stamped
  `0039` must retain the **named** `ck_review_queue_item_event_type` CHECK
  with all three server-generated triage types. Missing or renamed constraints
  fail closed before API startup/migration; no stamping, rewriting or deletion.
- Added four SQLite regression cases (0038 compatibility, missing, renamed,
  valid 0039) verifying preservation of revision markers and existing events.
  Updated synthetic desktop/runtime fixtures to model the actual 0039 schema
  rather than accepting unconstrained tables. Existing standalone review and
  executable saved `qc_review_queue` Workflow Builder contracts are unchanged.
- **Validation limitation:** SQLite constraint reflection was reproduced
  locally, but complete repository Ruff/mypy/pytest/frontend/Windows acceptance
  must pass on the exact new head. This is **HOLD**, not release acceptance.

## 2026-10-24 — Strict QC event-type constraint validation

- Exact previous head `60ded5f` finished 20 Actions workflows: 17 passed,
  three failed on Ruff formatting in `test_migration_lineage_guard_16.py`.
  Frontend, desktop packaging build and other completed workflows passed, but
  installed-GUI and scientific release acceptance remain outstanding.
- The read-only startup guard now requires the full six-value event-type
  CHECK expression from migration 0039, not merely the presence of three
  triage substrings. It rejects permissive `OR 1=1` checks, extra unreviewed
  event types and missing coordination types without altering any records.
- Regression fixtures cover those three tampering cases and verify the
  migration marker, event history and table DDL remain unchanged.
- Repaired the exact prior Ruff format findings in the same test module.
  An isolated SQLAlchemy/SQLite reflection reproduction passed 4/4 cases;
  full repository tests and exact new-head CI are pending.
- No new scientific Workflow Builder node was introduced: the existing
  executable, typed, persisted `qc_review_queue` node, standalone review
  API and human approval gates remain unchanged. This change protects
  the audit data those workflows rely on.
- Release remains **HOLD** pending CI, reconciliation of colliding 0038
  lineages, real Windows MSI upgrade/rollback, installed-GUI, and
  representative scientific acceptance.

## 2026-10-24 — No implicit pretrained checkpoint acquisition in Windows CI

- Audited the exact-head Windows installer/clean-install acceptance logs. The
  earlier automatic PR job invoked `-LiveSam2Acceptance` and downloaded a
  SAM 2.1 Tiny checkpoint on a disposable runner. That contradicts the
  offline-first rule against downloading unapproved pretrained weights.
- The standard Windows PR acceptance now runs without that switch, retaining
  isolated MSI install, project/annotation persistence, model catalog policy,
  migration, restart and uninstall checks. Real SAM checkpoint inference and
  confidence-review evidence are explicitly reported as **SKIPPED**, not PASS.
- An explicitly requested manual live-SAM acceptance now requires both
  `-LiveSam2Acceptance` and `-ApprovedCheckpointDownload`. Missing approval
  fails before resolving an MSI, creating acceptance data or fetching weights.
- The native PowerShell harness regression asserts the default CI workflow
  cannot request live SAM and exercises the missing-approval refusal without
  an installer. The existing isolated-environment regression requires
  `HF_HUB_OFFLINE=1` by default.
- Source commits: `03d86cf`, `58903a3`, `cb95730` (all on isolated 1.6).
  GitHub source read-back confirms the modified workflow, approval guard and
  regression; **native PowerShell execution and new exact-head CI are still
  required**. Earlier Windows acceptance at `ef6a1d0` passed, but that
  run included an unapproved automatic live checkpoint download and is not
  evidence for the new offline acceptance contract.
- No checkpoint download, model deployment, cross-version merge, release or
  user-data deletion was performed by this iteration. Windows interactive
  GUI, actual MSI upgrade/rollback, cross-version Alembic reconciliation and
  representative scientific data remain release blockers.

## 2026-10-24 — Windows acceptance junction containment (Track D)

- Audited the existing Windows clean-install/upgrade harness and its disposable
  cleanup path after the offline-only CI run. The previous lexical-only
  acceptance-root check did not reject a junction/symlink in an existing path
  ancestor; a seemingly disposable directory could resolve into unrelated
  research data. This is a validation safety gap, not a scientific feature.
- The acceptance-root guard now rejects existing reparse-point ancestors before
  MSI installation or disposable directory creation. Automatic run-root cleanup
  also refuses any linked ancestor **or descendant** before recursion, even
  when the generated run marker is present.
- Added native Windows disposable-fixture regressions for a linked root,
  a linked parent of a nonexistent run, a nested junction during cleanup, and
  SHA-256 preservation of an unrelated sentinel. Fixtures are acyclic and
  remove only their own generated directories/junctions.
- Commits: `1bb90f7`, `e21589f`, `d81d13a`, `8b1940c`.
  Exact GitHub source read-back and static invariants verified. Native PowerShell
  regression, Windows installed-app upgrade/rollback, interactive GUI and
  scientific acceptance still require exact-head CI or physical Windows tests.
- Previous branch head `eb10fdaa` completed 20/20 Actions workflows,
  including the offline-only disposable MSI install/persist/uninstall run.
  That evidence **does not** validate these new path guards or a real upgrade.
  No release, model acquisition, branch merge or user-data deletion.

## 2026-10-24 — Packaged Windows QC coordination acceptance (new, CI pending)

- Extended the disposable MSI clean-install/upgrade acceptance harness to create a real scoped QC queue via the **installed** loopback API, post an idempotent researcher comment, assign a local reviewer, and exercise manual bulk skip/retry/return/start. It checks that no researcher annotation is changed or automatically verified.
- Added a second installed-desktop restart and read-back of the queue, five append-only audit events, in-progress review state, reviewer assignment and original annotation. Evidence is recorded as `qc_review_coordination` only after persistence passes.
- Extended the existing native Windows preflight test with explicit coverage guards for these checks. The earlier Python standalone and executable saved-Workflow-Builder QC regressions are preserved; this is additional packaged-runtime coverage, not a replacement.
- **Validation limitation:** local runtime has no PowerShell/Windows or full repository checkout (GitHub DNS unavailable); exact-head native Windows Actions must execute the new harness before any PASS claim. Still missing interactive GUI, MSI cross-version upgrade/rollback, migration-branch reconciliation, large-scene profiling and full scientific acceptance. **HOLD; no release.**

## 2026-10-24 — Reject false-positive MSI upgrade acceptance

- Exact prior branch HEAD `8af27b22d331a3f38b8798b5ba2e1281f5d066b8` completed **20/20 GitHub Actions workflows successfully**, including offline-only Windows MSI clean-install, packaged API QC review/assignment/bulk triage, persistence across restart and uninstall. This is **not** an MSI cross-version upgrade or interactive GUI test.
- Audited the existing acceptance harness: its upgrade path marked PASS immediately on a successful `msiexec /i` exit, without proving that the target version exceeded the previous version or that the installed app and Windows registration actually changed.
- Added a strict three-field Windows Installer `ProductVersion` preflight (major 0–255, minor 0–255, build 0–65535). Equal-version reinstalls, downgrades and malformed/overflowing versions are rejected **before any MSI installation or acceptance data creation**. The previous installer must still explicitly support isolated acceptance.
- Upgrade PASS is now deferred until the restarted packaged API and Windows uninstall registration both report the expected target version, the isolated database path and migration revision are valid, and the original project/image annotation survived the restart. A plain MSI success exit is insufficient.
- Added native PowerShell regression assertions for valid patch/major increments, same-version, downgrade, malformed and overflowing versions, as well as source wiring and helper parser checks. Existing QC Workflow Builder and standalone/API scientific behavior are unchanged; no new node is necessary for an installer-only acceptance guard.
- **Validation:** GitHub contents API read-back and static source-order/invariant checks passed. Native PowerShell regressions and new exact-head Actions are still pending; local runner has no PowerShell and cannot clone GitHub because DNS resolution fails. No real previous-version MSI was supplied; actual upgrade/rollback and installed interactive GUI remain **HOLD**. No merge, tag, release, pretrained-weight download or user-asset deletion.

## 2026-10-24 — Packaged class-visibility persistence acceptance (Track D)

- **Audit:** Existing class creation, project defaults and local-user visibility preferences already have standalone API tests on the base branch. No duplicate persistence model, migration, or Workflow Builder analysis node was added; class visibility is a display preference, not a scientific analysis operation.
- **New installed-app check:** Windows clean-install acceptance now saves a project annotation visibility default hiding its disposable label class, plus an **explicitly saved empty** local-user preference overriding that default. It reads both scopes and the local identity through the installed packaged API.
- **Restart/upgrade check:** After desktop restart (and after a real MSI upgrade when an approved isolated prior installer is provided), the harness checks the same project, class IDs, saved-state distinction, empty override, and stable local-user identity. It reports a separate `class_visibility_persistence` result; failures block acceptance.
- **Regression contract:** `scripts/test-windows-clean-install-harness.ps1` checks that installed API calls, persistence checks and evidence fields remain present. No checkpoint acquisition, hosting, model deployment, or research-asset modification was introduced.
- **Validation:** Source changes committed on `develop/reefvision-1.6`; native Windows PowerShell execution and new exact-head CI must be checked before claiming this acceptance passes. The prior head `c304a9035e3296d3fb18f078dd2db614d39d3907` completed **20/20 GitHub Actions workflows successfully**, but those runs do **not** validate this new increment.
- **Release:** **HOLD** — real previous-version MSI upgrade/rollback, interactive installed GUI, scientific reference-image validation, and cross-version Alembic `0038` reconciliation remain outstanding.


## 2026-10-24 — Windows installed-backend readiness after restart (Track D)

- **Observed exact-head failure:** ff406fea Windows Desktop workflow run 40143438989 finished with 19/20 overall workflows passing; its installed-MSI job failed at acceptance-windows-clean-install.ps1:519 (Invoke-RestMethod $visibilityUrl: loopback connection refused). Downloaded evidence artifact 12580059132: first launch, isolated SQLite migration to 0039, external COCO/YOLO import and offline model policy all passed; second launch had published its backend port while the packaged API was still starting. The report marks class visibility, restart, QC persistence and uninstall as **NOT RUN**, not PASS.
- **Fix:** Wait-BackendApiReady polls the actual installed loopback API's version and migration-status endpoints, with per-request timeouts, an overall 120-second bound, desktop-exit detection and backend-log diagnostics. Invoked after all **three** desktop launches, before project/QC/visibility API calls. Does not change production backend startup, migration, scientific records, user assets, or Workflow Builder.
- **Regression:** Native PowerShell harness now asserts the readiness barrier is present at all three launch sites, checks the bounded version/schema probes, migration equality, process-exit handling and timeout diagnostic. The Windows workflow itself must prove the actual packaged behavior; source assertions alone are insufficient.
- **Validation boundary:** GitHub source read-back and previous-run artifact inspection were completed. This new exact-head Windows regression and installed MSI acceptance have **not** yet been verified to pass. Still **HOLD** for Windows interactive GUI, real MSI cross-version upgrade/rollback, cross-version Alembic lineage and independent scientific acceptance.

## 2026-10-24 — Class visibility restart port regression (Track D)

- **Evidence:** Exact-head `72a36fbc` Windows workflow [40147705506](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/40147705506) completed 19/20 workflows successfully; the installed-MSI acceptance failed at line 559. Downloaded Windows evidence artifact `12582566404`: the first packaged API migrated the isolated database to `0039`, imported COCO/YOLO annotations, and reported offline model policy PASS. The second packaged API started at 01:15:07 UTC, but the persisted visibility request targeted the **first launch's** cached `$visibilityUrl` and received connection refused at 01:15:10 UTC. This was a stale loopback-port URL, **not proof of a production API crash**.
- **Fix:** The post-restart class visibility read now builds its endpoint from the current `$api` base, after the second launch's port discovery and API/migration readiness barrier. The first-launch URL remains valid only for first-launch preference writes. No database, annotation, class, model or Workflow Builder data is altered.
- **Regression:** The native Windows harness rejects a cached first-launch visibility URL, requires the current `$api` endpoint and verifies that the persisted read occurs after the second readiness barrier. The standalone source read-back is verified; the **new** PowerShell regression and installed-MSI acceptance remain pending exact-head CI.
- **Release:** **HOLD**. Required: current-head Windows acceptance, real MSI upgrade/rollback, interactive GUI/dense-object profiling, cross-version Alembic reconciliation and scientific checks. No automatic pretrained weights or hosting.

## 2026-10-24 — Installed Windows executable QC Workflow Builder acceptance (Track D)

- **Audit before change:** Isolated 1.6 draft PR #77 at `b9c14092012bca1492fc1c1d11434938ba874312` completed **20/20** GitHub Actions workflows, including disposable Windows MSI clean-install, class visibility persistence, packaged QC coordination and restart/uninstall. This did **not** exercise a saved QC Workflow Builder graph in the installed application. Existing Python standalone/saved-graph regressions and production QC services were preserved.
- **New MSI scientific acceptance:** After the installed application's ordinary QC API tests, construct and validate a typed `project_source -> qc_review_queue` graph through its real packaged API; save the graph, enqueue a background workflow job, poll with a 120-second bound, inspect the persisted `review_queue_reference` artifact, and check dimensionless priority scores, project ownership, researcher-review gate, SHA-256 artifact/scoring/item evidence, and workflow-created queue. No model is downloaded or automatically accepted.
- **Persistence:** Restart the installed desktop again, discover the **new** loopback API port, and verify the saved graph, successful run, exact artifact SHA-256, review status and queue survive SQLite close/reopen. Only then record `qc_workflow_persistence=PASS` in the disposable Windows evidence report.
- **Regression:** Extended `scripts/test-windows-clean-install-harness.ps1` to protect real graph planning/saving/queueing, job completion, scientific provenance, review gate and third-launch persistence ordering. Read-back and static source-invariant checks passed for the committed files; **native PowerShell execution and new-head Windows CI remain unverified until Actions finish**.
- **Commits:** `6fa4791e`, `34fc0a0c`, `2f79552a`. This is validation coverage, **not** a claim of release readiness. Remaining gates: native exact-head CI, representative dense-scene interactive GUI/performance, real previous-MSI upgrade/rollback, cross-version Alembic `0038` reconciliation, and independent scientific acceptance. No merge, release, deployment, pretrained-weight acquisition, or user-asset deletion.

## 2026-10-24 — Installed saved-QC-workflow replay after desktop restart (Track D)

- **Pre-change audit:** Draft PR #77 on isolated `develop/reefvision-1.6` at `bb5b3c0503252d0a12c88287a7fad64ab8172f84`; all 20 exact-head GitHub Actions workflows completed successfully, including disposable Windows MSI install/launch/QC graph execution and persistence. This is **not** evidence for a real MSI upgrade or interactive GUI test.
- **Gap:** The installed-Windows acceptance verified that a saved graph and its first run survived restart, but never proved that the **persisted graph could execute again** through the newly launched packaged API.
- **Implementation:** After the third installed desktop launch and migration readiness barrier, enqueue a **new** run of the saved `project_source -> qc_review_queue` graph, poll the actual packaged background job with a 120-second deadline, and require exactly one typed queue artifact. Reject reuse of the first workflow run or queue identity. Compare source-scope, item-evidence and scoring-provenance SHA-256 digests, dimensionless units, project ownership and mandatory researcher review. Re-read the original workflow queue and five manual reviewer events to guard against accidental changes. Record separate `qc_workflow_replay` evidence only after success.
- **Regression:** Native PowerShell harness assertions cover graph re-execution, distinct identities, immutable scientific checksums, review gates, original audit preservation and readiness ordering. The production Workflow Builder node and existing API/migration/schema were not changed; no new duplicate feature or cross-version merge.
- **Validation boundary:** GitHub source read-back and static assertions can verify wiring, but only exact-head Windows Actions can prove this new installed-app replay passes. Real MSI upgrade/rollback, interactive installed GUI/dense-scene profiling, representative biological data, and cross-version Alembic 0038 reconciliation remain release blockers. **HOLD**; no release, merge, pretrained weights or asset deletion.


## 2026-10-24 — Dense raster-mask viewport safety (Track D)

- **Audit:** 1.6 already has viewport culling for boxes and predictions, and inline raster-mask culling. No duplicate feature was introduced. The inline mask path dereferenced every imported record before checking it and always allocated a new display array even when the viewport was invalid.
- **Implementation:** Added `cullViewportMasks` to the existing display-only viewport helper and wired the annotation editor to use it. A corrupt null entry is excluded from the SVG display, while legacy masks with missing/null/nonfinite or inverted bounds remain visible for inspection instead of being silently discarded. Inclusive viewport-edge intersection remains unchanged. When culling cannot safely run, the original clean array is reused without mutation.
- **Regressions:** Added 10,000-mask dense-scene selection checks, inclusive boundary checks, uncertain/malformed geometry preservation, null-record protection, and source-array identity/immutability checks.
- **Workflow Builder boundary:** This is strictly a client-side display optimization, not an analysis, model, measurement or persisted scientific transformation. Saved records, executable QC workflow nodes, provenance and human-review gates are unchanged; no misleading workflow node is added for display culling.
- **Validation:** GitHub source read-back verifies the three changed source/test files. The branch's prior exact HEAD `a4a6e899` passed 20/20 Actions workflows, including packaged saved-QC-graph replay. **The new mask-culling commits are not validated by those runs**; exact new-head frontend format/type/Vitest/E2E and Windows checks are required. Full local repository checkout remains blocked by GitHub DNS, and local Windows/PowerShell is unavailable.
- **Release:** HOLD. Real MSI upgrade/rollback, interactive dense-scene GUI profiling, representative scientific image acceptance and independent cross-version Alembic 0038 reconciliation remain required. No merge, tag, release, pretrained-model acquisition, paid hosting or user-data deletion.

## 2026-10-25 — Atomic single-item QC triage audit (Track D)

- Audited existing project/user class visibility, single-item QC routes, the
  bulk triage event implementation, and the executable persisted
  `qc_review_queue` Workflow Builder node before editing. No duplicate
  class-management or workflow subsystem was added.
- Single-item `start`, `skip` and `return` API transitions now append
  server-generated `triage_start`, `triage_skip` and `triage_return`
  records in **the same transaction** as their state changes, reusing the
  existing 0039 event schema. Skip reasons are preserved. Invalid repeated
  actions create no new audit records. Existing comments and assignments
  remain separate, and no scientific annotation is automatically verified.
- The legacy single-item endpoints do not carry an authenticated reviewer
  identity. These events explicitly use the **unverified** `local_user`
  actor label; do not interpret it as an authenticated person.
- Added standalone API regression for valid transitions, invalid requests,
  durable ordered history, unique request identifiers and unchanged image
  annotations. Extended the saved executable QC Workflow Builder regression
  to triage a workflow-generated queue and then replay its persisted typed
  review-required artifact without changing scientific scoring evidence.
- This increment does **not** add completion audit events: single-item
  `complete` currently has no matching event type in migration 0039.
  Extending that contract requires a separate additive migration and
  acceptance work, not a rewrite of applied 0039.
- **Acceptance:** committed for exact-head CI validation; full installed
  Windows GUI, migration lineage reconciliation, actual MSI upgrade/rollback,
  and representative scientific-data review remain mandatory. HOLD.


## 2026-10-25 — Audited single-item completion (development; release HOLD)

- Existing standalone and saved-workflow QC queues already supported manual
  completion, but unlike start/skip/return it left no append-only transition
  event. This increment adds server-generated `triage_complete` evidence in
  the same transaction as the successful state change.
- Additive Alembic 0040 expands the existing 0039 event CHECK without changing
  scientific annotation or reviewer approval. A downgrade refuses to erase
  completion history. The revision collision guard now verifies the exact 0040
  event allowlist and rejects tampered or mismatched 0038/0039/0040 stamps.
- Standalone API and executable saved-graph tests assert the completion event,
  rejected repeated transitions, unmodified annotations and preserved
  researcher-review gates. Migration tests cover SQLite data preservation,
  foreign keys, invalid event types and downgrade refusal.
- `local_user` remains an unauthenticated fallback actor label, not verified
  researcher identity. A completed QC queue item is **not** a validated
  biological observation, model acceptance, or authorization to publish.
- Full exact-head CI, native Windows installed-GUI, MSI upgrade/rollback,
  cross-version 1.1 migration reconciliation and representative scientific
  acceptance remain outstanding. No merge, release or deployment authorized.

### 2026-10-25 — Fail-fast Python syntax / migration guard CI recovery

- Exact prior head `7c61c1de8dfba8eeb9611565675f8c7061e07db7` failed all but the Prettier diagnostic workflow. Backend Ruff reported an unterminated f-string in `db/migration_lineage_guard.py:53`; Windows packaging aborted during bootstrap import of the same module, before MSI creation. These are CI failures, not evidence of installed-GUI validation.
- Restored the migration guard's error-message string without weakening its fail-closed handling of concurrent or foreign Alembic heads. Extended the existing SQLite regression to require the exception to identify the exact conflicting revisions and preserve research sentinel data.
- Windows installer CI now runs standard-library `python -m compileall -q apps/api/reefvision` immediately after Python setup, before Node/Rust/provider bootstrap and the multi-GB installer build. Syntax regressions fail quickly and do not trigger model acquisition.
- Full lint/type/backend/frontend/E2E, exact-head Windows CI, installed-GUI, MSI upgrade/rollback and 1.1/1.6 migration reconciliation remain release blockers. Do not merge, stamp, tag, publish or auto-approve.


### 2026-10-25 — Nullable audit-event bypass prevention (Track D)

- Inspected the 0038 review-events migration: `event_type` is explicitly NOT NULL, because SQLite CHECK constraints accept NULL values. A tampered already-at-head 0038/0039/0040 schema with a nullable event type could previously pass the named allowlist guard and store untyped reviewer events.
- The read-only desktop migration lineage guard now rejects nullable `event_type` before startup/migration, without stamping or altering scientific data. Added three isolated SQLite regressions preserving an untyped event and scientific sentinel on rejection, and corrected the desktop native-lineage fixtures to reflect the actual NOT NULL migration contract.
- Repaired the exact Ruff formatter difference from three previous CI failures in `test_migration_lineage_guard_16.py`.
- **Validation boundary:** SQLAlchemy inspector NULLability behavior checked in an isolated local SQLite smoke test; exact-head Ruff/backend/desktop/Windows CI still required. Cross-version 1.1/1.6 revision reconciliation and real MSI upgrade/installed interactive GUI remain blocked. Release HOLD.


### 2026-10-25 — Explicit QC audit-event type and CI repair (Track D)

- Verified exact previous head `ae1eb202`: 17/20 GitHub Actions workflows passed; three backend gates failed at the same Ruff E501 (101-character SQL fixture line in `test_desktop_migration_lineage_16.py:168`). Corrected that line without changing the generated SQL.
- Audited original 0038 audit-event migration: `event_type` is NOT NULL **without a server default**. A foreign already-at-head schema that adds a default such as `'comment'` can silently misclassify omitted QC triage actions as reviewer comments. The read-only 0038–0040 guard now rejects such defaults without stamping or modifying scientific records.
- Added three standalone SQLite regressions and three desktop startup regressions for forged defaults at 0038/0039/0040, including preserved research sentinels, existing event records and revision stamps. Corrected positive fixtures to explicitly supply event types, matching the original migration.
- Local isolated SQLAlchemy/SQLite inspector confirmed `default=None` for native columns and `default="'comment'"` for forged columns. Full exact-head Ruff/backend/frontend/E2E and native Windows MSI/installed-GUI acceptance are **not yet verified**. 1.1/1.6 Alembic revision collision remains unresolved. **HOLD**; no merge, release, paid hosting, model download or asset deletion.

## 2026-10-25 — Desktop migration fixture matches 0040 NOT NULL audit contract

- At previous exact head `0cc0b10`, 18/20 Actions workflows succeeded. The two
  failing backend workflows ran the same full test suite: 1,346 passed,
  3 failed and 32 skipped. All three failures were in
  `test_desktop_runtime_paths.py`: its synthetic review-event table still
  declared nullable `event_type`, although migration 0038 requires NOT NULL.
- The shared test fixture now uses `event_type TEXT NOT NULL` by default,
  matching the actual 1.6 schema and allowing the stale 0039 CHECK regression
  to exercise its intended rejection at stamp 0040.
- A separate explicit nullable-fixture regression asserts fail-closed desktop
  startup and unchanged database bytes. SQLite's CHECK alone permits NULL;
  this must remain a distinct negative-path test.
- The fixture fix is test-only. No production guard, schema, migration, user
  data, saved workflow or review approval state was changed.
- Local isolated SQLite NOT NULL/CHECK smoke tests passed for both nullable
  and nonnullable variants. Full repository tests and exact-new-head CI remain
  pending; installed Windows GUI and MSI upgrade/rollback remain unverified.

## 2026-10-25 — Explicit audited bulk QC completion (Track D)

- Audited existing single-item `triage_complete` (migration 0040), atomic bulk start/skip/return and saved executable `qc_review_queue` graphs. No migration or duplicate workflow node.
- Added bulk `complete` **only for already in-progress items**, requiring strict `review_confirmed=true` acknowledgement. The operation is queue bookkeeping only: it does not approve model predictions, verify biological annotations or change immutable scientific evidence. Actor labels remain self-reported.
- Validate the entire batch before writing; append `triage_complete` events atomically with state changes. Identical retries are no-ops. UI requires general confirmation plus explicit confirmation that every selected item was inspected.
- Standalone API/UI and saved-graph regression tests cover confirmation, mixed-state rejection, append-only events, unchanged annotations, replay and researcher-review gates.
- Release HOLD: exact-head lint/type/backend/frontend/E2E/Windows CI, interactive installed GUI, MSI upgrade/rollback, representative scientific validation and independent 1.1/1.6 Alembic 0038 reconciliation remain required.

## 2026-10-25 — Partial bulk QC completion retry regression (Track D)

- Previous exact head `1983f68b` completed 17/20 Actions workflows. The
  three failures share one Ruff formatter diagnostic: a surplus blank line
  before the bulk-completion regression at `test_review_queue_bulk_16.py:181`.
  Corrected the exact line without changing API or scientific behavior.
- Added a standalone API regression for a partially completed batch: the first
  researcher completes one started item, and a later confirmed bulk retry
  completes only the unfinished item. The original completion timestamp and
  actor-labeled append-only audit event must remain unchanged. Further exact
  retries must create no new events. Both items remain marked as requiring
  researcher review; completion never verifies biological annotations.
- This extends existing standalone and saved executable `qc_review_queue`
  Workflow Builder coverage; it does not introduce a second QC engine or
  change the persisted typed graph/artifact contract.
- **Validation:** GitHub source read-back and draft-PR branch HEAD verification
  completed; exact-head CI for the new test is pending. No local full checkout
  is available (GitHub DNS resolution fails), so no local Ruff/pytest or
  installed-Windows GUI/upgrade test is claimed. 1.6 remains **HOLD**.

## 2026-10-25 — MSI ProductVersion evidence integrity (Track D)

- Inspected exact-head Windows Actions artifact `12622085048` from run `40250322549`.
  The installed MSI, first launch, migrated isolated database (revision `0040`),
  project/class/QC persistence, saved typed QC Workflow Builder replay,
  uninstall and retained data all reported PASS. Upgrade was **SKIPPED**;
  interactive GUI profiling and hardware/scientific acceptance remain open.
- **Found an actual evidence defect:** the report serialized
  `reefvision_version` as `[null, "1.0.2", null]` instead of a string.
  The PowerShell COM `Execute()` and `Close()` calls in the MSI
  ProductVersion reader emitted pipeline values around the returned string.
- Suppressed COM method output, added a strict scalar MSI version validator,
  and made the disposable installer harness reject array-valued versions
  **before** installing or comparing versions. Added Windows tests for
  scalar/array/null/invalid/overflow versions and the COM output guard.
- The change affects only Windows acceptance/provenance evidence; it does
  not change application data, MSI payloads, scientific review decisions,
  or executable Workflow Builder behavior.
- **Acceptance:** exact new-head Windows harness and installed-MSI report
  must pass and serialize `reefvision_version` as the JSON string
  `"1.0.2"`. No new-head CI success or real upgrade/rollback is claimed
  until observed.

## 2026-10-25 — Installed MSI bulk QC completion acceptance (Track D)

- Extended the existing **disposable** Windows installed-MSI API acceptance to
  exercise manually confirmed bulk review completion, exact retry idempotency,
  actor-labeled `triage_complete` audit history, and completed-state persistence
  across an installed-desktop restart. The existing saved typed QC Workflow
  Builder replay must leave the six-event manual audit history unchanged.
- This is a synthetic installation fixture only: `review_confirmed` is explicitly
  supplied by the test, and queue completion **does not** verify scientific
  annotations or automatically approve model predictions.
- Native PowerShell harness contract tests guard these expectations. The
  production QC API, migrations, scientific observations and workflow engine
  are unchanged. Full exact-head CI and physical interactive Windows GUI/
  MSI upgrade acceptance remain required; **release HOLD**.

## 2026-10-26 — Installed-MSI acceptance evidence verification (Track D)

- Prior exact head `c9b7e2080c895b5457929e1c3cda8affc11ead0c` passed **20/20 Actions workflows**, including disposable Windows MSI clean installation, packaged API QC coordination and saved Workflow Builder replay. The CI workflow explicitly uses `-SkipUpgrade`; it does **not** establish a real MSI upgrade, rollback, or interactive WebView GUI acceptance.
- Added a read-only, standard-library verifier `scripts/validate_windows_acceptance_report.py` that rejects plan-only, failed, incomplete, or non-UTC evidence; missing required installed-app/QC/workflow checks; stale/non-isolated migrations; MSI version or actual installer SHA-256 mismatch; and misleading upgrade PASS/SKIPPED claims. Optional live SAM and confidence review are explicitly recorded, not silently promoted.
- Added eight standalone regression tests, including actual disposable-file tampering and strict upgrade version checks. The Windows packaging workflow now runs these tests before building and independently verifies the final report and 2.7 GB MSI digest after installed-app acceptance; failure blocks the job before the evidence upload step (which still uploads diagnostic logs on failure).
- Local standard-library unit tests **8/8 passed** and compileall passed in a separate Linux fixture; remote GitHub file read-back confirms committed sources. Full exact-head GitHub Actions and native Windows execution of the new verifier are **pending**, not claimed as passing.
- This is an evidence-integrity increment, **not** a claim of 1.6 release readiness. Real MSI upgrade/rollback, physical installed-GUI/dense-scene acceptance, representative scientific tests, and reconciliation of independent 1.1/1.6 Alembic `0038` lineages remain HOLD. No automatic checkpoint downloads, merge, tag, release, or user asset changes.

## 2026-10-26 — Stable-key QC bulk retry safety (Track D)

- Audited the existing standalone bulk triage endpoint and saved executable
  `qc_review_queue` Workflow Builder node. Both already share durable review
  queue IDs; no duplicate node or schema migration was needed.
- New manual bulk requests may include a client-generated UUID
  `client_request_id`. A new batch stores the original UUID on the
  lexicographically first item as a durable selection marker, and deterministic
  UUIDv5 keys on the remaining items. An identical retry checks committed
  audit events **before** current-state validation, so a lost HTTP response
  cannot restart an item another researcher subsequently changed.
- Keyed first attempts require every selected item to transition, ensuring a
  complete audit marker set. Reusing a key for a different action, reviewer,
  reason, changed selection (including disjoint items), or foreign queue
  fails closed once the first batch is committed. Existing UUIDv5-only event
  batches remain replayable; historical API clients without a key retain
  their state-based retry behavior. A future durable batch registry with a
  unique key is still needed for a formally guaranteed concurrent,
  disjoint-request race across independent database writers.
- The UI generates one UUID per confirmed submission and reuses the *same*
  request payload for an uncertain-response retry. Backend API tests cover
  an intervening reviewer decision, audit preservation, conflicting keys,
  and partial-state preflight. The saved-graph regression covers a keyed
  triage retry on a persisted, typed `review_queue_reference` artifact.
- No biological annotations are verified or altered, and no model checkpoint,
  user asset, migration, or cloud resource is touched. This is a development
  increment pending exact-head backend/frontend/Windows CI and installed-GUI
  acceptance, not a release-ready claim.

## 2026-10-26 — keyed skip/return retry regression and exact-head CI repair

- Inspected draft PR #77 at `88e40274` and its 20 exact-head GitHub Actions runs:
  17 succeeded; CI, Pose Workflow Validation and 1.0 Acceptance failed in the
  same backend Ruff formatter check on `test_review_queue_bulk_16.py`.
  The Windows installer and disposable installed-API acceptance succeeded,
  but this is not interactive installed-GUI or real MSI upgrade/rollback evidence.
- Applied the formatter's reported parenthesized status-code assertion and
  added a standalone API regression for a lost keyed **skip** response followed
  by another reviewer's **return**. The retry must leave the returned item
  pending, retain the original skip reason and both actor-labeled events,
  avoid duplicate events, and reject reuse of the key with a different reason.
  This complements the existing saved executable Workflow Builder keyed
  **start** retry regression; no duplicate workflow node was introduced.
- New code is pushed for CI evaluation; **do not claim the new regression
  passes** until the new exact-head backend and Windows runs finish. No local
  Ruff/pytest or native PowerShell was available in this runtime (GitHub clone
  DNS failed). Cross-version Alembic collision, interactive Windows GUI,
  upgrade/rollback and representative scientific acceptance remain **HOLD**.

## 2026-10-26 — QC batch UUID selection binding (Track D)

- Audited existing 1.6 QC bulk retry logic and found a reproducible gap:
  the same client UUID could be reused for an entirely disjoint item set,
  because UUIDv5 keys were derived independently for each item.
- New batches persist the original UUID on the canonical first item and
  UUIDv5 identifiers for the others. Replay lookup checks all candidate
  identifiers across queues, validates the complete selection and actor/action,
  and rejects any partial or foreign-queue marker. The original audit events,
  human review decisions and scientific annotations are not rewritten.
- Added API regressions for disjoint and cross-project reuse, reordered
  identical retries, and a persisted pre-change UUIDv5-only batch fixture.
  Existing saved executable QC Workflow Builder replay tests remain the
  integration gate for the shared service.
- This is a backwards-compatible service/test increment with **no migration**.
  Sequential committed-request reuse is protected; a separate persisted
  unique batch registry would be required to guarantee cross-writer
  concurrency semantics. Do not claim release acceptance from these tests.
- Exact-head CI, real installed Windows GUI, MSI upgrade/rollback, representative
  scientific data and 1.1/1.6 Alembic 0038 reconciliation remain **HOLD**.


### 2026-10-26 — Global bulk QC request identity (unaccepted)
- Additive migration 0041 introduces a globally unique persisted request registry,
  protecting against concurrent disjoint batches using the same UUID.
- Matching retries remain no-ops after later reviewer changes. Conflicting
  selection, actor, action, project or skip reason is rejected. Registry rows
  and append-only audit events commit atomically.
- Legacy UUIDv5-only events remain readable, with no retroactive guarantee
  that historical disjoint UUID reuse was absent. Nonempty registry blocks
  destructive downgrades. Workflow Builder review gates remain unchanged.
- CI, native Windows GUI, MSI upgrade/rollback, scientific acceptance and
  cross-version 1.1/1.6 Alembic reconciliation remain release blockers.


## 2026-10-26 — Revision 0041 registry schema-integrity guard (Track D)

- Audited the existing global bulk-request registry, desktop migration guard,
  saved Workflow Builder QC queue and 1.1/1.6 revision collision. The 0041
  guard previously checked registry columns and the primary-key name but
  accepted nullable actor, queue/project, action, selected items and timestamps.
  SQLite can also allow NULL in a bare TEXT PRIMARY KEY.
- Read-only desktop preflight now rejects any nullable required 0041 registry
  identity/scope field; only the optional skip reason may be NULL. It does not
  stamp, mutate, or delete databases. Seven synthetic forged-schema regressions
  preserve a sentinel research table and Alembic revision on rejection.
- Corrected the exact Ruff formatting discrepancy reported for the preceding
  0041 API regression. Existing API, typed saved Workflow Builder node and
  explicit researcher approval remain unchanged.
- This is schema-collision detection, **not** reconciliation of the independent
  1.1/1.6 revision 0038. Full CI, real Windows MSI upgrade/rollback, installed
  GUI and scientific acceptance remain mandatory; version 1.6 stays HOLD.

## 2026-10-26 — Revision 0041 QC registry foreign-key integrity (Track D)

- Pre-edit audit found the new registry guard validated non-null identities and
  the global request primary key, but could still accept a forged 0041 schema
  with no queue/project foreign keys or cascading deletion of review history.
- Desktop preflight now requires exact review-queue and project references with
  `ON DELETE RESTRICT`. SQLite uses read-only `PRAGMA foreign_key_list`
  because SQLAlchemy's SQLite inspector omits delete-policy metadata.
  Non-SQLite backends use SQLAlchemy foreign-key inspection.
- Added a valid registry-schema regression and six rejected forged-schema
  cases: missing links, one-sided links, wrong project target and CASCADE
  policies. Tests preserve an unrelated research sentinel and Alembic stamp.
- Fixed the two formatter discrepancies from the previous exact-head CI;
  repository CI and new regressions remain pending until the new SHA runs.
- This guard does not resolve the independent 1.1/1.6 revision 0038 collision
  and does not establish Windows MSI upgrade/rollback, installed GUI, or
  scientific release acceptance. No review decisions, user assets or saved
  Workflow Builder graphs are changed. **Release HOLD.**

## 2026-10-26 — Pooled SQLite foreign-key enforcement (Track D)

- Audited runtime engine setup and revision 0041's RESTRICT constraints. A
  newly connected SQLite session enabled foreign keys, but an existing pooled
  connection could subsequently execute `PRAGMA foreign_keys=OFF` and be
  returned to the pool without revalidation.
- Engine connect **and pool checkout** now verify that enforcement is enabled,
  re-enabling it when safe and failing closed if SQLite refuses. This preserves
  the existing local-first schema, request registry and review history.
- Added a regression that disables the PRAGMA on a pooled DBAPI connection and
  verifies enforcement is restored on its next checkout. Also corrected the
  two exact Ruff SIM117 failures in the existing parent-deletion/orphan tests.
- Isolated SQLAlchemy/SQLite behavior was reproduced locally, but the complete
  ReefVision checkout, Ruff, backend/E2E, native Windows MSI and installed GUI
  are unavailable in this runtime. Exact-head CI is the next required gate.
- The independent 1.1/1.6 Alembic 0038 collision is **not** reconciled.
  Existing typed `qc_review_queue` Workflow Builder execution, saved runs,
  provenance and researcher review gates are unchanged. **Release HOLD.**

## 2026-10-26 — QC batch audit-project provenance replay guard

- Inspected the live draft PR #77 head and all 20 exact-head workflows. CI,
  Pose Workflow Validation and ReefVision 1.0 Acceptance were blocked by the
  same Ruff SIM117 nested-context-manager error in the orphan-FK regression;
  Windows Desktop Build and 16 other workflows succeeded.
- Corrected the failing nested `with` statement without weakening the FK
  rejection test or changing production migration history.
- Keyed bulk QC retries now reject a saved audit event whose `project_id`
  differs from its parent queue's project, even when its event UUID, item ID,
  action, actor and other fields match. This is a read-only validation of
  existing records, not a rewrite of scientific observations or audit history.
- Added API regressions for both current keyed event IDs and historical
  UUIDv5-per-item layouts, asserting HTTP 409, no additional events, unchanged
  review states and annotations, and retained request-registry provenance.
- Source changes were pushed and GitHub file contents read back. Full
  exact-head CI and the new API regressions are **pending**, not accepted.
  Native Windows installed-GUI/MSI upgrade, scientific-image validation and
  independent 1.1/1.6 Alembic lineage reconciliation remain **blocked**.

## 2026-10-26 — Cross-queue QC retry provenance regression and CI formatter repair

- Preflight: isolated 1.6 draft PR #77 at `04f1bfd3`; 17/20 exact-head
  workflows succeeded. Backend jobs in CI, Pose Workflow Validation and
  ReefVision 1.0 Acceptance all stopped at Ruff formatting in two QC tests.
- Applied all four exact formatting edits from the CI log. Added an API
  regression that moves an otherwise valid keyed reviewer event to a different
  existing review queue and verifies a retry fails with HTTP 409, without
  duplicating or changing reviewer events. An explicit test-only restoration
  permits the same request to replay as an idempotent no-op.
- This protects the existing queue/project provenance contract without adding
  another QC implementation or changing the typed saved `qc_review_queue`
  Workflow Builder node. No migration, scientific approval or user-data
  rewrite was performed.
- The new regression and exact-head Ruff check have **not yet passed CI**.
  Local repository testing is blocked by GitHub DNS and missing Ruff.
  Native Windows installed GUI/MSI upgrade and 1.1/1.6 Alembic migration
  reconciliation remain outstanding. **Release HOLD.**

## 2026-10-26 — QC coordination event scope validation (Track D; pending CI)

- Audited the existing standalone comments/assignments service, bulk QC audit
  service, persisted `qc_review_queue` Workflow Builder node, and saved-graph
  regression before changing code. Class visibility and typed queue artifacts
  already existed and were not reimplemented.
- A keyed coordination-event retry now checks the event's persisted queue,
  project and item identifiers, in addition to its actor, action and content.
  Corrupted or cross-scoped audit evidence fails closed with HTTP 409 rather
  than being silently treated as a successful idempotent retry.
- Reading coordination history also rejects a mismatched persisted scope
  instead of silently exposing it under the wrong queue or hiding it.
  No repair, deletion, reviewer approval or scientific annotation mutation
  occurs automatically.
- Added standalone API regressions for cross-project and cross-queue event
  reassignment, plus a saved executable Workflow Builder queue regression
  exercising corrupted comment retries and recovery after **test-only**
  restoration. Existing typed `review_queue_reference` artifacts and
  `requires_researcher_review` gates remain unchanged.
- Fixed the precise missing blank line identified by the previous exact-head
  Ruff formatter logs. GitHub source read-back and CI are required to verify
  this iteration; Windows installed-GUI/MSI upgrade, full scientific acceptance
  and the independent 1.1/1.6 Alembic lineage conflict remain blockers.

## 2026-10-26 — QC coordination history fail-closed on fresh writes (Track D)

- Preflight: isolated draft PR #77 at `af1d9a8c`, 20 exact-head
  GitHub Actions completed: 17 successful, three backend failures
  (CI, Pose, ReefVision 1.0 Acceptance). All three fail at Ruff F821
  undefined `pytest`, `cast`, `FastAPI` in the newly added event test;
  frontend and Windows Desktop Build succeeded.
- Production gap: keyed retries and paginated history reads rejected
  cross-project/queue reviewer events, but a **new** request key could
  append fresh coordination evidence while earlier history was corrupted.
  The common queue/item scope check now rejects both reads and new writes
  before inserting audit events; it does not repair, hide or delete history.
- Standalone API regression covers cross-project and cross-queue corruption,
  blocked keyed retry, blocked new comment, empty-page history reads,
  test-only restoration, successful idempotent retry and fresh comment.
  The saved executable `qc_review_queue` Workflow Builder regression
  also rejects a new comment while its persisted review history is tainted.
- Repaired the exact missing imports reported by Ruff. No schema migration,
  new pretrained models, automatic scientific approval, user-asset deletion
  or cross-version branch changes.
- **Not accepted:** new-head CI and new regression execution, independent
  1.1/1.6 Alembic 0038 collision, native installed Windows GUI/MSI upgrade
  and rollback, real-image scientific acceptance. Release **HOLD**.

## 2026-10-26 — QC event history lint gate and pagination regression (Track D)

- Inspected exact predecessor `260fe394` CI: 20/20 Actions completed,
  17 successful and three backend failures (CI, Pose Workflow Validation,
  ReefVision 1.0 Acceptance), all reporting Ruff F841 at
  `review_queue_events.py:121` (unused `item` local).
- Removed only the unused binding in paginated history. The `_scope()` call
  still runs before any query, so corrupt cross-project/queue event history
  remains fail-closed for every page, including empty pages.
- Expanded the existing standalone API regression: valid paginated reviewer
  events retain queue-wide `total` and `current_assignee` even when the
  requested page is empty. This does not modify annotations, QC decisions,
  reviewer history, migrations or saved Workflow Builder artifacts.
- Verified changed source blobs via GitHub read-back. New exact-head Ruff,
  backend, frontend, E2E, migration, scientific and Windows acceptance results
  are pending; no local full checkout/Ruff/Windows GUI is available.
- The existing typed, persisted executable `qc_review_queue` Workflow Builder
  node and saved-workflow regressions are preserved. Independent 1.1/1.6
  Alembic `0038` collision, installed Windows MSI upgrade/rollback and
  real-image scientific acceptance remain blockers. **Release HOLD.**


## 2026-10-26 — Track D QC failed-write atomicity and formatter repair

- Audited the isolated 1.6 draft PR #77, issue #76, prior 1.0–1.5 scope, the
  existing standalone review-event service and its saved Workflow Builder QC
  queue integration. No duplicate feature or cross-version branch merge.
- At predecessor `dc058d1904ed78bb66ad6fb474706c5fbb0e4800`, 17 of 20
  GitHub Actions runs succeeded; three failed at Ruff format on two expressions
  in `test_review_queue_events_16.py` (confirmed from exact job logs).
- Corrected the two logged formatter discrepancies. Extended the standalone
  cross-project/cross-queue corruption regression to assert that a rejected
  fresh comment creates **zero additional persisted events**, and that recovery
  preserves event ordering and the researcher-review requirement. The existing
  saved executable `qc_review_queue` graph and typed review-required artifacts
  remain unchanged and must continue passing their regression suite.
- **Evidence:** test commit `f11312d3f9256cba28386b098997b0f66e61b713`;
  remote test blob `52a8f7c9ba85dfd563a73059cc335d59f233b4d8` read back.
  This documentation commit does not constitute a CI pass. Full exact-head
  tests, independent 1.1/1.6 migration lineage, Windows installed-GUI,
  MSI upgrade/rollback and representative scientific acceptance remain **HOLD**.

## 2026-10-27 — Track D SQLite FK-on backend regression repair (HOLD)

- Inspected PR #77 and issue #76, branch isolation, exact-head CI at
  `09f71bb8` and the prior full backend pytest run at `a88ab290`.
  The current 20-run matrix completed 17 successful and three Ruff-format
  failures, all pointing to a single QC test dictionary comprehension.
  The earlier full backend run reported 40 failures, 1,348 passes and
  32 skips. Most failures traced to two FK-on insertion-order defects.
- Backup creation now flushes the parent `Job` before inserting its
  `BackupRecord`, retaining one transaction and SQLite FK enforcement.
  Pose Active Learning scientist verification now flushes the
  `PoseLandmarkCorrection` before setting the candidate's
  `correction_id` FK, preserving explicit human review and provenance.
- Expanded existing standalone backup and pose review regressions to
  check enabled SQLite foreign keys, valid parent records and no
  `PRAGMA foreign_key_check` violations. Existing saved Workflow Builder
  pose training/review and QC tests remain in the full backend suite;
  no new workflow semantics, graph artifacts or approval bypasses.
- Applied the exact CI-requested Ruff formatting for
  `test_qc_bulk_provenance_16.py`. Isolated SQLAlchemy reproductions
  of both parent-before-child flush orders passed (2/2); these are
  **not** repository test results. Exact new-head CI, Ruff, pytest,
  Windows installed-GUI/MSI, migration/backward compatibility and
  representative scientific acceptance remain unverified.
- Independent 1.1/1.6 Alembic revision `0038` conflict remains open.
  No unmerged branch integration, schema rewrite, model download,
  automatic scientific approval, asset deletion, merge or release.
  **1.6 release HOLD; 1.7 and revised 1.8 untouched.**

## 2026-10-27 — Versioned QC formula identity on saved-workflow retries

- Audited the existing v2 scientific explanation validator and saved executable
  `qc_review_queue` path after the previous branch passed all 20 Actions workflows.
  A modified formula ID/version with a recomputed provenance checksum could
  previously pass the snapshot's nonempty-string and digest checks, despite
  the validator implementing only `review_priority_v1` version `1.0.0`.
- V2 snapshots now fail closed on unknown scoring formula identity **even when
  their scoring checksum is recomputed**. Future algorithms require a new
  integrity-schema contract and explicit validation, not silent reinterpretation.
- Standalone regressions cover re-signed formula ID/version changes and retain
  compatibility for historical unversioned queues. The saved executable
  Workflow Builder regression checks rejection and restoration without touching
  scientific annotations, mutable reviewer decisions or audit events.
- Release remains HOLD pending exact-head CI, 1.1/1.6 migration reconciliation,
  native Windows interactive GUI and MSI upgrade/rollback, and real scientific
  dataset acceptance.


## 2026-10-27 — Track D QC selection-provenance integrity and CI repair (HOLD)

- Inspected isolated draft PR #77, master issue #76, 1.6 code and existing
  saved executable `qc_review_queue` tests before changing anything.
  Predecessor `7a2d79dd` completed **17/20** GitHub Actions workflows:
  backend CI, pose backend and 1.0 acceptance failed at the same Ruff
  `SIM102` nested-`if` warning in the snapshot validator; Windows Desktop
  Build and the other 16 workflows passed.
- Fixed the exact `SIM102` diagnostic without changing formula identity.
  Also closed a separate v2 integrity gap: re-signed saved QC configuration
  cannot set a nonnumeric, boolean, negative or above-one
  `review_below_confidence`, or an empty/non-string QC ruleset version.
  This enforces the original API selection contract during **saved workflow
  replay**, not only at creation. Historical unversioned queues retain their
  previous compatibility path; mutable researcher decisions remain untouched.
- Added seven standalone re-signed-provenance negative regressions and an
  executable saved-graph regression that rejects an invalid re-signed
  confidence gate, restores the original snapshot and successfully replays
  the same typed `review_queue_reference` under researcher-review controls.
- Production/test commits: `bbcfa190`, `18c16433`, `37ee49e1`.
  Remote GitHub source read-back and exact-head CI remain to be checked.
  No local repository checkout or Ruff/pytest run was possible because this
  runtime cannot resolve `github.com`; no test pass is claimed here.
- **Release HOLD:** full new-head CI, independent 1.1/1.6 Alembic `0038`
  compatibility, native installed-GUI, MSI upgrade/rollback and representative
  biological-data validation remain outstanding. 1.7 and revised 1.8 untouched.

## 2026-10-27 — Track D saved QC replay guard versus scientific validator (HOLD)

- Audited draft PR #77, master issue #76, isolated 1.6 branch, the v2 QC
  integrity validator, the saved executable Workflow Builder regression, and
  both failed GitHub Actions backend logs at predecessor `5e2c3c30`.
  **18/20 workflows succeeded**; CI and ReefVision 1.0 Acceptance each ran
  1,403 passing backend tests, 1 failing test and 32 skips. The sole failure
  was a regression's expected exception message, not a silent QC acceptance.
- The saved workflow's retry-parameter equality guard correctly rejects a
  modified threshold *before* the v2 snapshot integrity validator runs.
  Strengthened the regression to explicitly invoke the snapshot validator
  on a re-signed impossible threshold (1.25) and assert its integrity failure,
  then independently assert the saved-workflow adapter's earlier retry guard.
  The test restores the original scientific configuration and verifies that
  the same saved typed QC queue remains reusable with researcher review.
- Test commit `1306fb4f6ab82a45ad564beb4ed742b31fe3d46d` was pushed and
  independently read back (blob `a2e082769e8a2404fe07ed497a014f87d3159456`).
  No production scoring, user annotations, audit history or workflow data
  were changed. Exact-head CI had not registered at initial read-back; no
  new passing test claim is made.
- **Release HOLD:** new-head CI, independent 1.1/1.6 Alembic migration
  collision, Windows interactive installed-GUI and MSI upgrade/rollback,
  and representative scientific acceptance remain unresolved. No merge,
  release, deployment, pretrained download or branch blending. 1.7/1.8
  remain unchanged.

## 2026-10-27 — Versioned QC scoring-signal identity contract (Track D)

- Audited the existing class/visibility features, standalone QC generator,
  persisted executable `qc_review_queue` Workflow Builder node, v2 snapshot
  validator, and prior 1.0–1.5 scope before editing. Prior isolated 1.6
  commit `9745300c` passed **20/20** GitHub Actions workflows.
- Found a scientific interpretation gap: v2 checks deterministic arithmetic,
  but a coherent, re-signed snapshot could add a fictitious scoring signal or
  omit a zero-weighted known signal while retaining a plausible priority.
- **Newly generated** queues use `qc-review-queue-v3`. The v3 validator freezes
  all 13 `review_priority_v1` input identities and includes the integrity
  schema version in the scoring provenance digest. The generator and saved
  Workflow Builder retry share the same validator; typed
  `review_queue_reference`, dimensionless scores, persisted runs, manual
  researcher review, retry semantics and mutable reviewer history remain.
- **Existing v2 and unversioned saved queues are not rewritten.** They retain
  their historical compatibility contract; the stronger input-set check is
  forward-only. Checksums detect accidental or inconsistent edits, not a
  malicious actor who can rewrite all records and digests.
- Added standalone v3 positive/negative regressions for a coherent 13-signal
  snapshot, invented/omitted signals with re-signed scoring and evidence
  digests, and a changed version marker. The saved executable Workflow Builder
  regression asserts v3 generation and rejects an invented signal on replay
  before restoration. No pretrained weights, network service or scientific
  approval is introduced.
- **Release HOLD:** new exact-head CI and standalone/saved-workflow tests
  must pass. Independent 1.1/1.6 Alembic 0038 reconciliation, real Windows
  MSI upgrade/rollback and interactive installed GUI, and representative
  biological-data acceptance remain outstanding. No merge or release.

## 2026-10-27 — Revision 0041 NULL-safe reviewer request identity (Track D)

- Audited the actual 0038 review-event migration and the existing 0041
  read-only migration preflight. The named two-column UNIQUE constraint
  alone does not prevent duplicate request identities in SQLite when
  either key column permits NULL; both columns are NOT NULL in real 0038.
- The 0041 startup preflight now rejects nullable `review_queue_item_id`
  or `client_request_id` even if the correct named UNIQUE exists.
  It performs no schema changes, stamping or researcher-data mutation.
- Added two forged-0041 SQLite regression cases preserving original data,
  corrected the valid 0041 migration fixture, and aligned the desktop
  synthetic 0041 fixture with real migration nullability.
- Existing QC review APIs and executable saved `qc_review_queue` Workflow
  Builder node remain unchanged; this protects their persisted reviewer
  event idempotency during startup. Independent local SQLAlchemy/SQLite
  inspector probes passed all three nullable/nonnullable cases.
- **Acceptance remains HOLD:** full exact-head CI, 1.1/1.6 Alembic 0038
  collision reconciliation, native Windows MSI/installed GUI and
  representative biological-data validation are still required.

### 2026-10-27 — Saved QC Workflow Builder input-artifact integrity (Track D)

- The executable `qc_review_queue` adapter now checks the original persisted
  `project_reference` JSON against its stored SHA-256 **before** creating or
  reusing a queue. This prevents a modified upstream project-source artifact
  from silently driving an interrupted retry, even if its `project_id` remains
  unchanged. The check is read-only and never accepts model annotations or
  overwrites a researcher's review state.
- Added two standalone negative-path tests (modified payload and modified
  checksum) plus saved-graph retry regressions for both forms of tampering,
  followed by restoration/reuse of the original queue.
- Commits: `7c604a83`, `fb3cd51b`, `96fe720a`. Validation: remote
  source read-back and line-length audit; full backend, lint, type and CI
  results are **not yet verified** for this head. Existing 1.1/1.6 Alembic
  revision collision and native Windows MSI/installed-GUI acceptance remain
  release blockers. No merge, tag, deployment or user-data mutation.

## 2026-10-27 — Actionable first-run onboarding (Track D)

- First-run help now opens the existing local class manager, QC review queue,
  saved Workflow Builder, or System status workspace.
- Project-only navigation is disabled until a project is selected. System
  status remains available without a project. Navigating closes the help
  overlay for the session without writing the permanent-dismissal preference.
- Frontend regressions cover workflow navigation, dismissal semantics, disabled
  project controls and project-independent system access.
- This is a UI navigation improvement, not a new scientific-analysis node.
  The existing typed executable `qc_review_queue` and standalone/saved-run
  regression contracts remain intact.
- Release HOLD: exact-head CI, Windows installed GUI and MSI upgrade/rollback,
  1.1/1.6 Alembic revision-0038 reconciliation, and representative science tests.


## 2026-10-27 — Attributed single-item QC actions and explicit completion check

- Audited existing class visibility, saved executable `qc_review_queue` workflow,
  append-only review events, and standalone QC routes. Bulk triage already
  accepts a self-reported reviewer label, but single-item actions previously
  recorded every transition as `local_user`, losing useful audit context.
- Start, complete, return and skip now accept an **optional** validated actor
  label. Existing API clients without a body retain the `local_user` fallback;
  no database migration, review history rewrite or workflow change is needed.
  Each action and its actor-labeled event commit atomically. Blank/oversized
  labels are rejected before state mutation.
- The standalone dashboard requests a local reviewer label for individual
  actions and asks for explicit human confirmation before marking a queue item
  complete. Completion remains **queue bookkeeping only**: neither the API nor
  Workflow Builder automatically approves model predictions or observations.
- Added API regression for all four labeled transitions, invalid-label
  atomicity and untouched annotations, plus frontend regression for required
  label, canceled/confirmed completion and attributed start. Successful
  single-item and bulk state changes now invalidate cached reviewer-event
  history so the coordination panel does not display stale audit events. The saved executable Workflow
  Builder QC node and its replay/retry tests remain unchanged and must pass
  full CI after this commit.
- Labels are **self-reported**, not authenticated identities. Exact-head
  lint/type/backend/frontend/E2E, representative science, native Windows
  installed-GUI and MSI upgrade/rollback acceptance are pending. Cross-version
  1.1/1.6 Alembic revision-0038 reconciliation remains blocked on accepted
  upstream integration. **DRAFT / HOLD; no release or approval.**


### 2026-10-27 — Single-item QC confirmation parity (Track D; not release-ready)

The individual `POST /api/v1/review-queue-items/{item_id}/complete` endpoint now requires a JSON request with `review_confirmed: true` (strict boolean). Missing, false, or string-valued confirmation returns HTTP 422 **before** any state or reviewer-event mutation. This closes a direct-API bypass of the dashboard's existing human confirmation; bulk completion already required the same explicit signal. A self-reported `actor` label remains optional for local compatibility, but is **not authenticated**. This is a deliberate pre-release tightening of the single-item API; older callers must add the explicit confirmation field.

The dashboard sends the confirmation only after the user confirms the action. The quick-review modal path now also asks for a reviewer label and explicit confirmation before submitting completion. Single-item skip reasons reject whitespace-only text and store trimmed evidence, consistent with bulk skip behavior. Completion is **QC queue bookkeeping only**: it does not verify annotations, accept predictions, or certify biological observations. Existing persisted reviewer events and saved `qc_review_queue` Workflow Builder runs remain untouched; the workflow node still requires researcher review.

Backend API regressions cover missing/false/nonboolean confirmation, absence of state/event mutation, valid confirmed completion, legacy actor defaults, blank skip rejection, and trimmed skip audit evidence. Frontend regression checks that a confirmed action passes the explicit flag. **Acceptance pending:** exact-head CI, local full suite, saved-workflow regression rerun, Windows installed GUI/MSI upgrade/rollback, real biological-data review, and cross-version Alembic revision-0038 reconciliation. No merge, tag, release, or completion notice.

## 2026-10-28 — Apply persisted segmentation class visibility in editor (Track D)

- Existing 1.6 class-visibility API persisted `segmentation_overlays` preferences,
  but the annotation editor marked that layer future-only and rendered every
  saved polygon/raster mask regardless of project/user/session hidden classes.
- The editor now resolves the existing segmentation visibility precedence and
  filters **display-only** mask overlays before viewport culling. Project
  defaults, personal preferences and temporary session overrides work without
  rewriting saved masks, class counts, review state or Workflow Builder artifacts.
  Unlabeled masks remain visible. The segmentation layer is now marked live in
  the editor; box/prediction visibility remains independent.
- Frontend regressions cover project defaults, independent box rendering,
  personal-over-project precedence, session reset, no extra annotation fetch,
  and no save request. Full Vitest/TypeScript/E2E and installed-Windows GUI
  acceptance remain pending. No migration or new workflow node is appropriate
  for a presentation-only visibility filter.

## 2026-10-28 — v3 binary QC observation integrity (Track D)

- Audited the frozen v3 queue generator and saved Workflow Builder replay checks.
  The generator emits `unreviewed_state` and `missing_group_metadata` only as
  binary 0/1 observations, but the replay validator previously accepted
  fractional raw values between zero and one if re-signed.
- Versioned v3 replay now rejects fractional values for these two flags.
  Continuous proportions remain continuous; pending-proposal counts retain
  their nonnegative integer and saturation rules. Historical unversioned/v2
  queue compatibility, mutable reviewer decisions and original data are intact.
- Standalone regressions cover four re-signed false flags and eight valid
  integer/float binary states. The real saved executable `qc_review_queue`
  regression rejects both fractional flags before queue reuse, preserves a
  completed review and succeeds after original evidence is restored.
- **Development only:** exact-head CI, Windows MSI upgrade/rollback, installed
  GUI, representative biological-data validation and independent 1.1/1.6
  Alembic revision-0038 reconciliation remain release blockers.

## 2026-10-28 — Packaged first-project-write migration smoke (Track D)

- Audited the historical disposable Windows clean-install failure from Actions
  run 39954832671, evidence artifact 12504626823. MSI installation and first
  API launch succeeded, but the report recorded `schema_status=uninitialized`
  and the first `POST /api/v1/projects` failed HTTP 500. The archived API and
  backend log tails contain no request traceback. This is historical evidence,
  **not** proof that the current branch still has the same failure.
- Added a real SQLite/Alembic regression in
  `test_desktop_real_migration_16.py`: migrate a fresh disposable database,
  require HTTP `up_to_date`, create a blank project through the actual API,
  reopen the app and verify the same persisted project and migration status.
  No `Base.metadata.create_all` shortcut or researcher data is used.
- Added this regression to the focused Windows installer build preflight in
  `build-desktop.yml`, before the multi-GB MSI build. This is a non-frozen
  Windows API smoke test; it does **not** replace an installed MSI/GUI run.
- Commits: `62794974` and `a5c6d5d1`. Exact-head CI and native installed
  Windows acceptance are pending. The independent 1.1/1.6 Alembic 0038
  collision and representative biological-data validation remain blockers.
  **HOLD — do not merge, tag, publish or notify completion.**


## 2026-10-28 — Real legacy-0037 desktop upgrade preservation regression (Track D)

- Added a disposable SQLite/Alembic regression to
  `test_desktop_real_migration_16.py`: migrate to the **real 0037 schema**,
  create a project and label class through the API, persist a project-level
  hidden-class default and an explicitly empty per-user override, then run the
  actual 1.6 desktop migration to 0041. Reopen the API and verify original
  project, class, local identity and both visibility scopes remain unchanged.
  Verify that a new project can be written after the upgrade and survives
  another desktop restart. No `Base.metadata.create_all`, manual stamp,
  deletion or user database is involved.
- This exercises the **isolated 1.6** lineage only. The independently authored
  1.1 revision 0038 is still incompatible and must not be merged, stamped or
  applied to an installed 1.6 database without reviewed reconciliation.
- Release remains **HOLD** until exact-head CI and native installed Windows
  MSI/GUI, upgrade/rollback and representative scientific-data acceptance pass.


## 2026-10-28 — Legacy multi-user visibility and foreign 0038 desktop guards

- Audited existing 0012 class-visibility persistence, isolated 1.6 Alembic
  revisions 0038–0041, desktop migration guard, real migration tests and
  exact predecessor CI (run 40673702046: backend/frontend both successful).
- Added a real 0037-to-0041 SQLite upgrade regression using two separate local
  identity directories and one shared research database. It creates two classes,
  a project default, an explicitly empty override for researcher A and a
  different override for researcher B. After upgrade and two desktop migration
  invocations, both identities, overrides, class IDs and project defaults must
  remain independent and durable. No metadata.create_all shortcut is used.
- Added a real desktop migration refusal regression for a 0038 stamp carrying
  1.1-style scientific/environmental tables. The migration must reject before
  creating the 1.6 review-events table, preserving the original project,
  scientific record and revision marker. This is a simulated conflicting
  schema, not a validated full 1.1-to-1.6 migration.
- Tests are additive and do not alter the database schema, production APIs,
  local identity implementation, scientific records or saved Workflow Builder
  behavior. The existing executable QC workflow remains the review-gated
  integration for 1.6.
- **Acceptance remains HOLD:** exact-new-head CI, independent 1.1/1.6
  migration reconciliation, real MSI upgrade/rollback, installed GUI and
  representative biological-data testing are still required.


## 2026-10-28 — SQLite concurrent-writer retry contract (Track D)

- Audited existing 1.6 deterministic workflow-owned queue IDs, saved
  `project_source -> qc_review_queue` execution, manual QC review history,
  and prior exact-head CI. Previous commit `bc59a451` passed its push
  backend/frontend CI, but Windows installed-GUI and cross-version migration
  acceptance remain separate blockers.
- The deterministic UUIDv5 primary key already rejects a competing writer
  that reaches an INSERT after another has committed (`IntegrityError`).
  When the other SQLite writer still holds its transaction, SQLite instead
  raises `SQLITE_BUSY` or `SQLITE_LOCKED` (`OperationalError`).
  The saved-workflow adapter now converts only those specific SQLite
  contention codes into a controlled, rollback-safe validation error
  instructing an explicit retry. Other SQL/database errors propagate.
- Added an actual two-connection SQLite busy-lock regression and an
  executable persisted workflow regression. The latter simulates an
  interrupted initial queue creation, holds a separate SQLite write lock,
  requires fail-closed rejection without altering independent manual
  reviewer comments, releases the lock, then verifies two idempotent
  retries with the same queue ID, typed dimensionless output, and
  researcher-approval requirement. The fixture modifies only disposable
  test data, never user research assets.
- No migration, background auto-retry loop, cloud dependency, automatic
  annotation approval or cross-version branch integration was introduced.
  **Acceptance HOLD:** exact-new-head Ruff/mypy/pytest and relevant CI,
  1.1/1.6 revision-0038 reconciliation, native Windows MSI upgrade/rollback,
  installed-GUI testing, and representative biological-data checks.


## 2026-10-29 — Native Windows QC workflow concurrency acceptance gate (Track D)

- Audited existing class visibility, review queue controls, saved executable
  `project_source -> qc_review_queue` Workflow Builder tests, 1.6 roadmap,
  and exact predecessor `eb0621d2` CI (backend and frontend succeeded).
- The Windows MSI build previously ran desktop migration and model-package
  smoke tests but **did not run** the existing independent-process SQLite QC
  workflow race regression. This left an explicit native Windows concurrency
  acceptance gap even though the portable backend suite ran on Linux.
- Added `test_workflow_queue_multiprocess_16.py` and
  `test_workflow_queue_sqlite_contention_16.py` to the Windows installer
  build's focused backend pytest preflight, before the MSI build. The tests
  exercise a real saved workflow, SQLite writer contention, stable typed
  `review_queue_reference` output with dimensionless scores, mandatory human
  review, and preservation of independent manual reviewer history. Failure
  blocks the installer artifact build; no migration, model download, data
  mutation, or production workflow behavior is introduced by this change.
- **Acceptance is not yet proven** until exact-head Windows Actions execute
  the tests successfully. A green Linux CI result alone does not prove native
  Windows multi-process behavior. MSI upgrade/rollback, interactive installed
  GUI, 1.1/1.6 independent revision-0038 reconciliation and representative
  biological-data acceptance remain release blockers. Do not merge/release.

## 2026-10-29 — Manual bulk QC writer contention (Track D)

- **Gap audited:** 1.6 already supports persisted class visibility, manual
  review/assignment/comments/bulk triage, and a saved executable
  `project_source -> qc_review_queue` Workflow Builder node. Its queue
  creation adapter already handles SQLite BUSY/LOCKED, but a *separate*
  bulk-triage transaction only handled integrity collisions. Two local
  reviewers could therefore receive an unhandled HTTP 500 when the second
  SQLite writer encountered a lock during manual triage.
- **Implementation:** `review_queue_bulk.py` now rolls back a failed bulk
  transaction and returns a controlled retryable conflict for actual SQLite
  BUSY/LOCKED primary or extended error codes. Other database operational
  errors propagate; no reviewer state is claimed committed on a lock.
  Reusing the original client request UUID after the lock clears remains the
  idempotent retry path. No automatic acceptance of scientific observations.
- **Tests:** `test_review_queue_bulk_sqlite_contention_16.py` uses a real
  second SQLite writer, both standalone QC queues and a persisted executable
  Workflow Builder graph, and verifies zero partial events/state changes,
  typed dimensionless review artifacts, successful keyed retry, append-only
  researcher history, and unchanged unverified annotations. A negative test
  rejects misclassifying an unrelated SQLite operational failure. The Windows
  MSI build preflight now includes these tests.
- **Evidence:** isolated commits `655166a4`, `05337cfa`, `7b73592d`.
  Repository read-back and exact-head CI still required; no local full
  pytest/Ruff/Windows PowerShell run is claimed because the container cannot
  resolve github.com for a checkout. Windows installed GUI, real MSI upgrade
  and rollback, independent 1.1/1.6 Alembic 0038 reconciliation, and
  representative biological-data acceptance remain **HOLD**.
