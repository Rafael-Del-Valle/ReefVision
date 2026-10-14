# ReefVision 1.0.2 annotation usability implementation plan

**Goal:** Deliver ReefVision 1.0.2 with reliable project entry, paginated keyboard navigation, safer viewer controls, undoable annotation clipboard operations, shortcut discovery, and exact-head release evidence.

**Architecture:** Extend the existing gallery and box/mask/raster annotation workspaces. Keep source-image pixels as the canonical geometry, use image IDs as asynchronous query boundaries, keep navigation and clipboard transforms in small pure modules, and reuse existing history and persistence services.

**Tech stack:** React 19, TypeScript, TanStack Query, Vitest/Testing Library, Playwright, FastAPI/Pydantic/SQLAlchemy, pytest/Ruff/mypy, Tauri 2, PyInstaller, WiX/MSI.

**Spec:** `docs/superpowers/specs/2026-10-11-reefvision-1.0.2-annotation-usability-design.md` and the maintainer's 1.0.2 master prompt.

## Global constraints

- Start from exact commit `70da46deceebe56ecc1c58240e950c08ae581360` on `feat/reefvision-1.0.2-annotation-usability`.
- Keep PR #44 draft and unchanged. Do not merge, tag, publish, replace public assets, or install on the maintainer's computer.
- Preserve originals, source-image coordinates, class mappings, provenance, verified-only learning, held-out evaluation isolation, immutable datasets, SAM acceptance boundaries, and existing local-model policy.
- Do not add a parallel editor, new UI framework, or unnecessary backend/storage abstraction. Add no migration unless implementation proves persisted schema is necessary.
- Use pagination for gallery navigation. Wrapping defaults off and persists through the existing browser preference mechanism.
- Drive every production behavior through a focused RED/GREEN test and record deviations as rulings in the execution ledger.

## Review focus

- Rapid project/image changes must never pair one image with another image's annotations or allow a late request to replace current state.
- Clipboard operations must never preserve scientific verification, reviewer audit, accepted-prediction identity, or evaluation-only provenance.
- Pan, zoom, fit, actual-size, reset, polygon hit-testing, raster painting, and SAM prompts must preserve source-image coordinates at edges and high zoom.
- Shortcut handling must be inactive in editable controls, dialogs, menus, and conflicting tool interactions while preserving Shift+1, Shift+2, class number keys, and SAM box prompts.
- Boundary navigation must handle zero, one, deleted, missing, corrupt, paginated, collapsed, and large-gallery cases without blank valid-image states.
- Exact-head evidence must distinguish automated validation from physical desktop interactions that were not performed.

## Task 1: Baseline, version contract, and release skeleton

**Files:** version sources in `pyproject.toml`, `package.json`, `apps/web/package*.json`, Tauri/Python sources and build scripts; version tests; `CHANGELOG.md`; new 1.0.2 release evidence files.

- [ ] Install isolated frontend dependencies and run representative baseline frontend/backend/version checks.
- [ ] Add a failing release-version test expecting 1.0.2 from every live source and package path.
- [ ] Update live version sources and current build resource paths without editing historical release evidence.
- [ ] Add 1.0.2 release-note and acceptance-report skeletons that name the exact base and current evidence state.
- [ ] Run the focused version checks and commit the checkpoint.

## Task 2: Deterministic project entry and paginated gallery navigation

**Files:** `apps/web/src/features/gallery/Gallery.tsx`, new gallery selection/navigation modules, `apps/web/src/App.tsx`, API types if needed, and focused Vitest tests.

- [ ] Add failing tests for first image, stored recent image/page, deleted recent image fallback, project switching, zero/one images, boundaries, wrapping, rapid transitions, and large page counts.
- [ ] Implement project-scoped recent-image storage with defensive parsing and default-off wrap preference.
- [ ] Implement pure page-aware previous/next/home/end resolution and a single active-image transition path.
- [ ] Synchronize the main preview and filmstrip, scroll the active thumbnail into view, and expose loading/empty/error/retry and broken-asset retry states.
- [ ] Guard keyboard navigation by viewer focus and editable/dialog/menu context.
- [ ] Run focused tests plus the full frontend unit suite and commit the checkpoint.

## Task 3: Editor image state and asynchronous reliability

**Files:** `EnhancedAnnotationEditor.tsx`, box/mask/raster workspaces, related hooks and tests.

- [ ] Add failing tests that simulate out-of-order image/session responses and image deletion while selected.
- [ ] Make the active image an explicit controlled identity between gallery shell and workspace and cancel/ignore stale query results.
- [ ] Clear stale selection and transient operations on image change while retaining pending-save safeguards.
- [ ] Add failure recovery that cannot display annotations under a mismatched image.
- [ ] Run focused tests plus full frontend tests and commit the checkpoint.

## Task 4: Pan, zoom, fit, actual size, and cancellation

**Files:** annotation editor view/geometry helpers, box/mask/raster viewer handlers and focused tests.

