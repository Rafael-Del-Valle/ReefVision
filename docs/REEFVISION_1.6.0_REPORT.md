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


## 2026-11-19 — Frozen study split-protocol and grouping reconciliation (Track D)

The original 0006 and 0007 dataset producers record the requested and
resolved split method, ratios, random seed, parent-assignment reuse, warnings
and biological missing-group count on both the dataset version and its
immutable manifest. Frozen scientific QC now verifies that this split
configuration agrees at both persistence layers, independently recomputes
the count of ungrouped images, and verifies the *achieved image ratios*
for train/validation/test from actual frozen membership. This prevents
re-signed metadata from falsely claiming group protection or different
train/test allocations without authorizing any alteration of original
annotations. Grouped parent-colony separation remains an independent gate.

Synthetic historical-schema and real database tests cover protocol drift,
forged missing-group counts and achieved ratios, standalone QC, executable
saved typed Workflow Builder refusal, rollback, replay and preservation of
pending researcher review. A prior CI assertion also reflects the actual
shared-validator-first failure for the row-only eligible-status-drift case.
These checks validate frozen metadata, **not original image bytes**, and
do not solve the independent 1.1/1.6 Alembic-0038 collision. Real Windows
MSI/GUI installation, migration reconciliation, full scientific CI and
explicit researcher release approval remain mandatory.


## 2026-11-19 — Collision-safe biological group versus singleton split identities (Track D)

Audited the original 0006/0007 shared dataset split producer, the 1.6
frozen QC validator and existing executable typed saved QC Workflow Builder.
The producer keyed a missing-group image as `image:<image_id>`, which could
collide with an explicitly supplied biological group key of the same literal
string. Two *independent* units could be inadvertently pooled; conflicting
manual train/test assignments could be rejected as if they came from the same
colony. The source planner now uses separate group/image key namespaces, while
retaining legacy scalar ordering for non-colliding historical inputs and
preserving seed reproducibility for ordinary datasets. No existing frozen
dataset or immutable study evidence is rewritten.

A database-backed regression covers real image imports, manual preview,
persisted version/image split provenance, standalone QC and an executable
saved `project_source → dataset_version_source → qc_review_queue` graph run
twice. It requires typed dimensionless priority, unchanged manifest identity,
two pending reviewer decisions and no automated approval. No additional
workflow node, database migration, model download or user-asset mutation.
Full backend/frontend/E2E CI and representative MSI installed-GUI validation
are still required. The independent 1.1/1.6 Alembic-0038 collision remains a
release hold.

## 2026-11-19 — Stable seeded split ordering for colliding legacy keys (Track D)

Follow-up to the distinct group/singleton namespace fix: the source planner
retained a duplicate **display sort key** when a literal biological group
was named `image:<singleton UUID>`. A stable Python sort would then depend
on the eligible-image import order before seeded random shuffling, allowing
the same two independent samples to exchange train/validation assignments.
For the rare colliding keys the planner now uses the immutable per-unit image
ID list as a tie-breaker. All unique historical sort keys, existing frozen
studies and ordinary seeded split ordering remain unchanged.

Added an in-memory permutation regression alongside the existing real-DB,
standalone scientific QC and executable saved Workflow Builder acceptance test.
Also applied the exact two-file Ruff-format patch from CI #44580139218,
which failed before backend pytest. Complete exact-head CI, representative
biology, Windows MSI/installed-GUI testing, 1.1/1.6 Alembic-0038
reconciliation and explicit release approval remain open. No review
automation or data migration is introduced.


## 2026-11-19 — Explicit split decisions must bind to the eligible study cohort (Track D)

- **Audit:** The original 1.0–1.5 dataset-version producer already accepted researcher-directed manual split choices; 1.6 adds immutable scientific QC, class management and typed executable Workflow Builder. In the existing shared split planner, manual image IDs absent from the current eligible cohort were silently ignored. A stale, excluded or cross-project image identifier could therefore leave an investigator believing a required holdout decision had been enforced.
- **Correction:** Before either preview or creation plans a split, validate that every explicitly assigned image ID belongs to the selected project's eligible image cohort. Reject absent, excluded and foreign-project image IDs with a controlled validation error. Legitimate manual assignments and frozen versions are unchanged. No migration, new workflow node, model download, approval automation or alteration of historical research records.
- **Regression:** Real imported-image API coverage creates a valid reviewed subset and persisted executable `project_source → dataset_version_source → qc_review_queue` graph, verifies rejection of unknown/excluded/cross-project explicit assignments in **both** preview and version creation, checks no extra immutable dataset is created, and replays the saved graph without provenance drift or lost pending human-review gates. Corrected the preceding exact-head CI Ruff import-order finding in the same test file.
- **Release HOLD:** Full exact-head Ruff/mypy/pytest/frontend/E2E, independent Alembic-0038 1.1/1.6 reconciliation, representative biological acceptance, genuine Windows MSI/CAB installed-GUI clean install and upgrade/rollback, and researcher approval remain required.

