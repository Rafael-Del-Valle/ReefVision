# ReefVision 1.6 — reviewed Alembic marker comparison

The read-only `scripts/inspect_sqlite_lineage_16.py` supports
`python scripts/inspect_sqlite_lineage_16.py current.sqlite --compare-to reference.sqlite --fail-on-revision-mismatch`.

The JSON `schema_comparison.revision_markers_match` field reports whether both
databases have exactly one valid, identical Alembic revision marker. The optional
gate exits 2 on unequal, missing or malformed markers, after emitting JSON.
Without the flag, inspection remains informational. Both inputs use SQLite
read-only connections; no stamps or research assets are modified.

**Scientific limitation:** Equal markers do not establish equal migration
histories, especially the independent 1.1/1.6 revision-0038 collision.
`schema_comparison.matches` checks structural DDL separately; even matching
DDL and markers cannot establish data or migration equivalence. Every report
retains `requires_researcher_review` and must not authorize automatic stamping,
schema repair, workflow replay approval, or scientific-data changes.

Regression coverage includes identical DDL with differing marker values,
identical values, malformed reference metadata and byte preservation. Full
repository, Workflow Builder saved-run and Windows MSI acceptance remain required.
