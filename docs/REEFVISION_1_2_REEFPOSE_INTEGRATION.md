# ReefVision 1.2 and native ReefPose development build

This draft combines the existing Phase 1–6 ReefPose implementation, 1.1 scientific workspace and GUI work, and the 1.2 ecological analysis branch. The standalone ReefPose source is preserved at `091a77f8822e4e9c43b13df916d38576a16ae802`. Review [draft PR #85](https://github.com/Rafael-Del-Valle/ReefVision/pull/85) alongside the [1.2 roadmap](roadmap/REEFVISION_1_2.md) and [connected branch specification](roadmap/REEFVISION_1_2_CONNECTED_BRANCH_MEASUREMENTS.md).

## Launch

These commands use an existing Python environment with the project dependencies and an existing locked web dependency install. Use a PyTorch environment with CUDA to run native training on the GPU. Manual annotation and the ecology workflows can run without a checkpoint. Native inference requires a local compatible checkpoint and matching schema revision. These commands do not fetch model weights.

Run from the integration checkout in two PowerShell terminals.

**API**

```powershell
$python = 'C:/AI-Projects/venvs/reefpose-phase2a-verification/Scripts/python.exe'
$env:PYTHONPATH = (Resolve-Path 'apps/api').Path
$env:REEFVISION_DATA_DIR = Join-Path $env:TEMP 'reefvision-1-2-exploration'
& $python -m alembic -c apps/api/alembic.ini upgrade head
if ($LASTEXITCODE) { throw 'ReefVision migration failed.' }
& $python -m uvicorn reefvision.main:create_app --factory --host 127.0.0.1 --port 8000
```

**Frontend**

```powershell
npm --prefix apps/web run ui:dev -- --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173`. Use **Organisms & ecology** for identity, source image and calibration links, longitudinal candidates, and the source videos behind pose measurements. Use **Workflow Builder → Ecology observations and calibrated candidates** for persisted typed outputs and CSVs. The connected branch preview is in the mask editor's saved skeleton analysis. Its draft uses exact source-pixel attachment and keeps results separate from reviewed skeleton records.

## Status against the 1.2 roadmap

| Area | Development behavior verified | Remaining |
| --- | --- | --- |
| Repeated organisms | Identity revisions, explicit links to reviewed human geometry, pinned calibration and EXIF time evidence, revision history | A scientific identity adjudication workflow and verified longitudinal observation promotion |
| Connected branches | Graphical preview and undo/redo, exact attachment and splitting, unique-edge pixel and supported 2D physical lengths, stale calibration guards, typed workflow output | Saved reviewed segment identities and revision/supersession, gap disposition, persistent graph edit operations, reviewed per-branch exchange/export and across-date correspondence |
| Growth and population | Exploratory longitudinal and paired-count workflows, projected geometry comparisons using UTC and calibration, declared-unit summaries and QC CSVs | Authenticated abundance sampling, verified growth and replication, validated longitudinal branch comparisons and publication figures |
| ReefPose | Native training and registration, stable anatomy, video pose, identity correction, measurement and event review, held-out validation and comparison, exports, typed workflows, navigation from ecology back to the source video | Reviewed cross-date links between pose identities/results and ecological organism records and representative validation |
| Recovery and exchange | Fresh schema and old-version upgrades, backup and restore of integrated rows, existing portable pose datasets and selected scientific records | Full-fidelity exchange of ecological identity, native association, measurement, event and reference records, legacy standalone backup-envelope restore, and installed upgrade/rollback |
| Release | Local browser and RTX 3090 engineering runs on synthetic fixtures | Representative data, independent scientific review, exact-head GitHub gates, MSI and installed WebView2 acceptance |

## Data compatibility

The active Alembic head is `b12_integrated_0001`. The existing 1.1 science line and 1.2 ecology line keep their migration files. The seven copied ReefPose migrations use `reefpose_0038` through `reefpose_0044` with the standalone DDL. Online upgrades inspect the database schema before mapping a reused numeric revision, and the mapping and schema update share one transaction. Ambiguous or incomplete legacy schemas fail closed. Run upgrades against a verified disposable copy before moving any research data. Keep the original database and backup separately.

Project ZIP exchange remaps record IDs. The inspect and import results disclose omitted integrated research sections. Use a verified backup for complete local preservation. The integrated restore test compares scientific records, ecological identity revisions, ReefPose references and held-out locks across source, backup and restored SQLite copies.

## Verification

- Synthetic Chromium drove the native ReefPose training, anatomy, model comparison, multi-animal identity correction, movement review and reference validation workflows. Native training and held-out comparison used the RTX 3090; separate GPU integration tests exercised train/register/infer and evaluation.
- A live ecology run linked two dated observations to one organism. Calibrated source geometry produced four candidate measurements and a 2.5 mm projected width change over one day. The CSV and executed Workflow Builder artifact preserved provisional evidence.
- A live connected branch preview split an interior segment and measured the added segment as 4 px and 1 mm, with the saved skeleton unchanged.
- Windows Application Control blocked a Rust build-script executable locally (error 4551). Local Chromium exercises the frontend and backend. Current MSI and installed WebView2 acceptance are still release gates.

The development build is suitable for local exploration with sample data. Synthetic tests establish engineering behavior. Representative ecological validity remains to be measured.
