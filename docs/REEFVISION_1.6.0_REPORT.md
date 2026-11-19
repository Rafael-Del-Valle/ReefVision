# ReefVision 1.6.0 Report

## Completed In This Pass

- Preserved the earlier project-loading, training-draft, and image-loading improvements.
- Added richer class management:
  - description;
  - archive;
  - restore;
  - delete unused;
  - usage reporting;
  - merge of mutable references.
- Added stronger editor-side class visibility controls:
  - show all;
  - hide all;
  - invert;
  - reset;
  - solo.
- Applied class visibility to prediction review and canvas overlays without refetching the annotation session.
- Added Alembic revision `0011` for class-management fields.
- Added persisted class-visibility infrastructure:
  - stable local-user identity storage;
  - per-user visibility preferences;
  - project-default visibility;
  - layer-aware annotation versus prediction visibility;
  - Alembic revision `0012`.

## Explicitly Still Incomplete

This pass does **not** complete the full requested `1.6.0` scope.

Still pending:

- full packaged `start-reefvision` command work;
- full packaged `update-reefvision` command work;
- desktop installer command repair flow;
- QC bulk actions, reviewer assignment, comments, export, and correction workflow expansion;
- temporary QC reveal restore handling and packaged-desktop validation for the new visibility persistence flow;
- deeper dense-object rendering optimizations and measured large-scene benchmarks;
- packaged-desktop end-to-end validation for the new class-manager and QC scope.

## Exact Validation Run

Passed:

- `python -m pytest apps/api/reefvision/tests/test_projects.py -q`
- `python -m pytest apps/api/reefvision/tests/test_projects.py apps/api/reefvision/tests/test_quality_control.py apps/api/reefvision/tests/test_training_workspace.py -q`
- `python -m pytest apps/api/reefvision/tests/test_projects.py apps/api/reefvision/tests/test_class_visibility.py -q`
- `python -m pytest apps/api/reefvision/tests/test_class_visibility.py -q`
- `python -m ruff check apps/api/reefvision/services/projects.py apps/api/reefvision/schemas/projects.py apps/api/reefvision/api/routes/projects.py apps/api/reefvision/tests/test_projects.py --fix`
- `python -m ruff check apps/api/reefvision/services/class_visibility.py apps/api/reefvision/api/routes/class_visibility.py apps/api/reefvision/repositories/class_visibility.py apps/api/reefvision/schemas/class_visibility.py apps/api/reefvision/storage/identity.py apps/api/reefvision/tests/test_class_visibility.py`
- `python -m alembic -c apps/api/alembic.ini upgrade head`
- `python -m alembic -c apps/api/alembic.ini downgrade 0010`
- `python -m alembic -c apps/api/alembic.ini downgrade 0011`
- `npm --prefix apps/web run typecheck`
- `npm --prefix apps/web run test`
- `npm --prefix apps/web run test -- AnnotationEditor.test.tsx App.test.tsx`
- `npm --prefix apps/web run build`

Not run in this pass:

- full backend mypy strict sweep;
- full desktop packaged smoke test;
- NSIS installer rebuild;
- Playwright desktop workflow suite.


## 2026-10-29 — QC bulk constraint discrimination (Track D)

The persisted manual bulk-QC service now treats **only** real SQLite
idempotency-key collisions as potential competing-reviewer retries. A
matching primary key on `review_queue_bulk_requests.id` or matching
composite audit key on `review_queue_item_events` can be replayed only
after the existing registry, item-selection and event-provenance checks.
Unrelated UNIQUE, NOT NULL, foreign-key and non-SQLite integrity errors
are not converted into successful replay or ordinary reviewer conflicts.
The initial-read SQLite BUSY/LOCKED handler is also Ruff-formatted.

Added regressions for real extended SQLite constraint codes and for
commit-time unrelated-constraint rollback against **both standalone QC
queues and saved, executable Workflow Builder graphs**. The tests require
unchanged annotations and reviewer events after a failed commit, followed
by a successful keyed retry and no duplicate audit events.

Portable independent SQLite/SQLAlchemy check: four real constraint cases
passed (bulk primary key, audit composite unique, unrelated unique and
unrelated NOT NULL). This is **not** a full ReefVision test pass.
Full pytest, Ruff, mypy, frontend/E2E and native Windows installed-GUI
acceptance must be checked against the exact PR head before release.
The independent 1.1/1.6 Alembic revision-0038 collision remains unresolved;
do not merge unaccepted version branches or rewrite installed migrations.


## 2026-11-18 — updater options preserve saved repository configuration (Track D)

The managed `update-reefvision` command previously saved `--configure-repo PATH`
before rejecting mutually exclusive command options. Even
`--dry-run --configure-repo PATH` changed the repository used for a later
scientific MSI build. The updater now rejects dry-run configuration changes
and validates incompatible setup/build/install flags **before** any saved
repository preference is written. Deliberate standalone `--configure-repo`
continues to work.

The native-Windows MSI test suite invokes four rejected combinations in real
child PowerShell processes with disposable `LOCALAPPDATA`, verifies nonzero
exit and the expected diagnostic, and requires byte-identical command JSON.
No build, installation, network access or researcher-data mutation is needed.
This command preflight is outside scientific Workflow Builder; saved typed QC
workflows, approval gates and provenance are untouched. Real Windows MSI/CAB
clean-install, upgrade/rollback, installed GUI, representative biological and
saved-workflow tests, independent 1.1/1.6 Alembic-0038 reconciliation and
researcher release approval remain outstanding.

## 2026-11-18 — updater repository-configuration mode isolation (Track D)

The managed `update-reefvision --configure-repo PATH` operation is mutually
exclusive with setup, skip-setup, build-only, install-only, no-launch,
clean-build, verbose and test options. Previously those combinations silently
saved a new repository preference and returned success without running the
requested action; `--clean-build` could even bypass its safety rejection.
The existing `--dry-run` guard and the intentional `--configure-repo PATH
--status` behavior are preserved. Validate incompatible arguments before
writing `LOCALAPPDATA/ReefVision/config/commands.json`.

Eight additional native-Windows child-PowerShell cases run in disposable
`LOCALAPPDATA`, require nonzero exit and precise diagnostics, and compare the
preexisting configuration SHA-256 after each rejection. They extend the
already-registered MSI updater preflight rather than creating a separate
workflow or touching real installations.

This command-only safeguard does not create an executable scientific Workflow
Builder node. Existing saved typed QC graphs, provenance, reliable retries and
mandatory researcher review are unchanged. No migration or research-asset edit.
Full Windows CI and genuine installed MSI/GUI acceptance remain required.

Native-Windows CI #44446182081 revealed that Windows PowerShell's common
`-Verbose` binding can intercept `--verbose` before the remaining-arguments
parser. The updater now also reads `$PSBoundParameters['Verbose']` so the
configure-only exclusivity guard covers that invocation; diagnostics name
the offending regression case. Exact-head Windows rerun is required.
