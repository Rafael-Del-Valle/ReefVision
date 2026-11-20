# ReefVision 1.3 held-out human–model agreement

In **Models & AI**, open **ReefPose scientific validation** and expand **Scientific human–model comparison**. Choose a completed held-out scoring report with one registered checkpoint. An optional second report is paired on the exact same frozen reference revision, rater, configuration and upstream inference/tracker protocol. Use the same event label or anatomical measurement definition and units. Save the comparison, reopen it from the selector, and export pairs or the methods/provenance record. The saved comparison UUID configures **Publish Scientific Comparison** in Workflow Builder. This node retrieves the same report and rejects stale source evidence.

## Group provenance for frame and temporal checkpoints

From a project, open **Video & automation → Video & tracking**. Select the
source track in Pose Active Learning and enter its **Recording ID** and
**Animal ID across recordings**. Reuse the animal's identifier across other
recordings of that animal. Review the candidate pose and choose **Freeze
verified training dataset**. The frozen candidate records the declaration.
When a current reviewed organism link covers the selected track and frames,
it also records the linked revision and study assignment.

In the temporal sequence dataset, select the frame-model track, human-reviewed
supervision track and reviewed animal identity. Confirm that the tracks depict
the same animal, enter both source identifiers, and choose a partition for
each sequence. The comparison checks training and validation ancestry,
including upstream frame checkpoints. Reusing a recording or an animal across
development and test makes that source exposed. Missing declarations keep the
result exploratory. Previously stored evaluations retain their original
receipts. The saved training and evaluation graph uses the same frozen inputs.

A scratch-trained CUDA engineering fixture used two distinct test animals
and recordings. Both model lineages reported `held_out`. The frozen dataset
SHA-256 was `911e58ed4fe575d910a0cbc64ebe42c2035f9d16a99e1b573125428caaeb20b9`.
Frame and temporal estimates each scored 24 of 48 reference coordinates.
Their respective mean errors were 57.329 and 57.100 source pixels. The pair of
anatomical landmarks had zero frames with joint model support, so event
accuracy and timing were unavailable. Two independent groups supplied no
bootstrap interval. A saved graph reproduced the metrics. The fixture also
checks reused recording and animal declarations and missing grouping.
Representative measurements still require independent labels, compatible
weights and prespecified criteria. [Reproducible source fixture](../scripts/verify_reefpose_temporal_lineage_live.py),
[normal desktop grouping journey](../apps/web/tests/e2e/reefpose-lineage-grouping-live.spec.ts).

## Five held-out synthetic recordings

A separate RTX 3090 run on source `5578353c6` froze its design before
training. The scratch frame model used 96 generated training frames and a
separate 48-frame validation recording. Development used two other temporal
training recordings and a separate temporal validation recording. Five test
animals, each in its own 24-frame recording, were rendered after both models
were selected and registered. One development recording needed a reviewed
merge of fragments from the same generated individual. The scoring rule,
split and generating seeds were preserved. The frozen test dataset digest was
`1fa3a324dedbe9dcdd47671b967bd12f1742a3c60a154b0e7d8f80ddd02649ae`.

| Measurement | Frame only | Temporal |
| --- | ---: | ---: |
| Landmark coordinates scored | 240 / 240 | 240 / 240 |
| Frames with both anatomical landmarks | 120 / 120 | 120 / 120 |
| Mean landmark error | 5.575 px | 4.006 px |
| Matched / missed / extra events | 0 / 7 / 15 | 3 / 4 / 18 |
| Count error across seven complete reference events | +8 | +14 |
| Precision / recall | 0 / 0 | 0.143 / 0.429 |
| Mean absolute onset / offset error for matched events | unavailable | 0.133 / 0.133 s |
| Mean absolute duration / peak-time error | unavailable | 0.200 / 0.100 s |

Temporal refinement reduced mean landmark error by 1.570 px. The 95% paired
group-bootstrap interval for temporal minus frame error was −1.906 to −1.233 px.
The temporal model also overcounted more events. The model comparison covers
generated clips and their known coordinates. The tracked experiment repeated
the same errors and event counts from a fresh disposable directory. Run
`python scripts/verify_reefpose_known_answer_live.py <new-directory> --device cuda`
from the repository's ML development environment. Field validation remains open.
[Experiment driver](../scripts/verify_reefpose_known_answer_live.py).

## Statistical definitions

- Signed difference is model estimate minus the selected frozen human reference. Mean absolute error averages the absolute values of the paired differences. Percentage errors divide by the magnitude of a nonzero reference. Zero-reference observations contribute to raw error and are counted separately.
- Each continuous pair is keyed by recording, reference individual, definition, unit, and frame. Each event-count pair is keyed by recording, reference individual, label, and reviewed scoring-window bounds. Complete count is the total of matched plus missed human events or matched plus spurious model events. Partial events stay separate. Windows excluded by the original scoring report, missing reference values, and missing matched predictions are reported as exclusions. A two-model comparison uses common pairs and reports the second model’s absolute error minus the first model’s absolute error for each common pair.
- Two-sided 95% percentiles use 500 seeded bootstrap resamples of complete, investigator-attested independent recording groups. Within-group pairs stay together. Point estimates and intervals use the pair-level mean. At least five declared independent groups are required for interval calculation. The software records this attestation without establishing independence from the media.
- The Bland–Altman plot shows paired means and differences. The optional 95% limits use signed bias plus or minus 1.96 sample standard deviations of the differences. Enable the limits after reviewing the plot for approximately normal differences and constant variance. The result additionally requires at least three pairs from distinct independent groups, and equal-duration windows for count agreement. The limits describe expected differences for observations from the same population.
- ICC(A,1) assesses absolute agreement between the fixed human and machine methods for a single rating. ICC(C,1) assesses consistency and tolerates a fixed shift. Both use a balanced two-way ANOVA and at least three pairs from independent groups. A negative ICC is possible. Degenerate denominators produce unavailable values. Circular direction and body-axis measurements require dedicated circular agreement methods and are rejected here.
- Event counts apply to reference subjects in the declared windows. The report's unassigned tracks still contribute to the original ReefPose validation scoring where supported. The comparison is scoped to paired reference observations.

Comparison and workflow reports preserve the method, software version, reference and checkpoint hashes, exact inputs, selected ICC formulation, exclusions, and paired values. Archive import keeps the original scientific snapshot and records local ID remaps. Original values, available media, or checkpoint availability are not inferred from an archive's metadata.

The original Phase 6 inter-observer agreement view continues to show human–human reproducibility separately. One comparison against a reference is relative agreement with those annotations. A synthetic reference report is marked as engineering evidence. Supports counts of reviewed events and anatomical measurements from existing frozen ReefPose references. Caller-supplied image count comparisons remain available through the existing exploratory 1.2 endpoint.

## Method references

- [Bland and Altman, Statistical methods for assessing agreement between two methods of clinical measurement](https://doi.org/10.1016/S0140-6736(86)90837-8)
- [McGraw and Wong, Forming inferences about some intraclass correlation coefficients](https://doi.org/10.1037/1082-989X.1.1.30)
- [SciPy percentile bootstrap procedure](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html)

The analytic regression uses paired values 1, 3, 5, 7, and 9 plus a fixed method offset of 3. The subject mean square is 20, the ordinary two-method mean square is 22.5, and the residual mean square is zero. The expected ICC(A,1) is 20/29, ICC(C,1) is 1, and the agreement limits are [3, 3]. Reusing one group in that fixture suppresses inferential summaries.

