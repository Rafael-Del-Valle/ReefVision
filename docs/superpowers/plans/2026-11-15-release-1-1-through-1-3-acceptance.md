# ReefVision 1.1-1.3 Release Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the 1.1 stale-aggregate Project Exchange blocker, reconcile and validate the three release candidates, and update draft PRs #71, #85, and #87 plus issue #76 with exact evidence.

**Architecture:** Treat saved aggregate evidence as an immutable historical snapshot whose internal reproducibility is validated independently from the imported project's current state. Merge current `main` into the 1.1 line, preserve its additive migration and version contracts, then reproduce the regression on the stacked 1.2 and 1.3 heads and forward-port only the commits each branch needs.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy, Pydantic, Alembic, pytest, Ruff, mypy, React/TypeScript/Vitest/Playwright, Tauri/Rust, PowerShell/WiX MSI, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-15-release-1-1-through-1-3-acceptance-design.md`

## Global Constraints

- Published baseline is tag `v1.0.3` at `e94dad6a3bece7b776bf45776bc5d06cfbc2c0dc`; do not modify the tag or release assets.
- Preserve original source images, verified review history, immutable dataset versions, registered-model lineage, and local-only operation.
- Do not edit or renumber an applied migration. Add a uniquely named merge revision only if Alembic reports multiple heads after reconciliation.
- Keep PR #85 based on `develop/reefvision-1.2` and PR #87 based on `codex/reefvision-1.2-reefpose`.
- Never commit credentials, checkpoints, installer binaries, research media, exported databases, or user profiles.
- Synthetic fixtures establish engineering behavior only. Representative scientific acceptance remains blocked when independently reviewed references are unavailable.
- Do not merge, tag, publish, force-push, or install candidates into the user's normal Windows profile.

## Review Focus

- A rehashed archive with group totals that do not match its saved image snapshot must fail atomically; Task 2 adds the tamper test.
- A saved group key may resemble another remapped UUID but must remain researcher-authored literal metadata; Task 2 retains and extends the existing literal-key assertion.
- An imported stale result must remain stale without mutating its historical evidence, while a new calculation must use current grouping; Task 2 covers both outcomes.
- Merge conflict resolution must not downgrade 1.1 to 1.0.3 or remove 1.0.3 camera/training/upgrade safeguards; Tasks 1 and 4 run version, Windows harness, and upgrade checks.
- Later branches must not receive unrelated 1.1 history or duplicate migrations; Tasks 5 and 6 compare ancestry, migration heads, and exact diffs before committing.

---

### Task 1: Reconcile PR #71 with current `main`

**Files:**
- Merge/conflict review: `.github/workflows/build-desktop.yml`
- Merge/conflict review: `apps/api/reefvision/__init__.py`
- Merge/conflict review: `apps/api/reefvision/api/routes/videos.py`
- Merge/conflict review: `apps/api/reefvision/schemas/videos.py`
- Merge/conflict review: `apps/api/reefvision/services/video_tracks.py`
- Merge/conflict review: `apps/api/reefvision/tests/test_release_model_policy.py`
- Merge/conflict review: `apps/api/reefvision/tests/test_version_consistency.py`
- Merge/conflict review: `apps/web/package.json`
- Merge/conflict review: `apps/web/package-lock.json`
- Merge/conflict review: `apps/web/src-tauri/Cargo.toml`
- Merge/conflict review: `apps/web/src-tauri/Cargo.lock`
- Merge/conflict review: `apps/web/src-tauri/build.rs`
- Merge/conflict review: `apps/web/src-tauri/tauri.conf.json`
- Merge/conflict review: `apps/web/src/App.tsx`
- Merge/conflict review: `apps/web/src/App.test.tsx`
- Merge/conflict review: `apps/web/src/features/annotation-editor/AnnotationEditor.tsx`
- Merge/conflict review: `apps/web/src/features/video/VideoTrackingWorkspace.tsx`
- Merge/conflict review: `apps/web/src/features/video/VideoTrackingWorkspace.test.tsx`
- Merge/conflict review: `apps/web/src/features/video/videoApi.ts`
- Merge/conflict review: `package.json`
- Merge/conflict review: `pyproject.toml`
- Merge/conflict review: `scripts/acceptance-windows-clean-install.ps1`
- Merge/conflict review: `scripts/build-desktop-backend.ps1`
- Merge/conflict review: `scripts/build-desktop.ps1`
- Merge/conflict review: `scripts/check-release-version.py`
- Merge/conflict review: `scripts/lib/reefvision-commands.ps1`
- Merge/conflict review: `scripts/lib/windows-clean-acceptance.ps1`
- Merge/conflict review: `scripts/test-windows-clean-install-harness.ps1`
- Add only if necessary: `apps/api/migrations/versions/<unique_merge_revision>.py`

