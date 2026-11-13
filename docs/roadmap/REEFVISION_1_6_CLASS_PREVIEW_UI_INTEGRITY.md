# ReefVision 1.6 — class operation preview selection integrity

Manual class reassignment and reassign-and-delete now bind their preview
operation ID/checksum to the exact researcher-selected project, source class,
target class, normalized audit notes and a local edit epoch. Changing a target
or notes invalidates both executable approvals, even when the researcher
changes a value and later returns to its prior value. A delayed preview HTTP
response cannot re-enable execution for a different current selection.

The GUI additionally checks the returned preview status, project, source,
target, and operation type before enabling its execute button. Following a
successful operation, that preview is consumed. A mismatch displays a
non-executable warning and requires another explicit preview. The backend's
existing saved plan/checksum/reference-integrity checks remain authoritative.

This is protection for an inherently **manual scientific class-management
operation**, not an automated class-reassignment Workflow Builder node.
Existing typed, executable, persisted QC Workflow Builder tasks and human
review gates remain unchanged. Neither immutable dataset versions nor
registered model class maps are rewritten by this GUI guard.

Frontend regressions exercise both operation types, target change/reversion,
audit-note edits and a delayed successful preview that arrives after a target
change. Mocked UI checks do not establish scientific accuracy or Windows
installed-GUI/MSI release readiness. Those acceptance gates and independent
1.1/1.6 Alembic revision-0038 reconciliation remain outstanding.
