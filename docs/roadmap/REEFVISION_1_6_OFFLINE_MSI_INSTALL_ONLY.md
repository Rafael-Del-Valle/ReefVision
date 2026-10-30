# ReefVision 1.6 — offline pinned-MSI install-only contract

**Status:** development only; no release acceptance or user-data migration authorization.

## Scope and overlap audit

The existing 1.6 Windows command installer, `update-reefvision.ps1`, MSI
provenance verifier, pinned MSI digest, local-source-commit verification,
Windows installer rollback ownership, and command preflight already exist.
This change does **not** add a second installer, change model providers, or
duplicate the earlier class/QC/Workflow Builder implementations.

Previously, `update-reefvision --install-only` still evaluated the ordinary
dependency-setup decision and could invoke `bootstrap.ps1` before installing
a previously built and SHA-256-pinned MSI. This could unexpectedly require
network access or modify Python/Node development dependencies even though
the user requested only installation of a cached MSI.

## Contract

- `--install-only` never executes the dependency bootstrap, regardless of
  changed dependency signatures or missing `.venv`/`node_modules`.
- `--install-only --setup` is explicitly rejected rather than silently
  ignoring the user's contradictory request.
- Normal build/update paths still bootstrap when the dependency signature
  changes or development environments are missing, unless `--skip-setup`
  is explicitly selected. `--setup` still forces setup for build/update.
- `--dry-run --install-only` reports `setup_needed: false`.
- The provenance validator uses only Python's standard library. If the
  repository's .venv is absent, an **already installed** Python 3.11+ on PATH
  is permitted, running with -I -S -B (isolated, no site packages, no bytecode
  writes). No interpreter or packages are downloaded. If neither interpreter
  exists, installation fails closed **before** the running desktop is stopped.
  If the .venv interpreter is broken or older than 3.11, the resolver
  checks other already-installed Python executables on PATH in order, never
  launching Windows Store App Execution Aliases. An unusable candidate does
  not trigger package installation or desktop shutdown. This is not a
  Python-free installer; native MSI/GUI acceptance remains required.
- Installation still requires a pinned MSI, matching SHA-256, verified
  embedded source commit/version, safe local MSI/log paths, and successful
  Windows Installer execution. No automatic pretrained model downloads,
  repository updates, user-asset deletions, or scientific approval are added.

## Regression and acceptance

`scripts/test-reefvision-msi-update.ps1` now parses the **actual** updater
PowerShell AST, evaluates the setup decision in an isolated disposable
fixture, and checks five cases: install-only with and without skip-setup,
normal dependency mismatch, explicit skip-setup, and explicit setup.
It also checks for the conflicting-option guard. The Windows preflight
now exercises the actual Python resolver against a disposable repository
without .venv, verifies selection of an existing Python executable, checks
recovery from a corrupt local .venv executable, and confirms a missing
validator still fails before installation. The Windows build workflow
provisions a known Python 3.12 interpreter before this preflight (without
installing ReefVision dependencies), rather than relying on the runner's
ambient PATH. The existing `.github/workflows/build-desktop.yml` Windows
preflight invokes the test before building an MSI.

This check does not execute `msiexec`, perform an actual upgrade/rollback,
or verify an installed GUI. Native Windows test results, MSI upgrade and
rollback, installed GUI, cross-version 1.1/1.6 Alembic revision-0038
reconciliation, saved executable Workflow Builder regressions, and
representative biological-data validation remain release HOLD gates.

No cross-version branches were merged, and no user files were modified.

## Unattended downgrade preflight (2026-10-30)

A cached MSI can have valid provenance and a correct digest while still being
**older than the installed desktop**. The updater now calls
`Assert-ReefVisionMsiNoDowngrade` after verifying the MSI payload and before
stopping ReefVision. It compares numeric three-part MSI versions with three-
or four-part installed executable FileVersions, including the fourth build
component. A known newer installed build is never silently replaced by an
older pinned MSI. Unknown nonempty installed version strings fail closed,
rather than being treated as an empty/uninstalled machine. A missing installed
version (clean install) and an equal version (MSI-managed repair) remain
permitted. No version changes, migrations, model downloads or user-data
operations are performed by this preflight.

The Windows MSI preflight covers clean install, same-version repair,
three/four-part version comparisons, known downgrades, unknown installed
versions, invalid target numeric limits, and the **verification -> downgrade
guard -> desktop shutdown** ordering. These are source-level and helper tests,
not proof of a real Windows upgrade/rollback. Native installed-GUI acceptance,
representative biological data, cross-version Alembic 0038 reconciliation,
and complete exact-head CI remain release HOLD gates.