**Interfaces:**
- Consumes: `origin/main` at `e94dad6a3bece7b776bf45776bc5d06cfbc2c0dc` and `origin/develop/reefvision-1.1` at `1ff78f20f47e34bea0a9cf3ffadef4aa908c4538`.
- Produces: a normal merge commit on local `develop/reefvision-1.1`, product version `1.1.0`, one Alembic head, and retained 1.0.3 upgrade safeguards.

- [ ] **Step 1: Attach the worktree to the existing branch and verify the fetched heads have not moved**

Run:

```powershell
git fetch origin main develop/reefvision-1.1
git switch -c develop/reefvision-1.1 --track origin/develop/reefvision-1.1
git rev-parse HEAD origin/develop/reefvision-1.1 origin/main
git status --short
```

Expected: local and remote 1.1 match, the tree contains only the approved design/plan files, and no concurrent remote commit is silently overwritten.

- [ ] **Step 2: Merge current `main` without committing and resolve conflicts by contract**

Run: `git merge --no-ff --no-commit origin/main`

Resolution rules:

- retain 1.1.0 in Python, root/web package, Cargo, Tauri, workflows, and installer checks;
- retain the AGPL license file and AGPL metadata introduced on published `main`;
- retain both sides' video/camera/installed-workflow fixes;
- retain all existing migration files and revision identifiers;
- do not choose an entire side for a conflicted application file without inspecting both diffs.

- [ ] **Step 3: Verify migration topology before deciding whether code is needed**

Run:

```powershell
$env:PYTHONPATH='apps/api'
python -m alembic -c apps/api/alembic.ini heads
python -m pytest apps/api/reefvision/tests/test_mask_migration_lineage.py apps/api/reefvision/tests/test_scientific_data_migration.py apps/api/reefvision/tests/test_computed_aggregate_migration.py -q
```

Expected: one head. If and only if multiple heads remain, create a new merge revision with a unique non-conflicting ID and `down_revision` containing both existing heads; do not edit either predecessor.

- [ ] **Step 4: Run focused merge-conflict checks**

Run:

```powershell
python scripts/check-release-version.py
python -m pytest apps/api/reefvision/tests/test_release_model_policy.py apps/api/reefvision/tests/test_version_consistency.py apps/api/reefvision/tests/test_video_tracking_phase6.py -q
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File scripts/test-windows-clean-install-harness.ps1
```

Expected: 1.1 metadata is consistent and the installed camera/training/upgrade harness remains intact.

- [ ] **Step 5: Commit the reconciliation**

Run:

```powershell
git add -A
git commit -m "Merge main into ReefVision 1.1 release candidate"
```

Expected: a two-parent merge commit; no force-push.

### Task 2: Preserve stale reviewed aggregates through Project Exchange

**Files:**
- Modify: `apps/api/reefvision/tests/test_computed_aggregate_project_exchange.py`
- Modify: `apps/api/reefvision/services/project_exchange_computed.py`

**Interfaces:**
- Consumes: `payload_json.image_snapshot`, `observation_snapshot`, `groups`, `excluded_proposals_by_status`, definition/workflow provenance, exported current image rows, and `id_map`.
- Produces: `_validate_aggregate_result(...) -> None` that authenticates historical evidence independently of current group keys; `remap_computed_sections(...)` that preserves literal historical group keys while remapping declared IDs and rebuilding hashes.

- [ ] **Step 1: Write the failing stale round-trip regression**

Add `test_stale_annotation_aggregate_round_trip_preserves_history_and_recalculates_current_grouping`:

- create and save a reviewed `image_group_key` aggregate;
- patch one source image to a different non-empty group key after the result is saved;
- assert the source validation endpoint reports `current is False` and includes `image_group_key_changed:<image_id>`;
- export and import the project;
- assert import returns 201 rather than the reproduced 400;
- assert the imported historical result retains its original groups, counts, evidence hash semantics, workflow provenance, and remapped image/observation IDs;
- assert imported validation is stale for the remapped image with the group-key-change reason;
- calculate again from the imported definition and selected image IDs;
- assert the new result uses the current two-group layout and does not mutate the historical result.

- [ ] **Step 2: Extend atomic corruption coverage**

Add corruption cases that rehash the archive after changing:

- a saved image snapshot group key without matching groups;
- a group unit key without matching saved image snapshots;
- the stale image checksum;
- workflow node/run linkage;
- evidence/provenance consistency.

For every case assert HTTP 400, unchanged database counts, and no new project directory.

