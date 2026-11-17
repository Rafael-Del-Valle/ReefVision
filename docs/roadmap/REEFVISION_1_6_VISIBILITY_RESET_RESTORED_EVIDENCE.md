# 1.6 class-visibility reset integrity — imported/restored JSON

Status: **implementation checkpoint, not release approval** (2026-11-17).

## Audit and gap

Class management, per-user/project visibility, QC, dense-object rendering, onboarding
and persisted typed QC Workflow Builder already exist on the isolated 1.6 branch.
Earlier 1.0–1.5 branches have legacy visibility reset behavior; this adds no
duplicated feature or workflow node. Prior 1.6 safeguards reject malformed
restored JSON during editor GET and PUT, but a revision-checked DELETE previously
used a direct SQL DELETE (no JSON hydration), so it could silently erase the
same corrupted source evidence. Legacy DELETE could also discard JSON shapes
that hydrate successfully but do not represent `list[str]`.

## Safety contract

Both personal-preference and project-default reset paths now:

1. Validate the project, layer and optional revision-token pairing.
2. Acquire the same local SQLite project writer turn used for class-visibility
   saves, before reading the affected row. Hold it through the final delete.
3. Hydrate the affected scope and validate its saved JSON shape using the same
   existing sanitizer as GET/PUT, including compatibility for deleted IDs
   and duplicates. Invalid JSON or invalid nested/scalar forms return HTTP 409.
4. Preserve original corrupt bytes, scientific annotations and other projects.
   **Never automatically repair, stamp, truncate or delete corrupt evidence.**
5. Retain conditional compare-and-delete behavior against updated timestamp
   and record ID. Legacy unconditional reset still works for valid records.

Twelve disposable-database HTTP regressions cover three malformed JSON forms,
both scopes and both conditional/legacy reset contracts. Each checks a 409,
unchanged stored bytes, explicit *test-only* restoration, successful reset with
the previously observed revision and independent project access. The existing
visibility CAS and persistence tests remain applicable.

Class visibility is an editor display preference, not a scientific workflow
artifact. No new Workflow Builder node is required: existing saved/executable
`project_source → qc_review_queue` graphs, typed outputs, provenance,
retry contracts and mandatory human-review gates are untouched.

## Unresolved release gates

The 1.1/1.6 conflicting Alembic-0038 migration lineages still require
independent, data-preserving reconciliation. Verify exact-head repository
Ruff/mypy/pytest, frontend/E2E and migration checks; real biological inputs,
saved-workflow acceptance, Windows MSI/CAB clean install/upgrade/rollback,
installed-GUI behavior and explicit owner approval. Local Git checkout in
the automation environment fails DNS; isolated SQLAlchemy/SQLite reproduction
is not a substitute for repository tests. Do not merge, tag, release or mutate
research assets based on this checkpoint.
