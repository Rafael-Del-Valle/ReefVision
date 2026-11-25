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

## Joint filtered-sample bound (2026-11-25)

When a researcher selects pending predictions with confidence at most t,
every confidence deficit is at least b = 1 - t. If the largest observed
deficit is d and the selected count is n, the mean deficit must be at
least b + max(0, d - b) / n. Checking the selection and unfiltered sample
bounds independently is insufficient. The v3 validator now checks their
joint bound with the existing 1e-12 selection tolerance. This is a
necessary consistency check, not authentication of the original model
predictions. No live predictions are read or review state changed.

Five synthetic re-signed cases and two additional standalone API and
saved-graph replay cases cover this constraint. Independent Python checks
passed for 1,926 valid producer samples and four contradictory filtered
samples that met both former separate bounds. Full repository pytest is
not yet verified. Exact-head CI #45562778337 passed frontend and native
Windows preservation but stopped at the fixture signature Ruff formatting;
that exact formatting has been corrected. Release HOLD and all earlier
scientific, integrated migration and installed GUI gates remain in force.