- [ ] **Step 3: Run the focused test and confirm RED**

Run:

```powershell
$env:PYTHONPATH='apps/api'
python -m pytest apps/api/reefvision/tests/test_computed_aggregate_project_exchange.py -q
```

Expected: the new stale round-trip fails at import with the reproduced computed-aggregate image snapshot/timestamp mismatch; existing corruption cases remain green.

- [ ] **Step 4: Implement the minimal historical-evidence validation boundary**

In `_validate_aggregate_result`:

- validate immutable image identity/ownership and checksum against exported image rows;
- reconstruct independent units and group totals from `image_snapshot[*].group_key`, not `sections["images"][*].group_key`;
- continue validating observation rows, label ownership, proposal exclusions, deterministic ordering, totals, means, evidence hash, content hash, provenance, and workflow run/node linkage;
- accept a current non-empty group-key divergence as stale historical evidence;
- validate `payload.observed_at == row.observed_at` and require `max(exported image created_at) <= observed_at <= result created_at`; this authenticates a historical result without demanding equality with a later image update;
- fail closed on malformed, missing, duplicate, cross-project, or internally inconsistent evidence.

In `remap_computed_sections` preserve saved `image_snapshot[*].group_key` and `groups[*].unit_key` for group-key aggregation, remap only declared IDs, and rebuild evidence/provenance/content hashes.

- [ ] **Step 5: Run GREEN and prove the regression detects the fix**

Run the focused module, then temporarily reverse only the historical-group selection logic and confirm the stale test fails; restore the fix and rerun.

Expected final command:

```powershell
python -m pytest apps/api/reefvision/tests/test_computed_aggregate_project_exchange.py apps/api/reefvision/tests/test_computed_aggregate_metrics.py apps/api/reefvision/tests/test_workflow_computed_aggregates.py -q
```

Expected: all focused aggregate, tamper, and workflow tests pass.

- [ ] **Step 6: Commit the repair**

Run:

```powershell
git add apps/api/reefvision/services/project_exchange_computed.py apps/api/reefvision/tests/test_computed_aggregate_project_exchange.py
git commit -m "fix(exchange): preserve stale aggregate evidence"
```

### Task 3: Align 1.1 licensing and release metadata

**Files:**
- Verify/modify: `LICENSE`
- Verify/modify: `README.md`
- Verify/modify: `CONTRIBUTING.md`
- Modify: `pyproject.toml`
- Modify: `apps/web/src-tauri/Cargo.toml`
- Verify/modify: `apps/api/reefvision/__init__.py`
- Verify/modify: `package.json`
- Verify/modify: `apps/web/package.json`
- Verify/modify: `apps/web/package-lock.json`
- Verify/modify: `apps/web/src-tauri/tauri.conf.json`
- Verify/modify: `.github/workflows/build-desktop.yml`

**Interfaces:**
- Consumes: published `main` license decision and 1.1 version contract.
- Produces: AGPL-3.0-only across project metadata, exact 1.1.0 version consistency, and installer provenance generated from the build HEAD rather than a stale candidate SHA.

- [ ] **Step 1: Add or update consistency tests before metadata edits**

Extend `apps/api/reefvision/tests/test_version_consistency.py` or `test_release_model_policy.py` to assert:

- root `LICENSE` starts with the GNU Affero GPL v3 text;
- Python and Cargo license identifiers are `AGPL-3.0-only`;
- README and CONTRIBUTING point to the same license;
- all product version sources equal `1.1.0`;
- build provenance reads the current clean Git HEAD and workflow verification passes the event SHA rather than embedding a 1.1 candidate SHA.

- [ ] **Step 2: Run the metadata test and confirm any remaining drift fails**

Run: `python -m pytest apps/api/reefvision/tests/test_version_consistency.py apps/api/reefvision/tests/test_release_model_policy.py -q`

- [ ] **Step 3: Apply the minimal metadata corrections**

Retain the published AGPL license language and the README's previously-licensed-copy note from `main`; retain `1.1.0` everywhere version-specific. Do not add per-source headers unless the repository already has an established header policy.

- [ ] **Step 4: Verify and commit**

Run:

```powershell
python scripts/check-release-version.py
python -m pytest apps/api/reefvision/tests/test_version_consistency.py apps/api/reefvision/tests/test_release_model_policy.py -q
git add LICENSE README.md CONTRIBUTING.md pyproject.toml apps/web/src-tauri/Cargo.toml apps/api/reefvision/__init__.py package.json apps/web/package.json apps/web/package-lock.json apps/web/src-tauri/tauri.conf.json .github/workflows/build-desktop.yml apps/api/reefvision/tests
git commit -m "chore(release): align ReefVision 1.1 licensing metadata"
```

