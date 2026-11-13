# ReefPose Phase 6 scientific validation

Phase 6 evaluates original Phase 4 identity observations using the Phase 3 landmark
metrics and Phase 5 anatomical measurement and event engines. Reference datasets and
completed reports are stored locally. Migration `0043` adds reference revisions and
`0044` adds write-once held-out protocol locks.

## Prepare independent references

Create the project, register the source videos, and record the stable anatomy schema
ID, revision, and hash. Assign every related video the same `group_id` and partition
the groups before model or threshold selection. The project rejects an existing video
hash or group in a different partition. Preserve original annotation files externally
and include each file's SHA-256 as `original_sha256` when available. The frozen dataset
also hashes the imported contents of each rater record.

Collect labels separately while annotators are blinded to model results and to one
another's labels. The JSON manifest records pseudonymous rater IDs, the blinding
attestation, and the source. The application is local and the manifest remains
visible to the operator. Organize blinding through the research protocol. An
adjudicator imports a separate record with `adjudicates` listing the original rater IDs
and an `adjudication_note`. Amend a dataset by supplying its `parent_id` when freezing
the replacement manifest. A new revision preserves the previous records.

The minimal top-level manifest has `name`, `data_kind` (`synthetic` or `biological`),
and `recordings`. Each recording supplies `video_id`, `video_sha256`, `group_id`,
`split`, `schema_id`, `schema_revision`, `schema_sha256`, `individuals` (stable
`id` and `species`), `annotations` (at least two rater records), and optional
`conditions`, `calibration` and `event_windows`. Biological movement references
also freeze the measurement kind, ordered landmark IDs and options in
`measurement_protocol`. Each rater record accepts:

- `poses` with `individual_id`, `frame`, a source-pixel XYWH box, and stable
  landmark IDs, coordinates and visibility. Mark unobservable instances as
  `occluded`, `ambiguous`, or `missing`.
- `measurements` with `individual_id`, `definition_id`, `frame`, `value`, `unit`,
  and optional `state`.
- `events` with `id`, `individual_id`, `label`, `start_s`, `end_s`, optional
  `peak_s`, `state` (`complete` or `partial`), optional `quality` and optional
  `amplitude` paired with `amplitude_unit`.
- `frame_states` with `individual_id`, `frame`, `label`, and independently
  assigned `open`, `closed`, `ambiguous` or `missing` state.
- `empty_identity_frames` for explicitly reviewed zero-animal frames when
  `exhaustive_identity_coverage` is set.

Scoring windows declare the interval that reviewers labeled, including intervals with
zero events. Set `exhaustive_event_coverage` only if all individuals were inventoried
in the same windows. This allows evaluation of extra predicted identities as event
false positives. Use the OpenAPI schemas at the local application's `/docs` for the
full JSON contract.

## Run and reproduce

From Model Hub or Video Tracking Workspace, open **ReefPose scientific validation**.
Freeze a manifest, select a partition and a rater, choose one completed original
identity run per video, and enter the development configuration grid. Each event
configuration specifies `label`, `definition_id`, `unit`, and the Phase 5 detector
options. A held-out submission takes a completed development job ID and reuses its
configuration. The first test submission pins the reference revision, rater,
development report and original predictions per project, video hash and checkpoint.
The worker verifies source-video bytes, complete original tracking output and
training/selection lineage, including registered initialization ancestors, for
biological runs. A completed zero-detection pose tracking job can supply an empty
prediction set. Retain recording-group assignments and external training provenance
alongside the experiment. Exact content hashes cannot identify re-encoded or cropped
copies, and model selection across checkpoint versions needs a study-level protocol.

Workflow Builder exposes **Independent ReefPose Reference** and **Validate ReefPose
Scientifically**. Connect the reference artifact and one original identity output
per video. The workflow artifact contains the immutable report and input hashes and
the API export route. JSON includes the scored reference snapshot and provenance.
Full CSV flattens the report, and the summary CSV gives per-individual measurement
and event results for tabular use.

