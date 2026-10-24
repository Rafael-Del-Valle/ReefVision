undefined

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
