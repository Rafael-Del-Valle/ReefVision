# ReefVision 1.5 Provider Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:executing-plans to implement this plan task-by-task and
> superpowers:test-driven-development for every behavior change.

**Goal:** Complete the bounded ReefVision 1.5 early-provider foundation by
discovering inspect-only local provider manifests, exposing their declared
capabilities and availability without executing unknown code, isolating bad
manifests, and giving both the normal Providers workspace and saved Workflow
Builder graphs access to the same versioned record.

**Architecture:** ReefVision reads bounded JSON files only from
`<data_dir>/provider-manifests`. A strict version-1 declarative schema allows
identity, declared tasks/capabilities, availability, licensing, and notes; it
does not allow Python modules, entrypoints, commands, URLs to execute, package
installation, or model loading. Discovery never imports provider code. Each
file produces a stable inspection record even when it is malformed, oversized,
a symlink, or conflicts with a built-in provider. The existing Advanced
Provider service merges these inspection records into its catalog while
keeping them blocked from preflight and execution. Workflow Builder snapshots
the same record as provenance-only metadata and never turns it into an adapter.

**Tech Stack:** Python 3.12, Pydantic v2, FastAPI, React/TypeScript,
TanStack Query, Vitest, Playwright, existing Workflow Builder runtime.

**Specs:**

- `docs/superpowers/specs/2026-11-15-reefvision-through-2-0-program-design.md`
- `docs/roadmap/REEFVISION_2_0_FEATURE_INVENTORY.json`
- `docs/PHASE_8_ADVANCED_PROVIDERS_PLAN.md`

## Scope boundary

- This is feature `rv15-provider-foundations`, not the 2.0 plugin SDK.
- No plugin install, enable/disable lifecycle, executable entrypoint,
  permission grant, marketplace, hosted service, dynamic dependency install,
  or unknown-code loading is added.
- Built-in provider execution remains unchanged.
- Local manifest records are inspect-only and always fail closed at execution.
- SLEAP remains governed by the completed licensing audit and active support
  remains retired.
- No top-level tab is added. The user path remains project → Models & AI →
  Providers/Advanced providers.

## Contract conflicts resolved before implementation

- The historical `REEFVISION_1.5.0_REPORT.md` describes a partial provider-hub
  snapshot, not completion evidence for the inventory entry. The canonical
  inventory requires local manifest discovery, failure isolation, preserved
  unavailable records, normal navigation, Workflow Builder parity, and final
  Windows evidence.
- The 2.0 plugin entry owns executable third-party plugins. Therefore the 1.5
  manifest format deliberately omits execution hooks instead of creating an
  unstable early SDK.
- Missing 1.4 representative scientific inputs remain 1.4 blockers; the owner
  explicitly permits this independent 1.5 engineering slice without closing
  or reclassifying those blockers.

---

### Task 1: Strict inspect-only manifest discovery

**Files:**

- Create: `apps/api/reefvision/ml/local_provider_manifests.py`
- Create: `apps/api/reefvision/tests/test_local_provider_manifests_v15.py`

**Interfaces:**

- Produces: `LocalProviderManifestV1`
- Produces: `LocalProviderManifestRecord`
- Produces: `discover_local_provider_manifests(settings, built_in_ids=())`
- Reads: `<resolved_data_dir>/provider-manifests/*.json`

- [ ] Write RED tests for one valid version-1 manifest and deterministic
  ordering.
- [ ] Write RED tests proving malformed JSON, unknown fields, unsupported
  versions, invalid IDs, duplicate IDs, built-in ID collisions, oversized
  files, non-UTF-8 files, directories, and symlinks are isolated per file and
  retained as blocked inspection records.
- [ ] Write RED tests proving discovery never imports a declared module,
  executes a command, installs a package, follows a symlink, or reads outside
  the manifest directory.
- [ ] Implement the smallest bounded JSON reader and strict schema that make
  the tests pass.
- [ ] Run focused pytest, Ruff format/lint, mypy, and `git diff --check`.

### Task 2: Provider API integration and fail-closed preflight

**Files:**

- Modify: `apps/api/reefvision/schemas/advanced_providers.py`
- Modify: `apps/api/reefvision/services/advanced_providers.py`
- Modify: `apps/api/reefvision/api/routes/advanced_providers.py`
- Modify: `apps/api/reefvision/tests/test_advanced_providers_phase8.py`
- Create: `apps/api/reefvision/tests/test_local_provider_manifest_api_v15.py`

