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

## Reviewed scientific workflows

- In the mask editor, select a reviewed mask and load its saved skeleton. **Coral graph review** links the graph to a registered colony and a UTC observation time. Accept or reject source and graphical edits. Each saved revision carries branch and junction UUIDs, provenance, and any unresolved gaps.
- In Workflow Builder, connect **Verified Masks** or **Mask Review** to **Extract Coral Branch Candidates** with one verified colony mask. The node uses the same skeletonization as the mask editor and saves the calibrated image-plane lengths and source checksums. Open the saved skeleton in the mask editor for scientific review.
- In **Organisms & ecology → Coral branch growth**, select the two reviewed graphs. Account for every edge in the correspondence, then save the reviewed correspondence and calculate growth. The total is the sum of unique projected edges. Unresolved matches suppress total change. Pixel-only or incomplete graphs cannot produce calibrated growth. The workflow node uses the same current correspondence and returns the same hashed result.
- In **Pose measurements**, select an organism and confirm a scoped ReefPose identity link. A link can include already-reviewed measurement or event evidence. The link inspector shows freshness, allows correction and unlinking, and opens the relevant recording and frame.
- **Reviewed analyses** saves investigator-confirmed growth or abundance selections, projections, source checksums and exclusions. Raw counts and density are distinct. Density requires reviewed surveyed area. Use **Recalculate Reviewed Ecological Analysis** in Workflow Builder to replay a current saved selection.
- **Project exchange** has a 1.2 record inventory for integrated scientific history, snapshots, and Workflow Builder records. Import creates a separate project; unavailable source media or checkpoints are disclosed. Backups preserve the full managed local data directory.

The calibrated methods describe image-plane projections. Scientific acceptance still requires representative image and video data, a compatible local checkpoint, independent review of metrics and correspondences, and trained-model performance criteria. A graphical gap review can retain an unresolved or separate-colony candidate, which remains ineligible for growth.

## Data compatibility

The active Alembic head is `b12_integrated_0002`, a forward migration from `b12_integrated_0001` for reviewed coral graphs and correspondence, paired growth, reviewed ecological analyses, and reviewed pose links. The existing 1.1 science line and 1.2 ecology line keep their migration files. The seven copied ReefPose migrations use `reefpose_0038` through `reefpose_0044` with the standalone DDL. Online upgrades inspect the database schema before mapping a reused numeric revision, and the mapping and schema update share one transaction. Ambiguous or incomplete legacy schemas fail closed. Run upgrades against a verified disposable copy before moving any research data. Keep the original database and backup separately.

Project ZIP exchange remaps local record IDs. Immutable snapshots retain their source evidence and hashes with explicit local mappings. The inspect and import results disclose unavailable assets. Use a verified backup for complete local preservation. The integrated restore test compares scientific records, ecological identity revisions, ReefPose references and held-out locks across source, backup and restored SQLite copies.

For an interrupted held-out job, open **ReefPose scientific validation**, select the run under **Validation runs**, and choose **Retry saved validation**. The new job uses the saved reference revision, rater, development report, and prediction sources. Its input checksum and every held-out lock must match. The interrupted run remains in history. An export of the original project carries a verified manifest when the saved evidence can be reconstructed. If you opened a legacy exchange that contained only an opaque lock, retry in the original project or restore its verified backup and export again. For biological retries, include the original recordings in the new exchange or relink those exact files before retrying. Workflow-owned validations are retried from their workflow run.

## Verification

- Synthetic Chromium drove the native ReefPose training, anatomy, model comparison, multi-animal identity correction, movement review and reference validation workflows. Native training and held-out comparison used the RTX 3090; separate GPU integration tests exercised train/register/infer and evaluation.
- A live ecology run linked two dated observations to one organism. Calibrated source geometry produced four candidate measurements and a 2.5 mm projected width change over one day. The CSV and executed Workflow Builder artifact preserved provisional evidence.
- A live connected branch preview split an interior segment and measured the added segment as 4 px and 1 mm, with the saved skeleton unchanged.
- A disposable Windows Python 3.12.10 environment passed the official provider preflight with Ultralytics 8.3.228, PyTorch 2.5.1+cu121, torchvision 0.20.1+cu121, and OpenCV contrib 4.12.0.88. The registered local synthetic segmentation checkpoint `32e14eadcc70eae474c4d391fe972dca50df7fd7cebee7719d28b69d07ffec9f` produced one RTX 3090 mask proposal at 0.97574 confidence. Explicit reviews recorded a rejected edit, an accepted split from three to four edges, and an occluded gap that excludes the result from growth. At the fixture calibration of 0.25 mm/px, unique-edge length was 13.59637 mm before and after the split, within rounding. The original image checksum stayed the same. Restart and verified backup restore reopened the same graph and reproduced its CSV byte for byte.
- The development MSI at `ff19386e` passed disposable Windows clean install, WebView2 launch, restart, uninstall with retained data, and upgrade from 1.0.3. Windows Application Control previously blocked local Rust packaging with error 4551. The acceptance-fix checksum and exact-head installer results belong to the checks and artifacts on PR #85. Major workflow interaction in installed WebView2, physical display scaling, and MSI upgrade from 1.1/1.2 need a disposable host and compatible prior installers.

Before upgrade, verify a backup with the prior build and retain its installer and data profile separately. For rollback, restore that pre-upgrade backup into an empty profile and reopen it with the matching prior build. An unknown newer schema is rejected during compatibility checks. The regression fixture checks that attempting to start migration on such a database leaves its bytes unchanged.

### Representative validation package

- Coral study input requires original images with acquisition dates, colony and sampling-unit identifiers, original calibration evidence, and an independently reviewed reference for visible centerlines, junctions, branch correspondence, and gaps. Keep held-out colony groups distinct from any checkpoint training or threshold selection. Export the reviewed graph, branch lengths and growth plus checkpoint, calibration, and source-image checksums. Record missed and spurious branches, unresolved correspondences, and length error.
- Animal study input requires original videos, verified animal identities and observed windows, compatible registered checkpoints, and a frozen independent reference for landmarks, identity continuity, measurements, and event bounds. Record frame rate, window exclusions and track interruptions, and export the scored report and reviewed organism links. Preserve false detections, uncovered footage, and partial events separately.
- For growth, observed abundance, and density, supply the reviewed observation and group roster, surveyed area evidence where used, and independent review of exclusions and denominators. The available local samples did not include a demonstrated independently reviewed biological reference and compatible checkpoint. The synthetic results above document the engineering workflow.

The development build is suitable for local exploration with sample data. Synthetic tests establish engineering behavior. Representative ecological validity remains to be measured.
