# ReefVision 1.6 — preserve saved scientific SQL views across offline upgrades

**Status: release HOLD.** Isolated `develop/reefvision-1.6`, draft PR #77.
This is a read-only acceptance diagnostic, **not** a migration or authorization
to upgrade a researcher's only database.

## Gap

The existing offline row-preservation verifier checks protected biological,
class visibility, QC review and saved Workflow Builder tables, including their
record values, constraints, triggers and structural contracts. Identical
historical rows do **not** ensure research output stability when an existing
SQLite `VIEW` is dropped or redefined, or when an unchanged `SELECT *` view
acquires additional output columns after an otherwise additive table change.

For example, a saved view computing `length_mm * 1.0` versus
`length_mm * 2.0` may produce the same result for all zero-valued historical
coral measurements but would produce incorrect future measurements.

## Protection

The offline tool now captures every preexisting, persistent SQLite main-schema
view's normalized SQL tokens and its *evaluated output-column contract* within
the read-only transaction of each independent database copy. Missing or
changed original views produce HOLD, even when every protected table row
matches. Newly added views and equivalent SQL keyword/whitespace formatting
remain permitted. Views are verified separately from ordinary tables because
they are scientific query definitions, not persisted measurement rows.

Diagnostics reveal only aggregate view counts and fixed reason codes
(`research_views_missing`, `research_view_contract_changed`).
Researcher-defined view names, underlying SQL, study/sample identifiers and
row contents must not appear in JSON or CI logs. The tool never alters either
database or invokes Workflow Builder. Existing executable typed QC nodes,
saved graphs/runs, provenance and researcher review gates remain intact; an
offline migration preflight is deliberately not duplicated as a workflow node.

## Acceptance and boundaries

Seven disposable-SQLite scenarios cover dropped/renamed views, changed
scientific formulas with equal current observations, `SELECT *` shape drift,
unchanged views, newly added views and equivalent formatting. They assert
stable database bytes, redacted reports and continued explicit approval.
Full repository Ruff/pytest/mypy/frontend/Playwright, representative biological
data and saved-workflow regression, independent 1.1/1.6 Alembic-0038 lineage
reconciliation and *genuine* Windows MSI/CAB installed-GUI clean installation,
upgrade and rollback remain separate requirements.

The view inventory covers persisted SQLite main-schema views, not temporary
connection-local views, external database ATTACH aliases, arbitrary external
files, or semantic equivalence of reworded SQL. It intentionally fails closed
where original view definitions or result shapes cannot be established.
