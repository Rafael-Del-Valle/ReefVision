# ReefVision 1.6 — start-command configuration atomicity

## Overlap audit and gap

Existing 1.0–1.5 scientific workflows, the 1.6 class and visibility services,
the saved executable `project_source -> qc_review_queue` Workflow Builder path,
and the Windows startup commands were inspected before this change. The updater
already rejected incompatible `--configure-repo` arguments before saving
configuration, but `start-reefvision` did not.

Previously `start-reefvision --configure-repo PATH --restart`, `--logs`,
`--diagnostics`, `--safe-mode` or `--no-wait` persisted a new repository
choice and returned success without running the named action. Combinations of
development modes could reject only **after** changing the persistent
`commands.json` file. This risks using the wrong local checkout in future
scientific builds and is not merely an incorrect help message.

## Contract

`scripts/start-reefvision.ps1` now rejects conflicting actions and mutually
exclusive development modes **before** calling `Set-ReefVisionRepoPath`.
Explicit pure `--configure-repo PATH`, `--help`, and the existing
`--configure-repo PATH --status` or single development-mode handoffs remain
available. Invalid combinations return a nonzero status and do not change any
saved configuration bytes. The startup command does not run a background job,
start a desktop, approve observations or modify project assets in these cases.

`scripts/test-reefvision-start-command-config.ps1` invokes actual child Windows
PowerShell processes with an isolated temporary `LOCALAPPDATA`. Eight invalid
combinations verify nonzero exit codes, the expected validation messages and
SHA-256 equality of the preexisting configuration. Additional checks verify
read-only help and successful standalone configuration preserving installed-app
identity. The native-Windows GitHub Actions preservation job runs this test.

## Scientific workflow and release boundaries

This change is a local **CLI safety preflight**, not a new scientific analysis.
It does not add a duplicate Workflow Builder node. Existing typed saved QC
graphs/runs, provenance, retries, pending human-approval gates and offline-first
model policy are unchanged.

This is **not** full release evidence. Complete exact-head CI, independently
reconciled 1.1/1.6 Alembic-0038 histories, representative biological data and
saved-workflow execution, real Windows MSI/CAB clean install and
upgrade/rollback, installed GUI testing and explicit researcher approval are
still required. Do not merge cross-version branches, automatically stamp user
databases or release on the strength of a synthetic preflight.