### Task 4: Verify, package, and exercise ReefVision 1.1

**Files:**
- Evidence only; do not commit generated `.venv`, `node_modules`, `dist`, MSI/CAB, reports containing user paths, profiles, checkpoints, or media.

**Interfaces:**
- Consumes: clean committed 1.1 SHA and published 1.0.3 installer/profile backup.
- Produces: source, migration, installer, clean-install, upgrade, rollback, older-build rejection, GPU, provider, and representative-data evidence or exact blockers.

- [ ] **Step 1: Install branch-local dependencies without modifying lockfiles**

Run the repository-supported Python environment setup, then `npm ci --prefix apps/web`. Confirm `git status --short` remains clean.

- [ ] **Step 2: Run the full source gate**

Run:

```powershell
$env:PYTHONPATH='apps/api'
python -m ruff format --check apps/api
python -m ruff check apps/api
python -m mypy -p reefvision
python -m pytest apps/api/reefvision/tests --pose-interop-integration
npm --prefix apps/web run lockfile:check
npm --prefix apps/web run format:check
npm --prefix apps/web run typecheck
npm --prefix apps/web run test
npm --prefix apps/web run build
npm --prefix apps/web run test:e2e
```

Expected: zero failures. Fix and rerun any recoverable source regression before continuing.

- [ ] **Step 3: Run fresh and supported migration/restore paths**

Exercise:

- fresh database `upgrade head`, `downgrade base`, `upgrade head`;
- published 1.0.3 database to the 1.1 head;
- verified pre-upgrade backup restore;
- 1.1 database opened with the older build, expecting a read-only rejection and an unchanged database SHA-256.

Use disposable copies only and record before/after hashes.

- [ ] **Step 4: Build from the exact clean SHA and verify MSI/CAB provenance**

Run the repository's `scripts/build-desktop.ps1`, `scripts/verify-windows-installer-payload.ps1`, `scripts/test-windows-installer-payload.ps1`, and `scripts/test-windows-clean-install-harness.ps1`. Verify ProductVersion `1.1.0`, source commit equal to `git rev-parse HEAD`, MSI Media entries, and every external CAB hash.

- [ ] **Step 5: Run installed Windows acceptance in a disposable interactive profile**

Verify first-open rendering, real camera JPEG import with unchanged source checksum, reopen, scientific exchange, clean install, 1.0.3 upgrade, backup rollback, and uninstall/retained-data behavior. Use a compatible registered local checkpoint for installed RTX 3090 prediction and explicit review if one is available; otherwise record the exact checkpoint requirement.

- [ ] **Step 6: Run optional live scientific checks when inputs exist**

Run authenticated Copernicus acquisition and surveyed-reference comparisons only if credentials, dataset identifiers, time/space bounds, and frozen references are available. Never print or commit credentials or raw research assets.

- [ ] **Step 7: Push without force after refreshing the remote lease**

Run:

```powershell
git fetch origin develop/reefvision-1.1
git rev-list --left-right --count origin/develop/reefvision-1.1...HEAD
git push origin HEAD:develop/reefvision-1.1
```

Expected: fast-forward push. If the remote advanced, stop and reconcile the new commits before pushing.

### Task 5: Reproduce and selectively forward-port to ReefVision 1.2

**Files:**
- Conditional modify: `apps/api/reefvision/services/project_exchange_computed.py`
- Conditional modify: `apps/api/reefvision/tests/test_computed_aggregate_project_exchange.py`
- Evidence/update: `docs/REEFVISION_1_2_REEFPOSE_INTEGRATION.md`

**Interfaces:**
- Consumes: PR #85 current head, Task 2 regression, and only the minimal validated repair commit.
- Produces: a 1.2 head with the stale exchange regression passing, version `1.2.0`, unchanged migration IDs and model/review lineage.

- [ ] **Step 1: Switch the detached worktree to the existing branch and refresh it**

Run `git fetch origin codex/reefvision-1.2-reefpose`, create the local tracking branch, and verify the remote head before edits.

- [ ] **Step 2: Add/run the stale regression before porting implementation**

Apply only the Task 2 test hunk and run its exact test. If it already passes, do not port product code; retain only a justified regression commit if it adds missing coverage. If it fails with the same root cause, apply the minimal service hunk and rerun red/green.

- [ ] **Step 3: Run 1.2 workflow and migration acceptance**

Run focused coral graph/growth, ReefPose review, Project Exchange, backup/restore, workflow replay, and migration suites, followed by the full source gate from Task 4. Exercise available 1.1 to 1.2 and prior-candidate to current-candidate disposable profiles. Verify calibration, measurement IDs, graph review history, and replay.

