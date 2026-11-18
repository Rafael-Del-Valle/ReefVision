# ReefVision 1.6 — fail closed on portable research-asset name collisions

**Status:** Isolated 1.6 offline migration-copy preservation improvement; **release HOLD**.

## Pre-work audit and safety rationale

Track D reviewed the existing read-only research-row/asset preservation verifier,
the real standalone and saved QC Workflow Builder implementation, prior version
scope and the isolated 1.6 draft PR. The verifier already checks source bytes,
file identity/hardlinks, symlinks/reparse points, concurrent mutation, directory
preservation, SQLite rows, migration schema contracts and researcher approval.
A remaining gap concerned **two distinct names on a case-sensitive filesystem
that can collapse during a future Windows or Unicode-normalizing copy**.
Matching SHA-256 values for both original and candidate trees on Linux does not
prove that a later copy to a different filesystem can preserve both assets.
The original case-sensitive pair must never be silently accepted as portable.

## Implementation

During each independent asset-tree inventory, compare the complete relative
file **and directory** paths using a conservative Unicode NFC + casefold key.
Reject a duplicate normalized key with `asset_portable_path_collision` and
`HOLD`, without including the researcher’s file names in the JSON report.
Both identical baseline/candidate trees and a candidate-only added collision
are rejected. Different relative paths that remain distinct after normalization
are still accepted, and additive folders remain permitted. The check makes no
claim to precisely emulate every Windows filesystem naming rule; an additional
manual Windows copy/installed-app acceptance is still mandatory.

The verifier reads research snapshots only, never rewrites asset names or data.
No new Alembic migration, API, scientific Workflow Builder node, downloaded
pretrained weight, automatic approval or release is introduced. Existing typed
saved and standalone executable QC workflows, immutable provenance, reliable
retry and human approval remain unchanged.

## Disposable regression matrix and limits

Six independent-database/asset-copy negative cases cover ASCII filename
case-only pairs, folder case-only pairs, and NFC-vs-NFD filename pairs, each
with both independently preserved trees and candidate-only additions.
Tests check controlled HOLD, redacted diagnostics, unchanged SQLite bytes,
unchanged source/candidate observations, and explicit researcher approval.
A positive case confirms that genuinely distinct project folders and additive
directories still permit `PASS_PRESERVATION_ONLY` (which never authorizes an
upgrade). Collision fixtures are skipped when the host filesystem inherently
aliases the two constructed names. Native Windows MSI, installation, upgrades,
rollback, real biological files and installed-GUI tests remain outstanding.

**Release HOLD:** Independently reconcile the conflicting 1.1/1.6 Alembic-0038
migration histories on copies, complete exact-head backend/frontend/typing/
lint/E2E/Windows CI, run representative biological and saved-workflow
acceptance, validate physical Windows MSI/CAB clean install/upgrade/rollback,
and obtain explicit researcher approval before release. Revised 1.7/1.8 scope
remains isolated and untouched.
