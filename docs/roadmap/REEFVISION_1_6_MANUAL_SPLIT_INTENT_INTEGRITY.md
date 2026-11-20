# ReefVision 1.6 — explicit manual cohort intent integrity

## Audit and overlap

The 1.0–1.5 dataset version producer already supports frozen manual split assignments, while 1.6 adds standalone and persisted executable Workflow Builder QC with immutable dataset-source provenance and researcher review gates. This change extends the existing producer and its existing `project_source → dataset_version_source → qc_review_queue` integration; it does not add a second split implementation, workflow node, database migration, or an automatic review decision.

## Gap and conservative fix

Previously, repeated manual assignments for the **same image and same split** silently collapsed into one dictionary entry. Conflicting repetitions were already rejected. Silent collapse conceals repeated researcher instructions and makes an explicit train/validation/test request harder to audit. The producer now rejects both contradictory and identical repeated image IDs during **preview and creation**, before any frozen dataset is written. Valid single assignments, study-specific eligible-status filtering, group-aware splitting, parent reuse and existing frozen datasets retain their established behavior.

A new end-to-end regression tests both repetition types, plus the existing unknown, excluded and other-project image protections. It then replays a persisted typed frozen QC graph and verifies the manifest SHA, dimensionless priority, pending human decisions, and absence of extra dataset versions.

## CI fixture correction and verification boundaries

[CI #44600503594](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44600503594) completed with **2,301 backend tests passing, 32 skipped and one failing** in the new manual-cohort regression. The failure was `IndexError` while accessing the second successful image import, before reaching the intended split assertions. The existing `import_one` fixture generates identical PNG bytes from equal dimensions; same-project duplicate-content imports are deduplicated even if filename/relative path differ. The regression now creates distinct source-pixel dimensions for its three biological image fixtures rather than changing production image-import behavior. It is not evidence of a dataset planner failure.

The preceding run also passed frontend/E2E and native-Windows research-preservation jobs, backend Ruff, strict mypy and migration preflights. **Exact new-head pytest/CI is required before calling these fixes validated.** A GitHub-hosted job is not a substitute for genuine Windows MSI/CAB clean installation, upgrade and rollback, installed-GUI behavior or representative marine biology acceptance.

**Release HOLD:** independent 1.1/1.6 Alembic-0038 reconciliation, full exact-head CI, human-reviewed biological workflow acceptance, installed Windows validation and explicit researcher authorization. The 1.7 and revised 1.8 branches are untouched. No auto-merge, release, deployment, external weights or user asset changes.


## 2026-11-19 — original frozen parent authentication before split reuse

The original dataset producer (1.0–1.5) supports `reuse_parent_assignments`; the existing 1.6 standalone and saved typed Workflow Builder QC already authenticates 0006/0007 immutable manifests. The child dataset preview/create path instead trusted a parent's `complete` status and copied mutable `DatasetVersionItem.split` values without validating the parent's manifest. An externally modified parent holdout could therefore contaminate a new study while the parent's own QC rejected that same corrupted evidence.

Child planning now calls the **same** read-only shared frozen-dataset manifest validator before inheriting split assignments. Forged parent geometry, class, provenance, biological grouping or split data fail closed; valid parent records and existing historical frozen versions are unchanged. No new migration, Workflow Builder node, automatic approval, pretrained weights or data rewriting.

A disposable database regression covers parent creation, valid preview, standalone and persisted executable `project_source → dataset_version_source → qc_review_queue`, an intentionally forged parent split, rejection of both child preview and creation without unintended new versions, explicit test-only restoration, successful child creation and a second saved graph execution. Both graph runs retain provenance, typed dimensionless priority and pending researcher approval.

The preceding [CI #44611181242](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44611181242) passed frontend and native-Windows preservation but failed backend Ruff formatting only. This change also applies the exact CI-provided one-line Ruff correction. New-head integrated backend pytest/lint/type, frontend/E2E, independent 1.1/1.6 migration reconciliation and genuine Windows MSI/CAB/installed-GUI clean-install, upgrade and rollback remain unverified release blockers.


## 2026-11-19 — authenticate referenced parent even without split inheritance

The earlier producer authenticated a complete parent only when `reuse_parent_assignments=true`. A child using the same `parent_version_id` with split reuse **disabled** could still cite a modified or forged complete parent as scientific lineage. The parent is not just a split-donor: its identifier in the frozen child manifest is a provenance claim.

The common parent lookup now authenticates any selected **complete** parent against the original read-only frozen manifest before either child preview or creation, regardless of the reuse flag. The split-reuse path retains its previous fail-closed behavior and avoids an extra validator call inside the child split planner. This does not alter the original dataset, rewrite ancestry, change historical schemas, or approve review decisions. Non-complete parent semantics are otherwise unchanged pending the separately reviewed migration/release gates.

The existing real-database parent-tampering regression now exercises both inherited and independently assigned child paths: valid previews, corruption refusal before writes, explicit test-only restoration, both valid children, standalone frozen QC and two persisted typed Workflow Builder executions with unchanged dimensionless priority, provenance and pending human review. Full exact-head repository CI and native installed-Windows acceptance remain required. The independent 1.1/1.6 Alembic-0038 collision is unresolved; **1.6 RELEASE HOLD**. Versions 1.7 and revised 1.8 are untouched.

## 2026-11-19 — authenticate entire frozen-study parent chain

**Audit:** Original 1.0–1.5 functionality already persists study parent IDs, manual/group-aware splits and immutable manifests. Version 1.6 already implements read-only 0006/0007 manifest QC, typed executable saved Workflow Builder graphs, provenance, retries and mandatory human review. The missing invariant is **transitive** ancestry: a valid direct parent can reference an older corrupted or incomplete source study.

**Change:** Before child preview or creation, walk the full parent chain, rejecting cycles, cross-project links, non-complete ancestors and changes to any ancestor's original frozen dataset manifest. Run the same integrity check with or without split inheritance. No migration, new Workflow Builder node, data repair or automatic researcher approval is introduced.

**Regression:** In disposable storage, create a three-generation reviewed study; deliberately change a grandparent's frozen split and verify preview/creation refuse the descendant without adding a version. Explicitly restore the split, test an incomplete grandparent refusal, restore its status, and create the valid descendant. Run the intermediate frozen study through standalone QC and a twice-executed saved typed `project_source → dataset_version_source → qc_review_queue` graph, checking SHA binding, dimensionless priority and pending researcher review. Existing frozen versions and user assets are unchanged.

**Verification limits:** Previous exact-head CI [#44639022806](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44639022806) passed frontend and native-Windows preservation but failed backend Ruff formatting on two lines, corrected in this increment. New backend pytest/mypy, full CI and physical Windows installed-MSI/CAB/GUI tests still require exact-head execution. Release HOLD remains for 1.1/1.6 Alembic-0038 reconciliation, representative biology and explicit owner approval; 1.7/revised 1.8 untouched.
