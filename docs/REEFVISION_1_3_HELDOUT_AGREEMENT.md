# ReefVision 1.3 held-out human–model agreement

In **Models & AI**, open **ReefPose scientific validation** and expand **Scientific human–model comparison**. Choose a completed held-out scoring report with one registered checkpoint. An optional second report is paired on the exact same frozen reference revision, rater, configuration and upstream inference/tracker protocol. Use the same event label or anatomical measurement definition and units. Save the comparison, reopen it from the selector, and export pairs or the methods/provenance record. The saved comparison UUID configures **Publish Scientific Comparison** in Workflow Builder. This node retrieves the same report and rejects stale source evidence.

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

