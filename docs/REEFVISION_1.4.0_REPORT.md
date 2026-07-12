# ReefVision 1.4.0 Report

## Status

Partial progress only. ReefVision `1.4.0` should not yet be claimed complete.

This report covers the implemented and verified Milestone 8 slices currently in the repository:

- version alignment to `1.4.0`;
- system version and compatibility visibility;
- structured rotating logs;
- managed backup creation and verification;
- managed restore into a new recovery location;
- redacted diagnostic bundle export;
- first-run onboarding and recovery UI foundations.

Not yet verified complete:

- packaged desktop backup or restore workflows;
- installer upgrade and uninstall preservation checks;
- clean-machine verification;
- full NSIS release checksum and release-note packaging;
- the remaining Milestone 8 documentation sweep;
- any claim of full release readiness.

## Version Sources

The main application version sources were updated to `1.4.0`:

- `apps/api/reefvision/__init__.py`
- `pyproject.toml`
- `package.json`
- `apps/web/package.json`
- `apps/web/package-lock.json`
- `apps/web/src-tauri/tauri.conf.json`
- `apps/web/src-tauri/Cargo.toml`
- `apps/web/src-tauri/Cargo.lock`

An automated backend test now fails if the authoritative version sources drift.

## Implemented Milestone 8 Behavior

### Backups

- Managed backups are created as background jobs.
- Backups use deterministic manifest ordering, SHA-256 checksums, and a completion marker.
- Cancelled or failed backups do not appear complete.
- Backup verification checks manifest readability, file membership, checksums, and completion state.

### Restore

- Restore is only allowed from a valid verified backup.
- Restore currently targets a new managed directory under `recoveries/`.
- Active data is not overwritten.
- Restored files are verified against the backup manifest before finalization.
- A restore receipt is written into the restored recovery copy.

### Diagnostics

- Diagnostic export is a background job.
- Bundles include ReefVision version, backup-format version, dependency versions, disk summary, recent failed jobs, and bounded recent logs.
- Data-directory and home-directory paths are redacted in strict mode.
- Media files are not included by default.

### Frontend

- `System status` now shows version, schema, compatibility, data paths, logs, backup controls, restore controls, and diagnostics export.
- A first-run onboarding modal is available and can be reopened from the top bar or `System status`.
- The onboarding copy explicitly notes that YOLO import is still not exposed in this build.

## Migrations

- No new Alembic migration was added in this restore or diagnostics slice.
- The current schema head remains `0009`.
- The existing Milestone 8 migration is `0009_backup_records_and_app_scoped_jobs.py`.

## Files Added or Changed in This Slice

Backend:

- `apps/api/reefvision/storage/diagnostics.py`
- `apps/api/reefvision/jobs/diagnostics.py`
- `apps/api/reefvision/jobs/restores.py`
- `apps/api/reefvision/services/backups.py`
- `apps/api/reefvision/services/system.py`
- `apps/api/reefvision/jobs/worker.py`
- `apps/api/reefvision/services/jobs.py`
- `apps/api/reefvision/api/routes/backups.py`
- `apps/api/reefvision/api/routes/system.py`
- `apps/api/reefvision/schemas/backups.py`
- `apps/api/reefvision/schemas/system.py`
- `apps/api/reefvision/domain/enums.py`
- `apps/api/reefvision/tests/test_restore_and_diagnostics.py`

Frontend:

- `apps/web/src/api/client.ts`
- `apps/web/src/features/system/SystemPanel.tsx`
- `apps/web/src/features/onboarding/OnboardingModal.tsx`
- `apps/web/src/App.tsx`
- `apps/web/src/App.test.tsx`
- `apps/web/src/styles/app.css`

Docs:

- `README.md`
- `CHANGELOG.md`
- `docs/REEFVISION_1.4.0_REPORT.md`

## Verification Run

Backend:

```powershell
.\.venv\Scripts\python.exe -m pytest apps/api/reefvision/tests/test_version_consistency.py apps/api/reefvision/tests/test_system.py -q
```

Passed earlier in this milestone slice: `6 passed, 1 warning`.

```powershell
.\.venv\Scripts\python.exe -m pytest apps/api/reefvision/tests/test_backups.py apps/api/reefvision/tests/test_system.py apps/api/reefvision/tests/test_restore_and_diagnostics.py -q
```

Passed: `12 passed, 1 warning`.

```powershell
.\.venv\Scripts\python.exe -m ruff check apps/api/reefvision/storage/diagnostics.py apps/api/reefvision/jobs/diagnostics.py apps/api/reefvision/jobs/restores.py apps/api/reefvision/services/backups.py apps/api/reefvision/services/system.py apps/api/reefvision/api/routes/backups.py apps/api/reefvision/api/routes/system.py apps/api/reefvision/schemas/backups.py apps/api/reefvision/schemas/system.py apps/api/reefvision/jobs/worker.py apps/api/reefvision/services/jobs.py apps/api/reefvision/domain/enums.py
```

Passed.

```powershell
.\.venv\Scripts\python.exe -m ruff format --check apps/api/reefvision/storage/diagnostics.py apps/api/reefvision/jobs/diagnostics.py apps/api/reefvision/jobs/restores.py apps/api/reefvision/services/backups.py apps/api/reefvision/services/system.py apps/api/reefvision/api/routes/backups.py apps/api/reefvision/api/routes/system.py apps/api/reefvision/schemas/backups.py apps/api/reefvision/schemas/system.py apps/api/reefvision/jobs/worker.py apps/api/reefvision/services/jobs.py apps/api/reefvision/domain/enums.py apps/api/reefvision/tests/test_restore_and_diagnostics.py
```

Passed.

```powershell
.\.venv\Scripts\python.exe -m mypy apps/api/reefvision
```

Passed: `Success: no issues found in 117 source files`.

Frontend:

```powershell
npm --prefix apps/web run test -- src/App.test.tsx src/runtime.test.ts
```

Passed: `12 passed`.

```powershell
npm --prefix apps/web run typecheck
```

Passed.

```powershell
npm --prefix apps/web run format:check
```

Passed.

```powershell
npm --prefix apps/web run build
```

Passed.

## Known Limitations

- Restore currently creates a verified recovery copy but does not activate it as the live ReefVision data directory.
- Overwrite restore and rollback-protected replacement restore are not implemented.
- Diagnostic bundles are backend-focused and do not yet collect packaged desktop metadata from the installed shell.
- The current onboarding explains unavailable YOLO import honestly instead of surfacing a nonexistent workflow.
- This report does not claim full desktop, installer, upgrade, uninstall, or clean-machine verification.

## Specification Deviations Still Open

- YOLO import is still absent from the user-facing workflow, despite being present in the product specification.
- Full Milestone 8 release hardening and distribution verification remains incomplete.
- The final `1.4.0` installer path and SHA-256 checksum have not been produced in this report.
