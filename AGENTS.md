# AGENTS.md — ReefVision

## Mission

Build ReefVision as a reliable, local-first scientific image-annotation and computer-vision application. The first release focuses on coral-polyp bounding-box annotation, YOLO interoperability, model-assisted review, immutable dataset versions, and leakage-aware data splitting.

Read `docs/REEFVISION_PRODUCT_SPEC.md` before making changes.

## Non-negotiable data rules

1. Original source images are never modified.
2. Canonical bounding-box coordinates are stored in source-image pixels.
3. Model predictions are never treated as verified annotations until explicitly accepted.
4. Dataset versions are immutable snapshots.
5. Related images sharing a non-null group key may not cross dataset splits.
6. Class indices may not silently change after use.
7. Multi-record annotation saves are transactional.
8. Schema changes require a new Alembic migration.
9. Applied migrations are never edited.
10. User data must not be written to test directories, and tests must not write to the user's data directory.

## Scope rules

- Implement one milestone at a time.
- Do not pursue full Roboflow parity.
- Do not add cloud accounts, authentication, hosted storage, or distributed infrastructure in version 0.1.
- Do not add segmentation or video tracking before the object-detection workflow is stable.
- Prefer simple, testable local components.
- Do not create unused abstraction layers.

## Required workflow

Before editing:

1. Inspect the repository.
2. Read the product specification and relevant architecture documents.
3. State the milestone being implemented.
4. Provide a concise file-level plan.
5. Identify any conflict between the request and existing contracts.

During implementation:

1. Keep changes limited to the milestone.
2. Add tests with the implementation.
3. Preserve backward compatibility unless the milestone explicitly changes a contract.
4. Use typed request and response models.
5. Return structured domain errors rather than unhandled exceptions.
6. Keep filesystem operations inside the storage layer.
7. Keep framework-specific model code inside an ML adapter.
8. Use UTC timestamps.
9. Use UUIDs in public APIs.
10. Use pagination for image, prediction, job, and version lists.

Before completion, run the relevant commands for:

- Python formatting and linting.
- Python type checking.
- Backend unit and integration tests.
- Frontend formatting and type checking.
- Frontend unit tests.
- Relevant Playwright end-to-end tests.
- Alembic upgrade and downgrade checks.
- Production build.

In the completion report, include:

- Summary.
- Files changed.
- Migration names.
- Tests and command results.
- Manual verification performed.
- Known limitations.
- Any specification deviations.

Do not claim completion when acceptance tests are failing.
