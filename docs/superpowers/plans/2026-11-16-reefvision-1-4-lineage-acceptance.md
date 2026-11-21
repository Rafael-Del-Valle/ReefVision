# ReefVision 1.4 Installed Lineage Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the deterministic engineering portion of `rv14-lineage-upgrade` by exercising validated 1.3 and both legacy 1.4 spatial profiles through the exact installed 1.4 candidate, Project Exchange, backup restoration, and historical-build compatibility where the retained 1.3 installer is available.

**Architecture:** Extend PR #89's disposable-profile generator into a deterministic, independently verifiable fixture contract. Add an optional lineage mode to the existing marker-gated Windows acceptance harness and a dedicated workflow matrix that consumes the exact candidate MSI/CAB payload; retain the existing published-1.0.3 upgrade job unchanged. Evidence remains split between synthetic data-profile migration, actual 1.3-to-1.4 MSI upgrade, and representative prior-user profiles.

**Tech Stack:** Python 3.12, SQLite, SQLAlchemy/Alembic, PowerShell 7, GitHub Actions, installed Tauri/WebView2 desktop and packaged FastAPI sidecar.

**Spec:** `docs/superpowers/specs/2026-11-15-reefvision-through-2-0-program-design.md`

## Global Constraints

- Never modify original source media or a non-disposable ReefVision data directory.
- Preserve the applied numeric `0038` and `0039` migrations; do not edit their bodies.
- Seed only a marker-gated isolated acceptance root and refuse reparse points or unsafe containment.
- Candidate installer, every MSI-declared CAB, and build provenance must come from the exact tested SHA.
- Published `v1.0.3` assets and its existing upgrade acceptance remain intact.
- Synthetic engineering evidence cannot satisfy representative-user or biological validation.
- No merge, tag, release, or publication is authorized.

## Review Focus

- A manifest path or profile-relative path that escapes the fixture root must fail before installation or file copying.
- A changed database, source asset, or backup hash must fail before the installed desktop launches.
- A legacy database whose declared revision and schema fingerprint disagree must fail without mutation.
- Historical 1.3 compatibility checks must never point at the normal ReefVision profile and must prove rejection leaves the upgraded database byte-identical.
- Exchange re-import must inspect remapped records and media by content/source hashes rather than incorrectly expecting imported UUIDs to stay identical.

---

### Task 1: Deterministic and independently verifiable lineage profiles

**Files:**
- Modify: `scripts/create_windows_lineage_fixtures.py`
- Create: `scripts/verify_windows_lineage_fixture.py`
- Modify: `apps/api/reefvision/tests/test_windows_lineage_fixtures_v14.py`

**Interfaces:**
- Consumes: preserved 1.3 and legacy-spatial migrations plus project/scientific/spatial services.
- Produces: manifest schema `reefvision-windows-lineage-fixtures-1` with profile name, revision, project ID, evidence kind/ID, database/backup/source paths and SHA-256 values; verifier CLI `python scripts/verify_windows_lineage_fixture.py MANIFEST --profile NAME`.

- [ ] **Step 1: Extend the existing test with deterministic IDs, complete hashes, verifier success, path escape, tamper, revision mismatch, and Windows URL-escaping regressions.**
- [ ] **Step 2: Run the focused test and confirm the new assertions fail for missing manifest/verifier behavior while retaining the observed Windows `%` interpolation failure as a separate root cause.**
- [ ] **Step 3: Implement the minimal deterministic generator and read-only verifier; escape rendered Alembic URLs in the test.**
- [ ] **Step 4: Run the focused fixture test, Ruff format/lint, and scoped mypy.**
- [ ] **Step 5: Commit the fixture contract.**

### Task 2: Marker-gated installed lineage mode

**Files:**
- Modify: `scripts/acceptance-windows-clean-install.ps1`
- Modify: `scripts/lib/windows-clean-acceptance.ps1`
- Modify: `scripts/test-windows-clean-install-harness.ps1`

**Interfaces:**
- Consumes: a verified fixture manifest/profile plus the existing candidate and optional previous MSI parameters.
- Produces: installed acceptance report sections for lineage preflight, before/after revision, preserved IDs/source hashes, Project Exchange export/import, restored backup, and historical-build open/reject behavior.

- [ ] **Step 1: Add failing harness assertions for lineage parameters, safe contained copies, pre-launch hash checks, initial/final revision checks, seeded evidence inspection, exchange import, separate restore root, and byte-stable historical rejection.**
- [ ] **Step 2: Run `scripts/test-windows-clean-install-harness.ps1` and confirm it fails on the first missing lineage contract.**
- [ ] **Step 3: Implement optional lineage mode without changing the default clean-install and published-1.0.3 upgrade paths.**
- [ ] **Step 4: Run the harness assertions and PowerShell parser checks.**
- [ ] **Step 5: Commit the installed harness increment.**

### Task 3: Exact-candidate Windows lineage matrix

**Files:**
- Modify: `.github/workflows/build-desktop.yml`
- Modify: `scripts/test-windows-clean-install-harness.ps1`

**Interfaces:**
- Consumes: exact-head 1.4 MSI/CAB artifacts, generated profiles, and non-expired exact-SHA 1.3 installer artifacts for `b13_temporal_0001`.
- Produces: one uploaded report/log bundle per profile, distinguishing data-profile migrations from the actual 1.3-to-1.4 MSI upgrade.

- [ ] **Step 1: Add failing source-contract assertions for three profiles, fixture verification before every run, candidate payload verification, and optional 1.3 artifact digest/source checks.**
- [ ] **Step 2: Run the harness assertions and confirm failure.**
- [ ] **Step 3: Add the Windows matrix and evidence uploads while leaving the 1.0.3 job unchanged.**
- [ ] **Step 4: Run workflow syntax/source checks and the focused backend/PowerShell tests.**
- [ ] **Step 5: Commit and push PR #89 without force.**

### Task 4: Evidence reconciliation

**Files:**
- Modify: `docs/roadmap/REEFVISION_1_4_MIGRATION_RECONCILIATION.md`
- Modify: `docs/roadmap/REEFVISION_2_0_FEATURE_INVENTORY.json`
- Regenerate: `docs/roadmap/REEFVISION_2_0_FEATURE_INVENTORY.md`

**Interfaces:**
- Consumes: exact-head local results and completed GitHub Actions/artifact links.
- Produces: separate source, installed-Windows, synthetic-lineage, MSI-upgrade, and remaining representative-profile evidence for `rv14-lineage-upgrade`.

- [ ] **Step 1: Wait for exact-head CI and inspect every lineage job/report; fix recoverable failures with RED-to-GREEN regressions.**
- [ ] **Step 2: Update the inventory only for evidence actually produced; retain an exact representative-prior-user-profile blocker if no authorized profile exists.**
- [ ] **Step 3: Regenerate Markdown and run the inventory validator/tests.**
- [ ] **Step 4: Run final Python format/lint/type/backend, frontend format/type/unit/build, relevant Playwright, Alembic round-trip, and Windows harness gates on the final SHA.**
- [ ] **Step 5: Commit/push evidence and update PRs #89/#79 and issue #76 with final SHA, checks, installer hashes/artifacts, and remaining blocker.**
