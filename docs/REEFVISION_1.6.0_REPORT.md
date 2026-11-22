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

## 2026-11-20 — Reject aliased research-media ancestors during offline upgrade preflight (Track D)

The migration-copy media integrity check already rejected symlinks/junctions
at the scoped asset root and inside it, but a real directory nested beneath a
**symlinked parent** could pass root-only inspection. The preservation verifier
now checks the complete lexical ancestry of each baseline and candidate asset
root, including Windows junction/reparse points, before comparison, during both
inventories, and during the final tree recheck. Any alias refuses preservation
with `asset_symlink_not_allowed`; neither the media path nor private filenames
appear in the diagnostic evidence. Existing ordinary independent offline media
folders and additive assets retain the original behavior.

Four parameterized subprocess regressions cover baseline/candidate aliases
one or more levels above otherwise ordinary research-media roots, assert
nonzero HOLD, no disclosed filenames, and unchanged SQLite/media bytes.
An independent Python filesystem probe confirmed the original root-only check
cannot detect an ancestor symlink. These are **not** a substitute for exact-head
repository pytest/Windows CI, real MSI/CAB upgrade and installed-GUI testing.
This optional offline migration preflight is not a scientific analysis node;
existing saved executable typed Workflow Builder QC, units, retries,
provenance and mandatory researcher review are unchanged. The independent
1.1/1.6 Alembic-0038 conflict and explicit release approval remain HOLD.

## 2026-11-20 — New SQLite triggers on protected research/QC tables require review (Track D)

The offline 1.1/1.6 migration-copy verifier previously required only that
*existing* triggers survived. A candidate upgrade could add an AFTER INSERT
trigger on a preexisting scientific or reviewer table that doubles future
measurements or changes review evidence, and still return a preservation-only
PASS when historical rows match. Added triggers now cause
`changed_trigger_contract` and HOLD; the comparison preserves normal SQL
whitespace/case normalization, permits additions to entirely new tables, and
does not expose source trigger SQL or biological identifiers.

Regression coverage includes two protected tables, a disposable independent
SQLite future-write oracle, read-only byte preservation, private-data
redaction, existing benign new-trigger expectations, and an unrelated
new-table trigger control. This is a **preservation-only** preflight, never
automatic migration approval. Repository CI, 1.1/1.6 revision-0038
reconciliation, real MSI/CAB installed-Windows GUI/upgrade/rollback, saved
scientific workflow acceptance and explicit researcher approval remain HOLD.
No Workflow Builder operation was added: the verifier is an out-of-band
offline migration diagnostic, and existing executable typed QC graphs,
provenance, retries and researcher-review gates were not changed.

## 2026-11-20 — Dense-object browser recovery after list shrink (Track D)

The existing 1.6 editor already bounds dense object rendering, preserves
selection pins and allows source-position jumps; no replacement browser or
scientific workflow node is needed. An earlier jump offset could remain above
the available filtered-document count after annotations were deleted or the
list changed. The browser previously clamped to only the last record even
when a full 200-row inspection window remained. It now recovers the last
available full window for an out-of-range offset, while preserving deliberate
in-range jumps and any selected objects outside the window. Annotation and
mask document arrays, saved research evidence, QC decisions and existing typed
saved Workflow Builder graphs are not modified. Vitest regression cases cover
the annotation-to-mask boundary, pinned selections, unchanged source arrays
and an intentional near-end jump. Full frontend/E2E CI and real installed
Windows usability validation remain required; version 1.6 remains on release
HOLD for the unrelated Alembic-0038 collision and scientific/packaging gates.

## 2026-11-20 — Linear-time dense-object selection row rendering (Track D)

The 1.6 browser already bounds its regular document window and pins at most
200 off-window annotations and 200 masks. Each rendered row still called
Array.includes on a potentially 50,000-object scientific range selection,
repeatedly scanning that selection. The new display-only helper collects
mounted IDs and scans each selection array at most once, storing only IDs of
selected mounted rows; box and mask ID namespaces remain separate. Vitest
regressions cover selected pins, mixed types with identical IDs, 50,000-object
selection read bounds, and an empty-row short circuit. This is not a new
scientific operation: stored observations, selection arrays, typed executable
and saved QC workflows, units, provenance, retries and human-review gates are
unchanged. Full exact-head CI and installed-Windows GUI responsiveness remain
unverified; Alembic-0038 lineage and explicit approval remain release HOLD.

## 2026-11-21 — Dense annotation selection and deletion indexing (Track D)

The editor's class reassignment, box-drag snapshot and selection deletion paths
used per-object `Array.includes` lookups against potentially tens of thousands
of selected coral observations. Class reassignment also fabricated a dirty
revision when the selected annotation already had the requested class; stale
selection IDs could dirty the document on deletion. The 1.6 branch now indexes
selection membership in sets, performs box/mask deletion through the existing
persisted-mask tombstone contract, and skips document commits when no matching
scientific observation changes. A 20,000-box selection regression, mixed
persisted/unsaved mask deletion cases, stale-ID identity tests and a React
no-op class/autosave regression have been added. Annotation and mask source
records, existing QC audit trails and typed saved Workflow Builder approval
and retry semantics remain unchanged. No duplicate workflow node or database
migration is necessary for editor-only operations. Full exact-head CI and
native installed Windows GUI large-image usability validation are required.
**RELEASE HOLD:** separate 1.1/1.6 Alembic-0038 histories, representative
biological/saved-workflow acceptance, MSI clean install/upgrade/rollback and
explicit researcher approval remain outstanding.


## 2026-11-21 — Rotated-mask corner crossing stays on the fixed anchor side

Audited the earlier 1.0–1.5 annotation primitives against the isolated 1.6
rotated-box editor and existing typed saved QC Workflow Builder. Dragging a
rotated rectangle corner across its fixed opposite vertex previously used
absolute projected edge lengths. That reflected the edited box back across
its anchor instead of preserving the grabbed corner's source-pixel side,
potentially revising a coral measurement unintentionally. Resize now uses
winding-aware signed projections for the existing two-pixel minimum width
and height. Original source images and existing annotation records are
unchanged until an intentional accepted edit.

Added interaction regressions for horizontal/vertical crossing, historical
reverse-wound geometry, preservation of record identity and revision metadata,
and a cross-and-return gesture that must not create a scientific revision.
An isolated arithmetic check confirms three clamped outcomes; repository
Vitest, Playwright, backend, migrations and Windows installed-MSI/GUI
acceptance remain subject to exact-head verification. This editor-only
scientific integrity change does not introduce a duplicate Workflow Builder
node or migration. Previously implemented executable typed QC saved graphs,
provenance, retry and researcher-review gates are unchanged. Independent
1.1/1.6 Alembic-0038 reconciliation, representative biological saved-workflow
acceptance, genuine MSI/CAB installation/upgrade/rollback and explicit
researcher approval remain release holds.
