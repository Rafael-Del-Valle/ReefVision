# ReefVision 1.6 — class reassignment preview identity review

## Gap after 1.0–1.5 overlap audit

The existing class manager already supplies reassign, reassign-and-delete,
checksum-bound backend previews, explicit researcher confirmation and
independent executable/saved QC Workflow Builder operations. No duplicate
scientific workflow node is necessary for this UI review integrity fix.

The execution button previously relied on source/target **IDs**, audit
notes and local input epochs. A concurrent class metadata edit could
change the source/target class name, scientific or state identity, index,
active status or revision without invalidating the previously reviewed
preview. The backend independently checks immutable preview checksums;
the frontend must not offer stale researcher approval.

## Changes

Both reassign and reassign-and-delete now bind the preview to a complete
source and selected-target identity snapshot including revision time,
classification fields, display metadata and active/archive status.
Missing or changed target identities fail closed. Any identity drift
withdraws the Run action until a new server preview is explicitly
requested. The test matrix covers both actions with source and target
identity changes and verifies no execution call is sent from stale
approval. Also corrects the exact Prettier failure in the preceding
onboarding-focus regression.

This presentation/reviewer gate changes no scientific records, database
schema, models, datasets, provenance, or installed research assets.
Existing typed standalone/saved QC Workflow Builder execution, units,
human approval and reliable retry behavior remain unchanged.

## Acceptance and hold

Full exact-head frontend format/type/Vitest/Playwright/build and backend
scientific checks, representative biological saved-workflow execution,
1.1/1.6 Alembic-0038 reconciliation, real native-Windows MSI/CAB
installation/upgrade/rollback and installed-GUI usability plus
researcher sign-off remain mandatory before 1.6 release. Versions 1.7
and revised 1.8 are not touched.
