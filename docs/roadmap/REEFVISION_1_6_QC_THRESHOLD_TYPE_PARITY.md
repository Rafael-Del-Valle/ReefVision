# ReefVision 1.6 — QC confidence threshold type parity

2026-11-26 | Release HOLD

The live standalone QC confidence filter previously coerced Boolean and numeric-string values into probabilities, and Workflow Builder planning did not validate the optional threshold at all. This could unexpectedly select all or none of the pending model proposals. The shared request schema now requires a finite JSON number within the inclusive interval [0, 1], or null/omitted for no filter. Numeric zero and one remain valid; the existing inclusive comparison and frozen-dataset prohibition remain unchanged. The planner validates through that same request schema and emits `invalid_qc_confidence_threshold` before execution for malformed inputs. No migration, new node, scoring-formula change, automatic review or historical evidence rewrite. Previously saved malformed values must be explicitly corrected by the researcher, not silently normalized.

Regression coverage: seven invalid standalone/planning cases refuse without creating queues; two numeric boundary cases exercise real persisted executable QC graphs and standalone selection, dimensionless priorities and pending researcher review. Existing saved-workflow retry and frozen-dataset guards remain required. Fifteen independent Pydantic cases reproduced coercion and verified the strict schema; these are not repository tests. GitHub DNS prevents local checkout. Exact-head CI, independent Alembic-0038 reconciliation, representative biological data and actual installed Windows MSI/GUI upgrade/rollback plus explicit researcher approval remain required.


## Retry parameter type integrity — 2026-11-26

Python dictionary equality considers Boolean flags equal to numeric zero and one. The saved-workflow retry now independently validates the persisted authoritative weights and confidence threshold as well as the supplied request; a malformed Boolean cannot be disguised by an equal-looking numeric retry. Valid historical omitted/default weights and numerical boundaries remain supported. Added eight persisted-workflow regression cases (both directions of substitution, both boundaries, threshold and weights), rollback/replay, queue identity, dimensionless units and pending human review checks. Corrected the exact prior CI formatting diagnostic in the boundary test. No migration, scoring change or automatic review. Independent Pydantic/equality probes are not full repository tests; exact-head CI and installed Windows/biological acceptance remain required.

Persisted QC node parameters must also retain their JSON object shape. A JSON
array of key/value pairs, including a duplicate key that is silently overwritten
by a later pair, must not be coerced into an apparently valid replay contract.
Null, Boolean and other non-object shapes are rejected before queue reuse or
creation. A real empty object remains valid for historical default parameters;
existing optional-weight compatibility is unchanged. The regression writes
malformed JSON into a disposable transaction, verifies refusal, rolls back,
then verifies the original dimensionless, researcher-review-required queue
is replayed without creating another queue.

## Interrupted output and queue configuration shape — 2026-11-26

Only an actual empty JSON list represents a saved QC node whose output has
not yet been persisted. Null, false, zero, empty strings and empty objects
must not authorize output regeneration. A completed node still requires its
existing output and queue, and an interrupted node with a genuine empty list
can replay the same immutable queue. Existing queue configuration must also
be a JSON object before comparing weights and thresholds; malformed scalars
or pair arrays now raise the same domain integrity error as direct snapshot
validation rather than a Python conversion exception. Seven persisted
regression configurations cover refusal, rollback and valid replay, with
pending human review preserved. No formula, data migration or new node.

## Frozen QC consumer binding shape — 2026-11-26

Persisted input bindings must be a list of string artifact IDs before set
comparison. Nested JSON arrays or objects in the dataset slot previously
raised an unhandled TypeError instead of a QC integrity refusal. Reject
non-string IDs before checking membership; preserve the existing exact
membership and cardinality contract, including valid order-independent input
bindings. Five database-backed cases exercise nested arrays, objects, null,
Boolean and duplicate IDs against the saved project + frozen dataset QC graph.
Each checks standalone scientific QC parity, refusal, rollback, exact queue
replay and unchanged pending researcher review. Nine independent SQLite JSON
round-trip checks confirm the guard, including valid input orderings; these
are not a substitute for the repository CI. No new scientific node or migration.

## Explicit QC source identity — 2026-11-26

Only JSON null or an omitted source ID requests automatic historical QC run
selection. Empty strings previously fell through the source selector and
could select an unintended QC run. Shared request validation now rejects empty,
padded, NUL-containing and non-string identifiers; graph planning uses the
same validator, and retry validates the saved source separately. The selector
also distinguishes None explicitly. Existing valid source IDs, automatic
selection, score units, saved queue identity and mandatory human review remain
unchanged. Seven API/planning cases and four saved-run refusal/recovery cases
are added. Twelve isolated Pydantic input/control probes passed; full CI and
installed-Windows acceptance are not verified. No migration or new node.

## Strict numeric QC scoring weights — 2026-11-26

The shared weight model now requires JSON numbers instead of silently coercing
numeric strings (including exponent notation) to dimensionless ranking weights.
Standalone queue creation, saved graph planning and saved-node retry all use
this model. Explicit numerical zero, positive integers and fractional weights
remain valid; defaults, finite-positive-total checks and the existing Boolean
refusal are unchanged. The dashboard already sends parsed numeric weights.
Four additional API/planning cases and four persisted retry refusal cases check
that no alternative queue is created and researcher review remains pending or
in progress. Malformed historical string-valued graph parameters require
explicit researcher correction; no historical evidence is rewritten. No new
node or migration. Isolated Pydantic probes reproduced four previous coercions
and passed 38 validation/control checks; full repository CI remains unverified.