The saved-workflow integration test exercises both Phase 6 nodes alongside the
Phase 5 review branch. It verifies the scientific artifact can export the same
report hash and refers to the original association output.

## Statistical interpretation

- Landmark PCK normalizes distance by reference box diagonal and counts missing visible
  landmarks as misses. Euclidean and normalized error are computed on localized
  visible references. Reports retain visibility and confidence summaries, occluded
  landmark error, and calibrated projected error where supplied.
- Identity scoring uses Phase 4 overlap matching and global identity assignment.
  A frame with an explicitly unscored identity is excluded from tracking metrics.
  Switch diagnostics show the frame and identifiers before and after the switch.
  With incomplete coverage the report exposes conditional identity F1 separately.
  Known frame-level identity conflicts are excluded from anatomical pairing.
- Measurements pair the same video, identity, definition, frame, and units. Error
  is prediction minus reference. Direction and body-axis error wrap at 180 degrees.
  The paired-mean versus difference plots are descriptive. Pooled repeated frames
  do not receive classical limits of agreement. See [Bland and Altman (2007)](https://www-users.york.ac.uk/~mb55/meas/bland2007.pdf).
- Event assignment maximizes one-to-one matches within both timing tolerances before
  minimizing timing error. Complete and partial cycles are scored separately.
  Ambiguous windows are excluded, and frequency uses the labeled window duration.
  An event must be contained within its declared scoring window. Censored partials
  preserve unknown boundaries. Frame classification reports instantaneous threshold
  state separately. Video navigation and missing timestamp fallback use nominal FPS,
  so precise variable-frame-rate studies need a verified timebase.
- ICC(A,1) is a two-way absolute-agreement, single-rating coefficient on complete
  video–individual–frame measurement units for the same raters. Angular data and
  undefined or unbalanced cases have no coefficient. Pairwise signed bias and event
  agreement remain descriptive. See [McGraw and Wong (1996)](https://doi.org/10.1037/1082-989x.1.1.30).
- Percentile intervals use 500 seeded bootstrap draws of top-level recording groups
  and require at least five groups. The design assumes those groups are independent.
  Frames remain nested within recordings. Five groups is a computational reporting
  minimum. A real study should justify its sample size.
- Sensitivity runs vary detection thresholds, durations, refractory periods,
  confidence, smoothing, association confidence, and gap policy on development
  data. Highest complete-event F1 wins, with the first configuration breaking ties.
  Lock one protocol before looking at held-out performance.

## Evidence and limits

The live Chromium test used a fresh local database, production API and worker, and a
synthetic 12-frame fish-gape trace with two fixture rater records. It froze the
reference in the GUI, selected a rater and original identity run, scored the model
output, opened event errors, navigated to a reference event, and verified the JSON
export. The report contained 24 localized landmarks, IDF1 of 1.0, two true-positive
complete cycles, zero false positives or misses, zero measurement bias, and fixture
ICC(A,1) of 1.0. The persisted job was `b0ac5c44-67a5-4fd4-861f-4866d7d15f29` and its
report hash was `d4140f5bfda3f966444dde6aa9fe81d20c9ee8fede436016828f4e7cd504db0b`.

Three opt-in upstream integration checks passed on an RTX 3090 with PyTorch
`2.11.0+cu128` and CUDA 12.8. These covered native evaluation, asynchronous
comparison, and CUDA workflow training through checkpoint registration and
inference. Phase 6 reference scoring runs on CPU.

The repository and local application database supplied no independently annotated
biological study data. Synthetic engineering fixtures are the available evidence.
Real-data accuracy, empirical human agreement, and external training leakage remain
research questions. Physical values are calibrated projections from single-view footage.
Sensitivity evaluates available traces with alternate gap and confidence policies. It
does not inject simulated occlusions into real traces.
Use verified model and recording provenance, independent annotations, and a registered
analysis protocol before a publication pilot.
