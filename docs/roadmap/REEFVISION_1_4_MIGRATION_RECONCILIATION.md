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

Exact-head installed Windows engineering acceptance has exercised deterministic
validated-1.3, legacy `0038`, and legacy `0039` profiles through upgrade,
Project Exchange, and verified pre-upgrade backup restore. Representative
prior-user acceptance remains open until authorized real validated-1.3 and
legacy draft-1.4 profiles, each with a verified backup, are available.

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
tests cover the generated profiles. The Windows run for lineage commit
`36c80224a` passed the three generated profiles and the published 1.0.3 upgrade.
The 1.3 installer rejected the upgraded schema and preserved the database
digest. Repeat the matrix on the integrated candidate. Real prior-user profiles
with verified backups still require owner-authorized copies.
[Windows lineage acceptance](https://github.com/Rafael-Del-Valle/ReefVision/actions/runs/44072770396)
## Packaged backup recovery on a disposable copy

The accepted 1.3.0 installer at `f44053a90` contains a frozen sidecar with
SHA-256 `05ca83d6cb1b2d931ecf775235f1e70a8bea859ba6182026fe8c6ac21ae74746`.
A fixture created through that sidecar included an original image, a reviewed
box and mask, two stable class IDs and indices, a 0.25 mm/px calibration,
an image-linked observation of 68 °F and a registered local scratch checkpoint.
Migration on the archived 1.4 build `78a02c20c` preserved the original
records. Project Exchange 1.1 remapped their IDs and preserved the media,
checkpoint and model-to-class relationship. The 1.3 executable declined to
open the upgraded database and left its bytes intact.

Both original Windows packages could verify the 1.3 backup. Their Restore
action returned HTTP 500 while locating bundled Alembic revisions. A
production-script frozen Windows sidecar at `63fd94bfc` used the shared
desktop Alembic resource resolver. Restore returned HTTP 200 and its job
succeeded. The recovered database and all five backup inventory files
matched their checksums. The exact 1.3 executable reopened a separate copy
of that recovery and accepted a new write. The upgraded database SHA-256
stayed `34b000428fff3429f9d736997eca7f662b9d04d29ababf383898fd06d1c51b92`
after the old reader exited with code 1. Two checksum-valid fixture backups
with an unknown schema or future application version both returned HTTP 409
and created no recovery directory.

Use a verified backup made before the upgrade and a separate recovery
directory. Keep the original upgraded profile and backup intact. The
completion marker authenticates the manifest. Verify each inventory entry's
size and SHA-256, including the database snapshot and original media. Open
the recovered copy with the matching previous executable and compare record
IDs, units, class indices, review history and file hashes before writing.
Representative historical profiles remain an owner acceptance input.
