# ReefVision 1.6 — empty pending-confidence sample integrity

2026-11-24 — release HOLD, isolated draft PR #77.

The original QC producer calculates both inverse confidence signals from
pending predictions only. If none remain, both values are exactly zero,
even when rejected or accepted proposals retain model provenance. A
re-signed v3 queue could previously invent confidence evidence for that
empty sample without affecting a zero-weight priority component.

Require both stored signals to be zero for a zero pending count. Keep
singleton equality and the existing multi-prediction ordering rule.
No live rescoring, migration, new node, or implicit researcher review.
Historical v2/unversioned compatibility is unchanged.

Correct the synthetic v3 fixture to represent its nonzero confidence
with a real pending count and coherent normalization; use the existing
human-only fixture for valid zero-count normalization. Four synthetic
re-signed cases and two additional standalone/API plus saved workflow
retry cases cover retained reviewed-model references, rollback, original
artifact replay, dimensionless priority and pending researcher review.

Independent isolated Python checks reproduced the producer formula for
2,050 valid samples and rejected six contradictory empty samples.
Repository pytest, lint, typing and exact-head CI are not confirmed;
local Git checkout is blocked by DNS. The test cases are not claimed
passing until repository execution confirms them.

Integrated 1.1/1.6 migration reconciliation, representative biological
workflow acceptance, installed Windows MSI/CAB GUI and upgrade/rollback,
complete exact-head CI and explicit researcher approval remain gates.
