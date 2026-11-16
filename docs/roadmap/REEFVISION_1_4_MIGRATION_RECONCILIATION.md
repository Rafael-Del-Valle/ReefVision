# ReefVision 1.4 migration reconciliation

## Integrated head

The validated 1.3 and draft 1.4 spatial histories converge at
`b14_integration_0001`:

```text
b13_temporal_0001 ─┐
                   ├─ b14_integration_0001
spatial_0039 ──────┘
```

The active spatial revisions are `spatial_0038` and `spatial_0039`. Their DDL
matches the draft-1.4 numeric migrations exactly. The original files are
retained unchanged under `apps/api/migrations/legacy_spatial/`; their Git blob
hashes before and after relocation are:

- numeric `0038`: `1d086cd5c0fe4614236f3f5e5ef53f7f65d2b0bc`
- numeric `0039`: `3d37109e78c9d8c397a569828244fc7ac3732302`

No applied migration body or database row is rewritten to pretend that a
different schema ran.

## Legacy numeric disambiguation

Numeric `0038` and `0039` were used independently by the scientific and
draft-spatial branches. Online upgrade inspects the schema inside the same
transaction before relabeling a proven draft-spatial head:

- `0038` requires the complete `spatial_source_assets` signature and no
  conflicting scientific or ReefPose signature;
- `0039` additionally requires the complete
  `spatial_calibration_reviews` signature;
- mixed, incomplete, unknown, or future signatures fail with a structured
  Alembic `CommandError` before a schema change;
- offline numeric upgrades remain rejected because schema evidence is not
  available.

## Verified source matrix

- Fresh database to `b14_integration_0001`.
- Validated 1.3 `b13_temporal_0001` to the integrated head while preserving a
  scientific record.
- Legacy draft-spatial numeric `0038` and `0039` to the integrated head while
  preserving spatial asset and calibration-review IDs and rows.
- Existing scientific, ReefPose, ecology, temporal, backup, unknown-head,
  ambiguous-schema, and failure-rollback lineage tests.
- Downgrade to the shared pre-branch `0037` and upgrade again.

Installed Windows upgrade, Project Exchange, and verified pre-upgrade backup
rollback remain open until an installer built from the final candidate SHA and
representative 1.3/legacy-draft-1.4 profiles are available.