**Interfaces:**

- Extends manifest responses with source, schema version, declared
  capabilities, availability, source filename, discovery status, and bounded
  validation errors.
- Produces a refreshable manifest-list endpoint without changing built-in
  provider factories.

- [ ] Write RED API tests that valid, invalid, duplicate, and unavailable local
  records are visible without breaking built-in manifests.
- [ ] Write RED tests that local manifest IDs cannot reach built-in preflight or
  execution, including an ID that attempts to shadow a built-in provider.
- [ ] Merge discovery records into the response with explicit
  `execution_surface=blocked` and `execution_supported=false`.
- [ ] Preserve existing response fields and built-in behavior for backward
  compatibility.
- [ ] Run focused and adjacent provider suites plus static checks.

### Task 3: Normal user entry point

**Files:**

- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/App.test.tsx`
- Modify: `apps/web/src/features/advanced-providers/advancedProvidersApi.ts`
- Modify: `apps/web/src/features/advanced-providers/AdvancedProviderWorkspace.tsx`
- Modify: `apps/web/src/features/advanced-providers/AdvancedProviderWorkspace.test.tsx`
- Modify: relevant Playwright project-navigation acceptance test.

**Interfaces:**

- User path: Home → project → Models & AI → Providers.
- Local records expose manifest version, capabilities, availability reason,
  discovery errors, and the exact boundary that no provider code was loaded.

- [ ] Write RED component tests for valid/unavailable/invalid records and
  disabled preflight/run controls.
- [ ] Rename or clarify the existing navigation label to “Providers” without
  creating a new top-level activity.
- [ ] Render inspection metadata and actionable manifest-directory guidance.
- [ ] Add a first-use navigation test beginning at project selection.
- [ ] Run focused Vitest, TypeScript, Prettier, and production build.

### Task 4: Workflow Builder manifest snapshot parity

**Files:**

- Modify: `apps/api/reefvision/services/workflow_node_registry.py`
- Create: `apps/api/reefvision/services/workflow_provider_manifests_v15.py`
- Modify: Workflow runtime registration identified during implementation.
- Create: `apps/api/reefvision/tests/test_workflow_provider_manifests_v15.py`
- Modify: `apps/web/src/features/workflow-graphs/ScientificNodeControls.tsx`
- Modify: `apps/web/src/features/workflow-graphs/ScientificNodeControls.test.tsx`

**Interfaces:**

- Produces executable metadata-only node `provider_manifest_snapshot`.
- Consumes current project plus an explicit discovered record ID.
- Produces immutable workflow artifact type `provider_manifest_snapshot` with
  manifest digest, discovery status, availability, declared capabilities, and
  source filename; it cannot execute or install a provider.

- [ ] Write RED registry, save/replay, stale/missing manifest, invalid manifest,
  digest, and artifact-integrity tests.
- [ ] Implement the standalone/shared discovery call and workflow adapter.
- [ ] Add contextual controls and saved-graph round-trip tests.
- [ ] Prove built-in and local execution paths remain unchanged/blocked.
- [ ] Run focused backend/frontend workflow suites and static checks.

### Task 5: Inventory evidence and release acceptance

**Files:**

- Modify: `docs/roadmap/REEFVISION_2_0_FEATURE_INVENTORY.json`
- Regenerate: `docs/roadmap/REEFVISION_2_0_FEATURE_INVENTORY.md`
- Modify: `docs/REEFVISION_1.5.0_REPORT.md`
- Modify: relevant architecture/user documentation.

- [ ] Record source/browser evidence per acceptance check; keep installed
  Windows evidence in progress until an exact-SHA installer is validated.
- [ ] Audit every 1.5 inventory entry independently; do not close unrelated
  experimental-design, field-capture, reviewer-lab, catalog/runtime,
  comparison, or reproducibility entries.
- [ ] Run backend format/lint/type/full tests, frontend format/type/unit,
  relevant Playwright, migrations, production build, inventory validation, and
  exact-SHA Windows build/install/upgrade/rollback checks.
- [ ] Push only fast-forward updates, create/update the 1.5 draft PR and issue
  #76 evidence, and report exact blockers.
- [ ] Do not merge, tag, or publish.
