# ReefVision 1.3 scientific workflows

This development branch was created from the reviewed 1.2 integration at `ff19386e557a0b354d693ccf3aebe8fd92ef7bf5`. Its PR base is the 1.2 follow-up at `746104089b19509982c5b089ef7215b9c186b56a` from draft PR #85. The 1.3 scientific records remain local.

## Using the workflows

- **Models & AI → Model Hub → ReefPose scientific validation** opens the comparison workspace. Select completed held-out reports scored under the same protocol and frozen evidence. Count comparisons use scored biological event windows. Continuous comparisons use the paired measurement values retained by ReefPose. Select ICC(A,1) for absolute agreement or ICC(C,1) for consistency. The comparison output retains exclusions, units, checkpoint hashes, sample counts and analysis choices. See [agreement methods](REEFVISION_1_3_HELDOUT_AGREEMENT.md).
- **Models & AI → Model Hub → Static-image human–model comparison** runs compatible registered detectors on an immutable reviewed image dataset. Counting uses stable image and class IDs and retains raw detections. The report identifies images excluded or missing evidence, inference failures, unmapped detections, zero reference values, and model training or selection overlap. An imported or external checkpoint with undocumented lineage remains exploratory. Create an identity or difference figure in Research reports from the saved comparison.
- **Organisms & ecology → Identity registry** associates a reviewed study assignment with an organism revision. Physical units and fragments retain their existing lineage rules. Study metadata records the investigator's declaration and supports auditing approved changes.
- **Organisms & ecology → Event summaries** selects a reviewed pose link and a detector based on its pinned measurement series. Save comparable sessions to view rates per organism and, when fully declared, per experimental unit. Each denominator sums elapsed time between adjacent, valid, scientist-reviewed frames. Only confirmed complete events explicitly linked and contained within one valid interval contribute. Counts are observed within that effort; partial, unreviewed and excluded events are shown separately.
- **Organisms & ecology → Research reports** saves a figure from a reviewed ecological result, event summary, or held-out comparison. Export scalable SVG, numerical CSV, and a JSON record with exclusions and method provenance. Figure configurations and source hashes persist. Trajectory plots show sampled dates and observed values. Group summaries show one sample SD across declared units when it can be computed, with the number of units.
- **Growth by reviewed treatment** uses one equally weighted contribution from each eligible experimental unit. Two or more reviewed treatments must share the metric, measurement method, unit type, measured units, and UTC endpoint dates. Tank assignments require tank-level units. Results show the mean signed change and sample SD when at least two units contribute. The coverage figure distinguishes planned visits with comparable measurements from visits without usable data, with each planned denominator retained.
- **Review → Quality control** configures acquisition thresholds and produces inspectable image warnings. The measures flag images for review. An analyst must explicitly record any exclusion.

Workflow Builder offers **Publish Scientific Comparison**, **Reviewed Ecological Event Summary**, **Publish Research Figure**, **Image Acquisition Quality**, the existing ecology nodes, and four temporal ReefPose nodes for sequence preparation, training, refinement and evaluation. Connect the required ports, select **Configure**, and choose sources or saved results using the guided fields. The event summary requires a reviewer, reason, and confirmation. Advanced parameter JSON accepts the same typed parameters. Reopening a saved result checks whether its inputs have changed.

## Native temporal ReefPose

Open **Video & automation → Video & tracking → Native temporal ReefPose**. Run a registered native frame checkpoint using the existing video workflow. Freeze the frame tracks and manual supervision with the corresponding reviewed anatomy revision. Group related recordings before assigning partitions. A sequence may contain missing predictions and partial human supervision.

The residual temporal convolutional model learns a coordinate adjustment to the frame estimate. It takes normalized source coordinates, visibility and confidence, and elapsed time and missing-observation information. Causal windows end at the prediction frame. Centered windows can include future observations. The run records the actual future frames and seconds used. Chunked inference shares context across chunk boundaries and keeps both methods' predictions.

Train from a frozen dataset and inspect the registered temporal checkpoint in Model Hub. Run refinement with the recorded frame dependency. The video panel compares predictions in source pixels and lets the scientist accept, correct, or reject the selected frames. A saved review revision can feed the existing anatomical measurement and cycle-detection workflow. Identity and review revisions are tracked for staleness.

Evaluation compares shared test observations, reports coverage and localization error, anatomical distance error, stationary and rapid movement behavior, runtime, and context. The anatomical-cycle option applies the same Phase 5 hysteresis configuration to human-reviewed landmark distances and both methods. This measures agreement to derived cycles. Independent event labels and field recordings are needed for biological validation. Only sufficiently replicated groups get group-bootstrap intervals.

## Development launch

Run from this checkout in two PowerShell terminals. The commands use already installed Python and web dependencies and a disposable data path.

```powershell
$python = 'C:/AI-Projects/venvs/reefvision11-rc-dev/Scripts/python.exe'
$env:PYTHONPATH = (Resolve-Path 'apps/api').Path
$env:REEFVISION_DATA_DIR = Join-Path $env:TEMP 'reefvision-1-3-exploration'
& $python -m alembic -c apps/api/alembic.ini upgrade head
if ($LASTEXITCODE) { throw 'Database migration failed.' }
& $python -m uvicorn reefvision.main:create_app --factory --host 127.0.0.1 --port 8000
```

```powershell
npm --prefix apps/web run ui:dev -- --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173`. Use a compatible local checkpoint and the officially pinned provider stack for Ultralytics GPU inference. The native ReefPose CUDA environment is separate.

## Compatibility and scientific limits

`b13_scientific_0001` adds reviewed study metadata to the existing identity revision table. `b13_temporal_0001` adds the temporal dataset, run, and refinement-frame tables. Existing frame-only projects remain readable. Saved publications, event summaries, and comparisons reuse project-scoped job results. Backups retain the integrated database and exchange validates dependencies and evidence hashes. Restore a verified pre-upgrade backup to use the prior application with its earlier schema.

Scientific validity still requires independent evidence for representative acquisition conditions, the actual experimental units and treatments, adequate observed exposure, and an independently reviewed reference. Classical agreement limits and ICC require their declared assumptions. The 1.3 branch does not infer mortality from lack of follow-up, estimate detectability, or implement later-version experimental-design tooling.
