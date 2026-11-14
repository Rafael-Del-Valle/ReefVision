# ReefVision 1.3 scientific workflows

This development branch builds on the reviewed 1.2 integration at `ff19386e557a0b354d693ccf3aebe8fd92ef7bf5`. It depends on draft PR #85, whose follow-up preserves recovery of verifiable interrupted held-out jobs. The 1.3 scientific records remain local.

## Using the workflows

- **Models & AI → Model Hub → ReefPose scientific validation** opens the comparison workspace. Select completed held-out reports scored under the same protocol and frozen evidence. Count comparisons use scored biological event windows. Continuous comparisons use the paired measurement values retained by ReefPose. Select ICC(A,1) for absolute agreement or ICC(C,1) for consistency. The comparison output retains exclusions, units, checkpoint hashes, sample counts and analysis choices. See [agreement methods](REEFVISION_1_3_HELDOUT_AGREEMENT.md).
- **Organisms & ecology → Identity registry** associates a reviewed study assignment with an organism revision. Physical units and fragments retain their existing lineage rules. Study metadata records the investigator's declaration and supports auditing approved changes.
- **Organisms & ecology → Event summaries** selects a reviewed pose link and a detector based on its pinned measurement series. Save comparable sessions to view rates per organism and, when fully declared, per experimental unit. Each denominator sums elapsed time between adjacent, valid, scientist-reviewed frames. Only confirmed complete events explicitly linked and contained within one valid interval contribute. Counts are observed within that effort; partial, unreviewed and excluded events are shown separately.
- **Organisms & ecology → Research reports** saves a figure from a reviewed ecological result, event summary, or held-out comparison. Export scalable SVG, numerical CSV, and a JSON record with exclusions and method provenance. Figure configurations and source hashes persist. Trajectory plots show sampled dates and observed values. Group summaries show one sample SD across declared units when it can be computed, with the number of units.
- **Review → Quality control** configures acquisition thresholds and produces inspectable image warnings. The measures flag images for review. An analyst must explicitly record any exclusion.

Workflow Builder offers **Publish Scientific Comparison**, **Reviewed Ecological Event Summary**, **Publish Research Figure**, **Image Acquisition Quality**, and the existing **Ecology Identity Registry** and **Recalculate Reviewed Ecological Analysis** nodes. Review and save the appropriate source when required, then connect the current project and select the saved record in node parameters. Reopening a saved result checks whether the sources have changed. Imported historical snapshots retain original evidence hashes and provide local mappings.

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

`b13_scientific_0001` adds reviewed study metadata to the existing identity revision table. 1.2-era identities remain readable with no study assignment. Saved publications, event summaries, and comparison artifacts reuse project-scoped persisted job results. Backups retain the integrated database and exchange validates dependencies and evidence hashes before commit. Restore a verified pre-upgrade backup to use the prior application with its earlier schema.

Scientific validity still requires independent evidence for representative acquisition conditions, the actual experimental units and treatments, adequate observed exposure, and an independently reviewed reference. Classical agreement limits and ICC require their declared assumptions. The 1.3 branch does not infer mortality from lack of follow-up, estimate detectability, or implement later-version experimental-design tooling.
