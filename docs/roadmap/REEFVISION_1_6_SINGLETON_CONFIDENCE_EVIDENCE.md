# ReefVision 1.6 — singleton prediction confidence evidence

2026-11-24 — release HOLD; isolated 1.6 draft PR #77.

The original QC producer calculates inverse mean and inverse minimum
confidence from the same pending predictions. For exactly one prediction
these signals must be identical. A re-signed saved snapshot previously
accepted a strictly higher inverse minimum, even with no change to a
zero-weight signal's priority contribution, rank or summary.

Validate equality only for one pending prediction in the frozen v3
contract. No live rescoring, model download, schema change or reviewer
approval is performed. Historical v2 and unversioned contracts remain
unchanged; the existing multi-prediction ordering check remains intact.

Five synthetic snapshot cases and two standalone/API plus saved-graph
retry regressions exercise rejection, rollback, original artifact replay,
dimensionless priority and pending researcher review. An independent
Python calculation verified eight real singleton confidence controls and
three contradictory cases. The repository tests and exact-head CI are
not claimed passing; GitHub checkout is blocked by DNS in this runtime.

Integrated migration reconciliation, representative biological workflow
acceptance, installed Windows MSI/CAB GUI and upgrade/rollback, complete
CI and explicit researcher approval remain release gates.