- [ ] **Step 4: Run installed coral workflow and representative comparisons**

At representative display scaling exercise camera JPEG, registered segmentation, explicit mask acceptance, rejected graph edit, unresolved gap/branch, reviewed graph, calibrated two-date growth, restart, exchange, and backup restore. Use independently reviewed coral pairs/animal identities if available; otherwise record the exact missing media, calibration, checkpoint, and reference package.

- [ ] **Step 5: Commit and fast-forward push only the proven 1.2 changes**

Commit message: `fix(exchange): preserve stale aggregate evidence in 1.2` when code changes are needed, or `test(exchange): cover stale aggregate import in 1.2` when only coverage is needed. Refresh remote and push without force.

### Task 6: Reproduce and selectively forward-port to ReefVision 1.3

**Files:**
- Conditional modify: `apps/api/reefvision/services/project_exchange_computed.py`
- Conditional modify: `apps/api/reefvision/tests/test_computed_aggregate_project_exchange.py`
- Evidence/update: `docs/REEFVISION_1_3_SCIENTIFIC_WORKFLOWS.md`

**Interfaces:**
- Consumes: PR #87 current head, Task 2 regression, current PR #85 base, and registered local temporal/static checkpoints.
- Produces: a 1.3 head with preserved 1.2 scientific lineage, matching standalone/Workflow Builder behavior, and explicit representative-performance status.

- [ ] **Step 1: Refresh branch and base without changing PR topology**

Switch the detached worktree to local `codex/reefvision-1.3-scientific-workflows`, fetch both its head and `codex/reefvision-1.2-reefpose`, and verify the base ancestry. Incorporate the final 1.2 repair only if required and only by an explicit non-force commit.

- [ ] **Step 2: Reproduce the stale regression and port only applicable hunks**

Follow Task 5's test-first decision rule, then run the aggregate, workflow, exchange, backup, and migration suites.

- [ ] **Step 3: Run temporal/static installed workflow acceptance**

Exercise registered frame inference, temporal refinement, explicit review, anatomical measurements/event scoring, export, saved-workflow replay, restart, exchange, backup restore, and 1.2 to 1.3 migration with model lineage preserved. Verify standalone and Workflow Builder parity from identical inputs.

- [ ] **Step 4: Run frozen representative evaluation if inputs exist**

Use the same upstream frame checkpoint and independently grouped held-out recordings for frame-only versus temporal evaluation. Report landmark error, event precision/recall, timing/count error, valid observation time, missed/partial events, exclusions, and group-level uncertainty where supported. Separately compare static detector counts, including zero-count images. If inputs are missing, keep prior synthetic results labeled engineering evidence and state the shortest next step.

- [ ] **Step 5: Run the complete source/installer/migration gates and push**

Repeat Task 4's full gate with version `1.3.0` and schema head `b13_temporal_0001`; build/verify MSI and CABs if the environment permits. Refresh and fast-forward push without force.

### Task 7: Update PRs and issue #76 with exact evidence

**Files:**
- GitHub draft PR #71 body/comment
- GitHub draft PR #85 body/comment
- GitHub draft PR #87 body/comment
- GitHub issue #76 coordination comment

**Interfaces:**
- Consumes: exact final SHAs, fresh local command outputs, GitHub Actions runs, installer artifacts/hashes, upgrade/rollback reports, representative-data results, and blockers.
- Produces: evidence-backed release status without merging or publishing.

- [ ] **Step 1: Verify each pushed remote SHA and CI registration**

Read back branch refs and compare them with local `git rev-parse HEAD`. Collect exact-head workflow runs; distinguish queued/in-progress from passed and never infer success from a prior SHA.

- [ ] **Step 2: Update each draft PR**

Include:

- final SHA and source-diff summary;
- CI commands/counts and workflow links;
- installer version, exact source SHA, MSI/CAB links and hashes;
- clean install, upgrade, rollback, older-build rejection, and backup paths exercised;
- hardware and installed-GUI evidence;
- representative-data agreement, exclusions, and unresolved cases;
- exact missing input/environment and shortest reproducible next step for every blocked gate.

- [ ] **Step 3: Coordinate issue #76**

Add one consolidated comment with a version-by-version table. Do not check a release-ready box or emit a completion notification unless every required release gate has evidence on the exact final SHA.

- [ ] **Step 4: Final verification and handoff**

For every changed branch run `git status --short`, verify a clean tree, list the final SHA, and confirm the remote branch equals it. Report no merge/tag/publication action and call out every remaining blocker.
