# Contributing to ReefVision

ReefVision's original software is licensed under [AGPL-3.0-only](LICENSE). Contributions should be compatible with that license; please only submit code, documentation, and other materials you have the right to contribute. Do not incorporate third-party code or research data without the necessary permission and attribution. External dependencies keep their own licenses.

Read `AGENTS.md` and `docs/REEFVISION_PRODUCT_SPEC.md` before making changes.
Work on one milestone at a time and add tests with production code.

## Required checks

Run the complete pull-request validation gate from the repository root:

```powershell
./scripts/validate-pr.ps1
```

This runs backend linting, formatting, type checks and tests; Alembic upgrade and downgrade verification; frontend formatting, TypeScript, Vitest, Playwright and production builds; Python packaging; and Rust formatting, Clippy and tests.

Useful variants:

```powershell
# Skip browser tests while iterating locally.
./scripts/validate-pr.ps1 -SkipE2E

# Validate only the backend, frontend and package layers.
./scripts/validate-pr.ps1 -SkipDesktop

# Include the complete MSI installer and packaged backend build.
./scripts/validate-pr.ps1 -BuildDesktopInstaller
```

Run `./scripts/bootstrap.ps1` first when `.venv`, Node.js dependencies or provider dependencies have not been installed.
Backend-only commands and development setup are documented in [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).
