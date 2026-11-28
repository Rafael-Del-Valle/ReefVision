# 1.6 QC candidate integration delta — 2026-11-28

**Release HOLD.** This is a read-only source comparison and integration
acceptance handoff, not a merger, a migration, or a claim that a candidate
has passed independent biological acceptance.

## Pinned evidence

- Isolated draft #77: `d7350b34c31e4ac6295830d7639938ccbb11bcc6`.
- Integrated draft #102: `a580042e84c4d2fa0a646fbf8ec5a3dc90657fa8`.
- Integrated drafts #107 (1.7): `556fc98b9f4e0591a542e13dd0ef36ea1b950a80`
  and #119 (1.8): `e3e8ffb6395c9f2675ffc10397c2401388e63ee8`.
- GitHub compare reports 2,571 commits ahead / 4,129 behind for #77 versus
  #102, with common base `9278d45e894cffa2da582df58c2dbf4a4bdac327`.
  This is not an appropriate whole-branch merge.
- The integrated inventory already includes safe class management, class
  visibility/dense editing, independent migration reconciliation, onboarding
  and reviewer assignment/bulk retry. Earlier main/1.0.3/1.1/1.2/1.4/1.5
  contents requests for this specific QC integrity module returned 404;
  this is not evidence that all earlier QC functionality is absent.

The following files under `apps/api/reefvision/services/` were fetched at
all four pinned heads. Each integrated source had identical blob IDs for
these three modules; the isolated candidate has later, distinct guards.

| File | Isolated blob | Integrated 1.6/1.7/1.8 blob |
| --- | --- | --- |
| review_queues.py | 73f014326ea85bfc42777f101b8d7e4773b63fe7 | 078c301bb9ed6a7086728373dcd5c97aeac14a20 |
| workflow_review_queue.py | 8fc8827c723b34df2f424277f5e949ba6fa4d73a | 6ca588da30db8343664fa66883fa1e75b70e499b |
| workflow_review_queue_integrity.py | 714ece3a953bf6b3d4698897c26700c7599d1199 | fe080653b0099763dcbf3d515d6d826b4e265c4c |

## Required selective integration review

The integrated implementation already rejects a substituted frozen image or
split during saved replay, preserves completed queue identity, and retains
scientific review gates. Do not replace these modules wholesale: the
integrated version factors out `queue_reference_payload` and may depend on
later work. Review the following distinct contracts and their callers.

| Priority | Isolated contract | Integrated source gap at pinned heads |
| --- | --- | --- |
| P0 | `validate_saved_queue_membership` and `validate_frozen_queue_annotation_evidence` in replay AND standalone regeneration | Replay checks each item's split but not complete v3 cohort coverage or independently recomputed annotation/class/group evidence. Manual regeneration lacks the shared integrity gates. |
| P0 | `ReviewQueueService` regeneration refuses incomplete queues, malformed JSON and re-signed evidence | Preserve original queue and review decisions; verify before constructing any replacement queue. |
| P0 | Real JSON array for interrupted saved output binding; real object for saved parameters/configuration; independent typed weight validation | Falsey non-list output can bypass the integrated conditional; dictionary coercion and Python equality can erase malformed types. |
| P0 | Compare saved artifact digest against canonical JSON of expected payload | Integrated comparison uses Python object equality after validating only the artifact's own digest. Boolean/number substitutions may compare equal. |
| P1 | Reject explicit null integrity marker/digests, nonfinite or zero total weights, boolean item weights | Keep historical absent-marker compatibility; never let explicit null downgrade the contract. |
| P1 | Prediction-confidence feasibility (zero/single/multiple pending predictions, joint bounds for selected predictions) and fully rejected sample consistency | Reject impossible re-signed QC scientific signals while retaining producer roundoff tolerance. |

These are source-level differences, not proof that a particular user database
has suffered corruption. Preserve both candidates and review the shared
producer formulas, version-specific behavior and migrations before porting.

## Regression transfer checklist

Compared test function definitions in seven files at #77 and #102.
Twenty-two named tests occur only in the inspected #77 files (absence here
does not exclude an equivalent test in another integrated file). Two files
are byte-identical: `test_workflow_review_queue_summary_types_16.py` and
`test_workflow_review_queue_selection_presence_16.py`. The frozen timestamp
test is also byte-identical at all four heads. Do not duplicate them.

Under `apps/api/reefvision/tests/`:

- `test_workflow_review_queue_integrity_16.py` (9): explicit null digest,
  null version marker, single-pending equal/unequal confidence, absent
  pending confidence, feasible mean, selected joint bounds, empty-v2
  finite positive weights, re-signed boolean item weight.
- `test_workflow_review_queue_frozen_dataset_16.py` (3):
  `test_manual_regeneration_refuses_resigned_false_split`,
  `test_manual_regeneration_refuses_resigned_frozen_class_evidence`,
  `test_manual_regeneration_requires_complete_queue`.
- `test_workflow_review_queue_weights_16.py` (8):
  `test_invalid_confidence_threshold_refused_before_qc_execution`,
  `test_numeric_confidence_boundary_matches_saved_qc`,
  `test_qc_retry_rejects_equal_looking_boolean_parameters`,
  `test_saved_qc_retry_rejects_nonobject_parameter_contract`,
  `test_prediction_confidence_evidence_on_saved_qc_retry`,
  `test_fully_rejected_prediction_evidence_on_saved_qc_retry`,
  `test_interrupted_qc_retry_requires_real_output_list`,
  `test_qc_retry_refuses_malformed_queue_configuration`.
