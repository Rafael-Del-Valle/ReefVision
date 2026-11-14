# ReefVision 1.3 release condition: ReefPose temporal cycle analysis

## Training data available through the API

Freeze independently annotated cycle intervals in the existing ReefPose reference
workflow. Supply the complete reviewed time windows for the selected rater,
individual, and label, including windows with zero events. Mark ambiguous spans
as ambiguous events, or individual frames as ambiguous or missing. Create pose
measurement runs for the corresponding videos and identities. For a ventilation
pilot, choose two channels such as jaw gape and gill-cover displacement relative
to the head.

In the local API docs, use
`POST /api/v1/projects/{project_id}/reefpose-references/{reference_id}/temporal-training-data`
with the following fields:

- `rater_id` and `label` from the frozen reference.
- Ordered `feature_ids` from the measurement run definitions.
- One or more `clips`, each with a `measurement_run_id`, `animal_identity_id`
  and `reference_individual_id`. The caller explicitly matches track identity
  to reference identity after reviewing the source video.

Save the returned JSON with its SHA-256. It includes source video and anatomy
hashes, recording groups, rater and measurement provenance, channel units,
original event boundaries, and per-frame feature values and confidence.
Only development recordings are exportable here. Use recording groups to
partition development clips for fitting and model selection, and keep test
recordings reserved for independent scoring.

Windows and events use half-open intervals. Within a reviewed window, target
`1` means inside a scored complete event, `0` means outside an event, and
`null` masks partial or ambiguous events, explicitly uncertain reference
frames, and frames without any usable features. Missing channels are null;
zeros are valid. The original event intervals distinguish adjacent cycles even when their binary frame
labels touch. An annotated event with no valid samples remains an event in
the reference and should be reported as unobservable. Original frame numbers and times preserve gaps where all
channels lack a sample. The temporal trainer must split by window, honor time
gaps, and carry missingness into the model inputs. This API builds the data
package. It does not train a checkpoint.

## Required before shipping 1.3

- [ ] A researcher can mark, revise, and freeze cycle start/end times in the
  video interface, including zero-event windows and unobservable intervals.
  Event-only labeling works without per-frame landmark labels.
- [ ] A local training job can consume the frozen dataset and train a temporal
  baseline such as a small TCN over saved pose-derived features. It supports
  separate channel masks, group-disjoint training and model selection, and
  records the dataset hash, feature layout, preprocessing, and checkpoint
  provenance. It can use a fixed ReefPose-S checkpoint. Verify the training
  and selection lineage of both checkpoints against held-out fish or groups.
  Use event boundaries as supervision so adjacent cycles remain distinct.
- [ ] A registered temporal checkpoint runs on new recordings in ReefVision.
  It produces reviewable cycle proposals and explicitly distinguishes
  unobservable intervals from observed periods with zero cycles. Save,
  reopen, correct and export cycle results through the existing review flow.
- [ ] Demonstrate the complete workflow on an installed build with a fixture.
  Independently score representative biological recordings held out by fish
  or recording group. Compare the existing rule-based detector and the
  temporal model at comparable coverage, reporting false and missed events,
  timing error, and unscored footage. Include one-channel and two-channel
  runs to quantify the contribution of each anatomical signal.
