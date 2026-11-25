# ReefVision 1.6 — finite pending-confidence sample bounds

2026-11-25 — release HOLD; isolated draft PR #77.

The v3 QC producer calculates inverse mean and inverse minimum confidence
from the same selected pending predictions, with each confidence in [0, 1].
For n >= 2, the largest individual deficit must be at most n times the
mean deficit. A saved snapshot can otherwise claim an impossible minimum
even with a valid digest, score, rank and explanation. Validate the bound
using division by n to avoid overflow and one binary64 epsilon to preserve
producer rounding near confidence 1.0. Existing zero/singleton rules,
v2/unversioned compatibility, typed dimensionless workflow output, immutable
provenance, and explicit researcher review are unchanged.

Six synthetic re-signed snapshots exercise exact boundaries and impossible
samples. Two additional standalone API and persisted saved-graph retry
cases use two local synthetic predictions. Independent Python checks of
8,771 actual producer confidence samples and six impossible examples
passed, including a near-one rounding boundary. Full repository pytest
and final CI are not claimed passing; local checkout fails GitHub DNS.

Previous exact-head CI #45554649574 passed frontend and native Windows
research-preservation but stopped at mypy on two inferred scalar index
lists in the read-only migration guard. Use the existing mapping-row
pattern instead, retaining identical index identity semantics.

Release remains held for integrated migration reconciliation, full CI,
representative biological workflows, installed Windows MSI/CAB GUI and
upgrade/rollback, and explicit researcher approval. No new migration,
duplicate node, external weights or changes to other version branches.