- [ ] Add failing transform tests for cursor-centered zoom, actual size, reset, arbitrary pan/zoom round trips, and edge coordinates.
- [ ] Add failing interaction tests for Alt+left pan, middle pan, pointer cancellation, window blur, mouse-up outside, and tool noninterference.
- [ ] Implement temporary pan and viewport-only Fit, Actual Size, Reset, double-click fit where consistent, and safe zoom clamping.
- [ ] Route polygon, raster, and SAM prompt coordinates through unchanged source-space transforms.
- [ ] Run focused interaction/geometry tests plus full frontend tests and commit the checkpoint.

## Task 5: Safe annotation clipboard and reversible editing

**Files:** shared annotation clipboard/geometry module, box/mask/raster workspace commands, history code, and tests.

- [ ] Add failing tests for copy/paste, duplicate, fresh IDs, repeated bounded offsets, no-space rejection, class/type preservation, dimension mismatch, and verification/audit/evaluation stripping.
- [ ] Add failing workspace tests for one undo transaction per paste/duplicate, redo, reversible delete, Escape cancellation, polygon copies, and compatible raster copies.
- [ ] Implement an internal annotation clipboard and workspace adapters using existing history/persistence paths.
- [ ] Ensure paste never rescales scientific geometry and never promotes predictions or changes review state.
- [ ] Verify reload persistence through the existing save APIs and commit the checkpoint.

## Task 6: Shortcut reference, tool feedback, and responsiveness evidence

**Files:** editor/gallery controls and styles, shortcut registry/dialog, preference UI, performance scenarios/report, tests.

- [ ] Add failing tests for the shortcut registry, conflicts, accessible dialog, tooltips, active-tool feedback, and protected existing bindings.
- [ ] Build one shared shortcut reference and expose relevant shortcuts in existing buttons/menus.
- [ ] Add the wrap toggle and persistence UI; document internal clipboard and OS/browser limitations.
- [ ] Add reproducible representative scenarios for image switching, zoom/pan, polygon interaction, and raster editing; collect real final-commit measurements only.
- [ ] Run accessibility/focus tests, focused performance scenarios, full frontend tests, and commit the checkpoint.

## Task 7: Integration, documentation, and scientific regression

**Files:** Playwright workflows, release notes/evidence, user documentation, and scientific regression tests.

- [ ] Add end-to-end coverage for project entry, recent restoration, navigation/focus, corrupt images, pan/zoom, clipboard/history, persistence, and protected SAM shortcuts.
- [ ] Run relevant annotation API, import/export, polygon/raster persistence, provenance, verified learning, held-out evaluation, SAM proposal/refinement, and migration tests.
- [ ] Complete the 1.0.1 versus 1.0.2 comparison, upgrade notes, known limitations, safeguards, and evidence.
- [ ] Create/update the 1.0.2 tracking issue and draft PR; attach the PR to this task. Do not change PR #44.
- [ ] Commit and push the checkpoint.

## Task 8: Exact-head full validation and Windows package

**Files:** validation evidence and generated release-candidate artifacts outside Git where appropriate.

- [ ] Run frontend Prettier check, TypeScript, complete Vitest, production build, and Playwright suite.
- [ ] Run backend format/Ruff, mypy, complete pytest, migrations up/down/up, annotation/import-export/scientific suites, and version consistency.
- [ ] Build the backend/frontend/Tauri MSI from final HEAD, validate MSI/CAB structure and checksums, and record the exact commit.
- [ ] Perform feasible noninstalling desktop/package smoke tests. Record clean-install, persistence-restart, uninstall, and hardware-only interactions as outstanding unless actually executed in an isolated test environment.
- [ ] Inspect changed/untracked files for secrets, caches, checkpoints, and temporary artifacts; confirm branch cleanliness and CI corresponds to final HEAD.
- [ ] Commit/push final evidence and update the tracking issue and draft PR.

## Task 9: Whole-branch review and release recommendation

- [ ] Generate a whole-branch review package from the exact base to final HEAD and obtain one fresh-context review as required by the execution workflow.
- [ ] Re-grade findings by user impact, fix Critical/Important findings with RED/GREEN tests in one pass, and record deferred minors/rulings.
- [ ] Rerun affected and full suites after review fixes, rebuild exact-head artifacts if code changed, and update remote evidence.
- [ ] Use the development-branch finishing workflow without merging or publishing.
- [ ] Report features, exact test counts/skips/failures, installer hash/commit/evidence, scientific safeguards, blockers, rulings, deferred minors, and READY FOR MAINTAINER REVIEW or HOLD.

## Progress ledger

- Preflight: exact base verified; branch isolated in `reefvision-1.0.2-annotation-usability`; PR #44 confirmed draft and unmerged.
- Ruling: the historical initial-release no-segmentation non-goal is superseded by existing 1.0.1 functionality; preserve and test the shipped segmentation workspaces. Cost if wrong: the 1.0.2 brief's polygon/raster acceptance criteria could not be met.
