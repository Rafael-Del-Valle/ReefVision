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
- Installation still requires a pinned MSI, matching SHA-256, verified
  embedded source commit/version, safe local MSI/log paths, and successful
  Windows Installer execution. No automatic pretrained model downloads,
  repository updates, user-asset deletions, or scientific approval are added.

## Regression and acceptance

`scripts/test-reefvision-msi-update.ps1` now parses the **actual** updater
PowerShell AST, evaluates the setup decision in an isolated disposable
fixture, and checks five cases: install-only with and without skip-setup,
normal dependency mismatch, explicit skip-setup, and explicit setup.
It also checks for the conflicting-option guard. The existing
`.github/workflows/build-desktop.yml` Windows preflight already invokes
this test before building an MSI.

This check does not execute `msiexec`, perform an actual upgrade/rollback,
or verify an installed GUI. Native Windows test results, MSI upgrade and
rollback, installed GUI, cross-version 1.1/1.6 Alembic revision-0038
reconciliation, saved executable Workflow Builder regressions, and
representative biological-data validation remain release HOLD gates.

No cross-version branches were merged, and no user files were modified.
