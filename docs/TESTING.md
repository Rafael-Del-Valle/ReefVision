# Testing

## Backend

- pytest covers API, service, storage, job, duplicate, pagination, and image-format behavior.
- Every normal test receives an isolated temporary data directory and SQLite database.
- A dedicated test enables the actual worker loop and verifies asynchronous thumbnail completion.
- JPEG, PNG, TIFF, and WebP imports are covered.
- Batch import, corrupt files, unsupported files, exact duplicates, missing source files, retries, and interrupted-job recovery are covered.
- Deprecation and resource warnings are treated as errors.
- Phase 5 real pose interoperability tests use the existing `integration` marker
  and opt in with `--pose-interop-integration`. Install `.[interoperability]` first.
  They generate synthetic temporary media and execute SLEAP-IO 0.9.2 without
  network access. See [the format contracts and test command](POSE_INTEROPERABILITY.md).

## Frontend

- Vitest and React Testing Library cover project navigation, gallery empty states, image metadata editing, and multipart import reports.
- Playwright runs a built-application browser workflow covering project selection, image import, gallery refresh, group-key editing, and status changes.
- The Playwright test injects the production Vite bundle directly, so it does not depend on a locally reachable web server during test execution.

## Migration verification

Every schema milestone proves that a blank database upgrades to `head`, downgrades to the previous milestone revision, upgrades again, and can downgrade to `base`.

## User-data isolation

Tests never use the default `.reefvision` directory. Database files, imported originals, staging files, and thumbnails are created only beneath pytest temporary directories.
