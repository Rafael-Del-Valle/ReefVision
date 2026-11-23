# ReefVision 1.6 — saved researcher-review graph-edge integrity

A saved, executable Workflow Builder review gate must approve the scientific input
wired to it by the frozen graph, not just any artifact with a valid SHA-256 and
a succeeded producer in the same run.

Before approval, review validates the saved graph revision's checksum against the
run, project binding, node identities/types, and the single incoming edge's source
node and output port. An altered graph, producer substitution, or rewired port
fails closed. The original prediction/artifact checksum, downstream QC requirements,
SQLite writer serialization, and explicit human-approval behavior remain intact.

The new five-case parameterized regression covers independent tampering modes
through direct service invocation and the persisted workflow-resume API, verifying
that run/node/job remain paused and no researcher approval is recorded.
The existing positive saved consensus-review workflow is the compatibility control.

This is a provenance gate in existing Workflow Builder execution, not a new
node, migration, output unit, synthetic biological measurement, or model download.
All biological assets remain local and unmodified. Full scientific, migration and
native Windows MSI/CAB installed-GUI acceptance remain separate release gates.
