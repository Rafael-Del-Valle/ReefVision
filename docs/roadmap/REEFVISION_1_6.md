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
