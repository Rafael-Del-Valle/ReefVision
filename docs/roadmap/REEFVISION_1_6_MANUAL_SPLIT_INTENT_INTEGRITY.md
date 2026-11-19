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
