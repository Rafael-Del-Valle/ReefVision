# ReefVision 1.6 — isolated Alembic parent-graph preflight

**Status: diagnostic only; RELEASE HOLD.** Coordinates with [issue #76](https://github.com/Rafael-Del-Valle/ReefVision/issues/76) and draft PR #77. This does **not** reconcile the independent 1.1 and 1.6 migration histories or authorize any migration on a research database.

## Why this increment exists

The existing read-only revision-collision audit catches two distinct files claiming the same Alembic revision. That alone is insufficient: a collision-free revision inventory may still have a missing parent, a cycle, two unmerged heads or a malformed dynamic `down_revision`. In particular, 1.1 scientific `0038/0039` and 1.6 reviewer-QC `0038–0041` must remain separate until a coordinated, scientifically validated integration path exists.

The optional `--verify-parent-graph` checks each supplied **complete local migration directory independently**. It statically parses one literal `down_revision` declaration per migration; accepts `None`, a single string or a tuple/list of literal strings; and refuses dynamic expressions, later bindings, malformed parent IDs or duplicate parents. It reports root revisions, heads, missing parents, cycles and duplicate IDs, with `parent_graph_consistent` in the JSON output. The CLI exits with status 2 for any inconsistent graph or revision-ID collision. It never imports or executes a migration module, modifies files or suggests automatic stamping.

Example, on a **separately prepared read-only source checkout**, not against user databases:

```bash
python scripts/audit-alembic-revision-collisions.py --verify-parent-graph apps/api/migrations/versions
```

For comparing two development histories, inspect a separately checked-out, complete migration directory for **each** version. A healthy parent graph within each version does not cancel overlapping revision identifiers between versions. Retain the default revision-collision check and original source hashes. A nonzero result means **human reconciliation is required**, not that a migration should be repaired automatically.

## Acceptance boundaries

Disposable-source regressions cover linear and merged DAGs, missing parents, unmerged heads, cycles, rebinding, invalid parent literals, cross-root collision detection, unchanged source bytes and strict CLI exit behavior. Linux backend CI runs Ruff and pytest; lightweight Windows CI runs the same parent-graph tests. A successful result is static source-contract evidence only. It does not demonstrate migration of populated 1.1/1.6 databases, preserved coral observations, saved typed QC Workflow Builder graphs and run provenance, reviewer approvals, hardware validation, Windows MSI/CAB installation, or safe upgrade/rollback.

This is an **offline migration evidence gate**, not a new biological analysis capability. No duplicate Workflow Builder node is introduced; existing executable saved `project_source → qc_review_queue` workflows, typed units, immutable QC history and explicit researcher review remain untouched. Scientific integrity still requires reviewed 1.1/1.6 DAG reconciliation on representative **copies**, standalone and saved-workflow acceptance, full CI, actual installed Windows GUI testing and explicit researcher approval before release. Do not auto-merge version branches, stamp ambiguous databases, release installers, download models or delete assets.