- `test_workflow_review_queue_16.py` (2):
  `test_standalone_qc_rejects_nonnumeric_weight`,
  `test_qc_source_run_id_type_parity`.

Run the affected modules in the integrated checkout after an authorized
selective port; retain existing integrated tests and first reproduce the
negative controls before a fix. Validate successful standalone generation,
saved graph execution/replay and manual regeneration; refusal must leave
old queue, artifact identity, pending review, original observations and
source checksums unchanged. For v3 frozen inputs validate complete membership
and independently derived dimensionless score signals. No automatic approval.

## Current qualification boundary

The connector returned 14 successful PR-triggered workflows for #102 and
20 for #107. For #119 the Windows package workflow succeeded, but exact
head general CI and 1.0 acceptance failed; the PR describes a separate
Pillow test-only correction. Do not treat another commit's evidence as
exact-head success. #77 returned no listed PR-triggered workflow runs at
its pinned head.

Nine independent local Python probes passed: four equal-looking JSON values
had distinct canonical digests (including a payload item-count boolean
versus integer); five falsey non-list values were not valid empty output
arrays. These demonstrate the relevant language semantics, not execution
of the repository's QC paths. Repository clone failed on GitHub DNS; no
new full pytest/Windows test claims. The independent scientific cohort,
predeclared reviewer thresholds, full exact-candidate CI and owner approval
remain open. No schema changes or source observations were changed by this
handoff. No version was accepted, no branches were combined.

Next: review the selective integration checklist with the owner and
candidate maintainers rather than repeat already implemented installation
and migration work on a divergent branch.

## Additional score-rounding regression — 2026-11-28

The producer accumulates v3 contributions sequentially in schema order,
whereas the validator previously used Python's built-in sum on an iterator.
Python 3.12+ uses compensated summation for floats. With one pending
prediction at confidence 0.2 and weights 29, 28, 16, 23 on inverse mean,
inverse minimum, pending count and unreviewed state respectively, the
producer stores 73.12 while Python 3.13's iterator sum rounds to 73.13.
The isolated validator now reproduces the original v3 accumulation order
without changing the stored formula, tolerating a different cent, or
rescoring live observations. V2 remains unchanged. JSON key reordering
does not change v3 signal order. The integrated producer uses the same
sequential addition; include this regression in selective integration.
This does not establish arbitrary cross-Python-version compatibility of
the weight denominator for noninteger custom weights.

An independent Python 3.13 numeric probe reproduced the mismatch and
verified all 24 permutations of the four nonzero inputs, including a
negative control for the adjacent cent. The new standalone, regeneration
and saved-workflow replay regression has not yet executed in repository
CI. No schema change or researcher approval is implied.

### Producer-side order guard (2026-11-28)

The v3 QC producer now iterates the same frozen signal order as replay validation. The existing canonical producer order and formula are unchanged; reordering a caller's mapping cannot change a half-cent priority. The regression uses all 24 permutations of four weighted signals and checks the schema order and complete component breakdown. Existing standalone creation, regeneration, saved graph execution and artifact replay coverage remains required. The integrated 1.6 producer at `a580042e84c4d2fa0a646fbf8ec5a3dc90657fa8` still iterates the input map; review this narrow guard with the previous replay fix when selectively integrating, without blending branches. Independent arithmetic probes passed; repository execution and Windows qualification are separate gates.

### Prediction lifecycle integrity (2026-11-28)

SQLite stores prediction review status as a string without an enum constraint.
The isolated and integrated 1.6 producers previously validated confidence
but silently omitted unknown review states from both pending and reviewed
counts. Reject noncanonical states before either standalone or saved QC
queue creation, even with confidence-based selection. Preserve the four
existing lifecycle states and historical saved evidence; no migration or
score formula change. A new saved run may recover after the local source
record is corrected explicitly; no automatic approval or source mutation.
The existing confidence regression now covers `approved`, `Pending`, and
empty status, filtered standalone refusal, failed saved-run artifact absence,
and recovery with the original pending checksum. Twenty-eight independent
SQLite state/confidence probes passed; full repository tests remain unrun
locally because GitHub DNS prevents checkout. Review this narrow shared
producer guard for selective integration; do not blend branches.

### Prediction project/image ownership integrity (2026-11-28)

Independent SQLite foreign keys permit a proposal belonging to one project
to reference an existing image in another. The previous scoped-image loop
silently dropped such evidence. Check every context prediction against the
requested project and complete image scope before scoring or confidence
selection. Frozen dataset contexts contain no live predictions; their
existing validation is unchanged. The integrated 1.6 candidate at
`a580042e84c4d2fa0a646fbf8ec5a3dc90657fa8` has the same gap.
No automatic repair, schema change or review approval.

Added a foreign-image case to both existing standalone and saved-workflow
database tests, including filtered refusal, preserved original checksum,
absent failed-run artifact and explicit recovery to the original image.
Three independent SQLite probes with foreign keys enabled reproduced the
loss and verified refusal and recovery; full repository execution remains
unverified. Corrected the precise predecessor Ruff formatting diagnostic
in the score permutation regression (CI #46155411232: frontend and native
Windows success, backend format failure). Local checkout DNS is unavailable.
