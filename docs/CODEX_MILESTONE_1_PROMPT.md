# Codex task: ReefVision Milestone 1

Read `AGENTS.md`, `docs/REEFVISION_PRODUCT_SPEC.md`,
`docs/ARCHITECTURE.md`, and `docs/MILESTONE_0_REPORT.md` before editing.

Implement **Milestone 1 — Projects, classes, and managed storage only**.
Do not begin image importing or annotation features.

Before editing, inspect the current repository and provide a concise file-level
plan. Then implement the milestone with the following required scope:

1. Add `projects` and `label_classes` SQLAlchemy models.
2. Add a new Alembic migration; do not edit migration `0001`.
3. Add project repository and service layers.
4. Add safe managed project-directory creation beneath the configured data root.
5. Add project create, list, retrieve, update, and archive endpoints.
6. Add class list, create, update, and deactivate endpoints.
7. Enforce unique project slugs and project-local class names and indices.
8. Add the exact six-class octocoral template defined in the product spec.
9. Build the project dashboard, project-creation flow, and class-management UI.
10. Add backend unit/integration tests and frontend component tests.
11. Add relevant end-to-end coverage only if the repository already has a
    stable Playwright setup; otherwise document its introduction for the next
    UI workflow milestone.
12. Update documentation and the changelog.

Run every check required by `AGENTS.md`, including Alembic upgrade and downgrade
verification. Report changed files, migration name, test results, manual
verification, known limitations, and specification deviations.

Do not claim completion unless every Milestone 1 acceptance test passes.
