# Ordinary detector acceptance

This opt-in Playwright test creates a project in a disposable ReefVision profile. It imports six generated 96×96 PNGs, saves three two-image groups in the Gallery, and supplies the known fixture boxes through the annotation API. It verifies that the browser freezes four train and two validation images without splitting a group. The test trains YOLO11n from the local architecture YAML for one epoch on CPU in FP32 and registers the resulting checkpoint.

The browser runs the registered detector on a separate generated still and the tracked synthetic 12-frame clip. It edits an initially pending proposal, explicitly accepts it, and checks the reviewed revision after reopening. It also downloads the clip’s machine-generated track JSON and the unchanged six-image YOLO dataset ZIP, checking their source and export digests. All fixture media are synthetic. Validation metrics describe this fixture run only.

## Source browser

Use a new scratch directory and a Python environment with the repository’s dev dependencies already installed, including the local detector runtime. Install the web dependencies and Playwright Chromium before running the offline exercise. Run the API and web UI in separate PowerShell sessions.

From the repository root, with the test Python environment activated:

```powershell
$rvScratch = Join-Path ([IO.Path]::GetTempPath()) ("rv-detector-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$env:REEFVISION_DATA_DIR = $rvScratch
$env:REEFVISION_ENV = "test"
$env:REEFVISION_BACKGROUND_WORKER_ENABLED = "true"
$env:PYTHONPATH = (Resolve-Path apps/api).Path
$env:CUDA_VISIBLE_DEVICES = "-1"
$env:YOLO_AUTOINSTALL = "false"
$env:YOLO_OFFLINE = "true"
python -c "from reefvision.config import Settings; from reefvision.desktop import run_pending_migrations; s = Settings(); s.ensure_directories(); run_pending_migrations(s)"
if ($LASTEXITCODE -ne 0) { throw "Disposable profile migration failed." }
python -m uvicorn reefvision.main:app --host 127.0.0.1 --port 18749
```

From `apps/web`, start the UI:

```powershell
$env:VITE_API_BASE_URL = "http://127.0.0.1:18749/api/v1"
npm run ui:dev -- --host 127.0.0.1 --port 18750 --strictPort
```

From `apps/web` after both servers are ready:

```powershell
$env:REEFVISION_ORDINARY_DETECTOR_ACCEPTANCE = "1"
$env:REEFVISION_GUIDED_TEST_API = "http://127.0.0.1:18749/api/v1"
$env:REEFVISION_GUIDED_TEST_WEB = "http://127.0.0.1:18750"
node node_modules/@playwright/test/cli.js test tests/e2e/ordinary-detector-live.spec.ts --workers=1 --retries=0
```

## Packaged Windows desktop

Use the disposable installed Windows acceptance environment and its existing WebView2 debug launcher. Set `REEFVISION_ORDINARY_DETECTOR_ACCEPTANCE=1`, set `REEFVISION_GUIDED_TEST_API` to the packaged sidecar’s isolated loopback API, and set `REEFVISION_SPATIAL_WEBVIEW2_ENDPOINT` to the launcher’s loopback CDP browser URL. Run the same Playwright command from `apps/web`. The fixture connects to the running Tauri window and verifies the Tauri runtime. Keep the deployment and training device on CPU. The test requires the bundled detector runtime and local architecture YAML. It starts training from scratch and needs no model-weight acquisition.

Playwright writes `ordinary-detector-evidence.json`, a reviewed-still screenshot, and the synthetic exports to its results directory. The trained checkpoint stays in the disposable app profile. Record the exact source or package SHA, package run identity, test surface and elapsed time beside the evidence when using this result for acceptance. Run this one journey serially. Runs without the opt-in variable skip it.
