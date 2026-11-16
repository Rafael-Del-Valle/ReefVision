# ReefVision 1.4 migration reconciliation

## Integrated head

The validated 1.3 and draft 1.4 spatial histories converge at
`b14_integration_0001`; the first additive integrated 1.4 schema revision is
`b14_spatial_0040`:

```text
b13_temporal_0001 ─┐
                   ├─ b14_integration_0001 ─ b14_spatial_0040
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

`b14_spatial_0040` adds append-only spatial asset metadata revisions for source
units, coordinate frames, optional affine transforms, calibration evidence,
local review attribution, revision ancestry, and content integrity hashes.

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

- Fresh database to `b14_spatial_0040`.
- Validated 1.3 `b13_temporal_0001` to the integrated head while preserving a
  scientific record.
- Legacy draft-spatial numeric `0038` and `0039` to the current head while
  preserving spatial asset and calibration-review IDs and rows.
- Existing scientific, ReefPose, ecology, temporal, backup, unknown-head,
  ambiguous-schema, and failure-rollback lineage tests.
- Downgrade to the shared pre-branch `0037` and upgrade again.

Installed Windows upgrade, Project Exchange, and verified pre-upgrade backup
rollback remain open until an installer built from the final candidate SHA and
representative 1.3/legacy-draft-1.4 profiles are available.

## Metadata ancestry integrity

Metadata revision reads now validate immediate ancestry in addition to each
revision's canonical content digest. Revision 1 must have no predecessor;
subsequent revisions must point to the immediately preceding revision of the
same project, source asset, and original SHA-256. Both individual reads and
paginated reads reject broken history. Regression tests tamper with predecessor
bindings and recompute otherwise valid per-row digests, verifying fail-closed
behavior. The original mesh and append-only API remain unchanged.

The digest is an integrity check, **not a cryptographic signature**. Coordinated
rewriting of a complete history by a database administrator is outside this
check's threat model; do not equate this with authenticated human review or
scientifically verified calibration.

## Generating disposable profiles for installed acceptance

From the repository root with the ReefVision development environment installed,
run `python scripts/create_windows_lineage_fixtures.py <new-output-directory>`.
This creates profiles at `b13_temporal_0001` and at both legacy spatial heads
(`0038` and `0039`). The manifest identifies each database, its project ID,
and the SHA-256 of its integrity-checked pre-upgrade SQLite backup. Copy the
whole selected profile, including its project files, into the isolated data
directory used for the candidate's installed acceptance run. Keep the
generated pre-upgrade database backup and the original project files outside
the installation under test. The generator refuses to overwrite a directory.

On Windows, launch the exact candidate in a disposable acceptance environment
and check the migration status, the seeded project and records, and the Project
Exchange export. Shut down the application before restoring the database backup
and the original project files into a separate disposable data directory.
Check the restored schema revision and project evidence. Source-level upgrade
tests cover the generated profiles. Installed launch, exchange, and rollback
still require execution on Windows. These synthetic profiles cover historical
schemas and do not stand in for an acceptance run on representative projects.
