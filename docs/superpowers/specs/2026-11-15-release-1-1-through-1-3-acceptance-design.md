# ReefVision 1.1-1.3 Release Acceptance Design

## Intent

Finish the remaining evidence-backed release work for draft PRs #71, #85, and #87 without merging, tagging, publishing, downloading unapproved checkpoints, or committing research media or credentials. Preserve the local-first scientific contracts and use published 1.0.3 (`e94dad6a3bece7b776bf45776bc5d06cfbc2c0dc`) as the upgrade baseline.

## Goals

- Reconcile the 1.1 branch with current `main` while preserving every published migration identifier.
- Preserve a reviewed aggregate as historical evidence when its source image group key later changes, round-trip the stale result through Project Exchange, and recalculate from the imported project's current grouping.
- Reject archives whose historical aggregate evidence, calculations, hashes, relationships, or workflow provenance are internally inconsistent.
- Align clearly drifted release metadata and record any licensing decision that cannot be derived from the repository history.
- Run the available source, migration, installer, installed-app, hardware, upgrade, rollback, and representative-data checks on the exact final SHAs. Mark unavailable environmental or scientific inputs as blocked with a reproducible next step.
- Keep 1.2 and 1.3 stacked on their current bases. Forward-port only fixes that reproduce on those branches.

## Non-goals and anti-goals

- Do not rewrite or renumber applied Alembic migrations.
- Do not make a stale historical aggregate appear current after import.
- Do not weaken archive integrity checks merely to accept stale evidence.
- Do not merge the release branches, create tags/releases, install on the user's normal Windows profile, or add private checkpoints, credentials, or field media to Git.
- Do not claim representative scientific acceptance from synthetic fixtures.

## Constraints

- Original images and immutable dataset evidence remain unchanged.
- Predictions remain unverified until explicit acceptance.
- The 1.1 merge must retain both branch histories and use a new reconciliation migration only if the merged graph truly has multiple Alembic heads; existing migration files are immutable.
- Installer provenance must name the exact clean source commit and the branch's actual product version.
- Historical aggregate evidence and current project state are distinct concepts. Import validates the former; the result-validation endpoint compares it with the latter.

## Approaches considered

1. **Surgical branch-local repair and evidence-driven forward ports (selected).** Merge current `main` into 1.1, repair and test the exchange contract there, then reproduce on 1.2/1.3 and forward-port only applicable changes. This preserves the stacked PR topology and minimizes migration risk.
2. **Wholesale forward merge of 1.1 into 1.2 and 1.3.** This provides one history but risks blending unrelated 1.1 changes into already validated later candidates and makes failures harder to attribute.
3. **Acceptance-only updates for 1.2/1.3.** This is appropriate only if their current implementations already pass the new regression; otherwise it would knowingly leave the defect in later releases.

## Design

### Historical aggregate validation

The Project Exchange validator will continue to verify the archive row checksum, definition snapshot, workflow run/node relationship, deterministic unique inventories, source ownership, class references, observation inventory, proposal exclusions, group totals, class totals, mean, evidence hash, provenance, and observation timestamp consistency.

Aggregate groups will be reconstructed from the saved image snapshot's group keys, not the imported project's current group keys. A saved image snapshot must still identify an exported project image with the same immutable image checksum. Current rows remain the authority for record ownership and relational existence. A current group-key divergence is allowed as historical staleness rather than treated as corruption. Other divergence is allowed only where the archive contains verifiable historical evidence under the existing model; otherwise import fails closed.

Identifier remapping will change declared relational IDs and rebuild hashes, while researcher-authored group-key strings remain literal. After import, validation compares the remapped saved snapshot with the imported current images and reports the same stale condition. Recalculation uses current image rows, so its grouping follows the new group keys and produces a new result without mutating the historical one.

### Branch and migration handling

PR #71 receives the `main` merge before release fixes are committed. Conflicts are resolved by retaining published 1.0.3 behavior and the additive 1.1 scientific implementation. Existing revision IDs remain unchanged. Fresh, 1.0.3 upgrade, downgrade/upgrade round-trip, verified-backup restore, and older-build read-only rejection paths determine whether an additive merge revision is needed.

PRs #85 and #87 retain their current base relationships. The regression is run first on each existing head; code is forward-ported only when it fails. Product versions, package metadata, Tauri metadata, MSI metadata, and generated provenance must agree on 1.1.0, 1.2.0, and 1.3.0 respectively.

### Licensing

Repository history and current `main` determine the mechanically correct license files and metadata. Clear mismatches are aligned consistently across Python, Rust, JavaScript, installer, and documentation metadata. If history does not establish whether the project owner intended MIT or AGPL for 1.1, the PR records that as an unresolved release decision instead of silently relicensing source.

### Acceptance evidence

Automated checks run from clean committed trees and include focused red/green regressions, backend, Ruff, mypy, frontend formatting/type/unit/build, relevant Playwright, migration lineage/round trips, PowerShell harnesses, and installer provenance checks. Installed Windows, RTX 3090, Copernicus, surveyed-reference, coral-pair, and animal-footage checks run only when their required local inputs are present. Missing inputs are reported separately from engineering failures, and other checks continue.

PR updates and issue #76 receive exact final SHAs, commands and counts, workflow/installer links, upgrade and rollback paths, scientific results, exclusions, and exact blockers. Synthetic results are labeled engineering evidence.

## Expected files

- `apps/api/reefvision/tests/test_computed_aggregate_project_exchange.py`: stale round-trip and tamper regressions.
- `apps/api/reefvision/services/project_exchange_computed.py`: historical aggregate validation/remapping boundary.
- Release metadata and license files identified by the `main` reconciliation.
- Release/acceptance documentation only where needed to record exact evidence or unresolved decisions.

No database schema change is expected for the Project Exchange repair.