## 2026-11-19 — reject noncanonical legacy blank colony groups (Track D)

Previously, a stored empty/whitespace-only `group_key` bypassed the image
metadata API's normal blank-to-null rule. Dataset splitting interpreted it
as a non-null colony key and pooled unrelated images, potentially changing
train/validation/test assignments and misrepresenting sampling units. The
shared split planner now refuses this malformed legacy metadata rather than
silently assigning those samples together; previously frozen records remain
unchanged. Normal API-created null group keys still form independent image
units.

A database-backed regression mutates a disposable image's live group key,
requires both dataset preview and creation to reject it, and proves that
standalone QC and twice-executed persisted typed Workflow Builder QC still
retain frozen manifest provenance, dimensionless priority scores, and
pending researcher approval. Recovery after restoring the source key is
also checked. No new migration or duplicate workflow node was introduced.

The immediately preceding CI failed one Ruff I001 import-order gate before
backend pytest; that exact import ordering was corrected in the same commit.
Full backend/frontend/E2E/native-Windows and real installed MSI/GUI acceptance
must still be verified on the resulting head. The independent 1.1/1.6
Alembic-0038 collision and explicit researcher release approval remain HOLD.


## 2026-11-20 — Reject ambiguous installed launcher actions (Track D)

Audited the existing 1.6 managed start/update command preflights, class visibility,
review QC and executable saved Workflow Builder against the 1.0–1.5 scope.
The installed `start-reefvision` launcher previously accepted combinations such as
`--status --restart` or `--status --dev` and returned successfully after
performing only the first matching action; `--no-wait` and `--safe-mode`
were similarly ignored in development/read-only modes. The start preflight now
rejects ambiguous action combinations **before** process launch, API access,
or saved repository configuration. Explicit `--configure-repo PATH --status`,
a single development mode, safe-mode/restart and normal read-only invocations
remain supported. Boolean-mode counts do not use PowerShell's ambiguous
`@($null).Count` semantics.

Nine new Windows child-PowerShell regressions use isolated `LOCALAPPDATA`,
require nonzero exit and appropriate diagnostics, and verify that the prior
configuration hash remains identical after rejection. Existing valid-config
and `--help` cases remain in place. The suite is already registered in the
Windows CI preservation job. No scientific data, model weights, migrations,
or installed binaries are modified. This command-only preflight is not a new
scientific Workflow Builder operation: existing typed executable QC, persisted
runs, provenance, retries and researcher approval remain unchanged. CI on
this exact head, genuine installed MSI/GUI testing, 1.1/1.6 Alembic-0038
reconciliation and release approval remain required.

## 2026-11-20 — Updater read-only status / disabled cleanup action preflight (Track D)

The 1.6 MSI updater already had safe source/installer identity checks and
configuration isolation, but `--status --build-only`, `--status --test`,
`--status --install-only`, and similar mixtures returned success after showing
status without carrying out the requested action. Likewise `--dry-run
--clean-build` reported a successful plan despite the cleanup operation being
explicitly disabled for user-asset safety. The parser now rejects mixed
status/update actions and refuses disabled cleanup **before** repository
resolution, any persistent setting, update lock, setup, API, or MSI operation.
Intentional standalone `--status`, `--dry-run`, `--configure-repo PATH
--status`, and `--help` remain supported; no installer, user assets, models,
scientific records, or migrations are changed.

Ten native-Windows child-PowerShell regressions are added to the existing
registered MSI updater preflight, using disposable `LOCALAPPDATA`, nonzero
exit/diagnostic checks, and SHA-256 verification that rejected invocations
leave the original command configuration unchanged. This is an out-of-band
CLI safety contract, not a new biological analysis: the already implemented
typed executable/saved QC Workflow Builder, provenance, retry semantics and
researcher-approval gates are unaffected. Exact-head CI, Windows MSI/CAB
clean installation/upgrade/rollback, installed-GUI acceptance, representative
biological saved-workflow validation, independent 1.1/1.6 Alembic-0038
reconciliation and explicit owner approval remain release holds.
