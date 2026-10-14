# ReefVision 1.0.1 release candidate

This patch retains the existing 1.0.0 release and tag. It targets training
lifecycle and restart reliability, Windows provider execution, training UI
refresh, editable polygon Fill, desktop sleep/resume recovery, isolated video
tracking and annotated-video exports, project interoperability visibility, and
background-job cancellation and recovery hardening.

## Annotation intelligence and verified learning

Shift+1 now proposes objects across the full source image. ReefVision uses an
explicitly promoted detector when available and falls back to bounded SAM point
grids with overlapping tiles when no active detector exists. Proposals retain
source-pixel masks, provenance and review state, and are deduplicated against
other proposals and verified objects. They remain outside scientific counts and
training data until a researcher accepts them.

Shift+2 refines exactly one selected saved mask from its original geometry. The
preview preserves the original until Accept & Replace, retains the mask identity
and revision history, and rejects stale or topology-losing replacements.
Pending raster proposals can be painted or erased with undo/redo before atomic
acceptance. SAM box prompting remains available separately.

The Improve Predictions workflow reports verified-data readiness, creates
immutable group-safe dataset snapshots, queues the existing local trainer, and
registers completed checkpoints as candidates. Detector candidates are evaluated
on held-out groups with class-aware AP50, precision, recall, count bias and mean
absolute error. A candidate is never activated automatically: promotion and
rollback are explicit audited actions, and evaluation-only outputs cannot enter
the annotation review queue. Arbitrary raster holes remain an explicit blocker
for the polygon-only instance-segmentation training path.

## Training recovery

Interrupted Ultralytics detection runs are never automatically requeued. Pending
cancellation becomes Cancelled. A complete results CSV covering every configured
epoch, finite final metrics and an intact PyTorch checkpoint ZIP can establish
Completed even if the final database transaction never happened. Recovery reads
existing artifacts and atomically finalizes the job/run/experiment; repeated
restarts do not duplicate experiments or modify artifacts. Already completed
runs remain completed. Incomplete or unverifiable runs become Failed with an
interruption message and retain all files.

ZIP validation checks container structure and CRCs without unpickling. It does
not certify model quality. Tuning, segmentation and other provider output
formats are not inferred to be complete using detection's CSV format; interrupted
runs in those paths remain conservatively failed/cancelled. Early-stopped runs
that returned normally still finalize normally; after a crash, fewer than the
configured epochs does not prove completion.

Pinned Ultralytics 8.3.228's extra post-validation epoch callback cannot increment
progress or write duplicate final metrics. Windows keeps `workers=0`. The API
and PyInstaller sidecar intentionally use Matplotlib Agg because they have no
interactive GUI event loop. Production logs retain launch, final validation,
artifact collection, completion/cancellation/failure and recovery events.

## Polygon Fill

Choose a class, choose Fill in the polygon workspace, adjust tolerance (0–255),
and click inside the source image. The connected region becomes a normal polygon
that supports vertex editing, class changes, undo/redo, deletion, save, reopen
and existing dataset/export workflows. Brush remains accessible from the same
toolbar. No SAM installation or model download is required.

Fill uses four-connected RGB distance from the seed color. It traces exact pixel
edges and removes collinear vertices only. Polygon Fill rejects holes, boundaries
that touch themselves, and outlines over 4096 simplified vertices; adjust the
tolerance or use Brush for those regions. It does not silently fill holes or
change the polygon data model. Conversion from a binary region to a polygon is
reusable by future segmentation providers.

## Desktop, video and background-job reliability

The Windows desktop shell detects wake, visibility restoration, focus recovery
and BFCache restoration, then repaints the WebView, verifies backend health and
refetches active state without unconditionally reloading the application.

Video tracking runs execute in isolated child processes so long-running OpenCV
and model work does not block the API. Tracking exposes persisted frame progress,
heartbeat state, cancellation and retry. Atomic queued-job claims prevent two
worker loops from launching the same isolated tracking or annotated-export job.

Succeeded tracking runs can generate Clean Tracking or Full Review MP4 exports
from persisted observations without rerunning detector inference. Class-colored
boxes and trails are retained while labels use a light background with black text
for readability.

Startup recovery does not silently resurrect cancellation requests. Generic
`cancel_requested` jobs are finalized as cancelled, while recoverable interrupted
running jobs are requeued according to their lifecycle policy. Quality-control,
backup and workflow companion records are kept synchronized. Running jobs only
accept generic cancellation when their processor implements cooperative
cancellation.

## Project interoperability

The existing project interoperability workspace is now exposed directly in the
project navigation. ReefVision can create versioned, checksummed project-exchange
ZIP packages, inspect them before import and import them as new managed projects
with identifier remapping. Inclusion of original media, model weights and
generated artifacts remains explicit.

## Reproduce acceptance

Use a new output directory on every run; the harness refuses an existing one:

```powershell
Set-Location C:\Users\rafae\Documents\ReefVision\reefvision
$AcceptanceOutput = Join-Path $env:TEMP ("rv101-" + (git rev-parse --short HEAD) + "-" + [guid]::NewGuid().ToString("N").Substring(0,8))
.\.venv\Scripts\python.exe scripts\acceptance_training_lifecycle.py --output $AcceptanceOutput
```

It creates four synthetic images in isolated managed storage, executes real
YOLO11 Nano CPU FP32 and CUDA FP32/AMP runs, cancels/interrupts additional runs,
and exits a child process just before committing a real 50/50 run. Recovery and
a new application instance verify durable state and unchanged artifact hashes.
This validates execution mechanics, not accuracy on research data.

After all source checks pass, build in a separate directory so prior MSI/CAB
artifacts remain untouched:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\build-desktop.ps1 -CargoTargetDirectory C:\Users\rafae\Documents\ReefVision\reefvision\.desktop\target-1.0.1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\finalize-release-artifacts.ps1 -InstallerDirectory C:\Users\rafae\Documents\ReefVision\reefvision\.desktop\target-1.0.1\x86_64-pc-windows-msvc\release\bundle\msi
```

Run full installation lifecycle acceptance on a **disposable Windows VM** after
copying the repository/harness plus the MSI and every adjacent `rv*.cab`:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\acceptance-windows-clean-install.ps1 -InstallerPath C:\ReefVisionRC\ReefVision_1.0.1_x64_en-US.msi -AcceptanceRoot C:\ReefVisionAcceptance -DisposableTest -KeepArtifacts
```

The existing harness covers install, first launch, restart, persistence,
uninstall and retained data. Also reinstall the same candidate and verify retained
project/training states, close/reopen, and absence of stale registration. Verify
upgrade from 1.0.0 only in a disposable environment; an older installer must
explicitly support isolated acceptance before passing it to this harness.

Do not tag `v1.0.1` until the exact candidate and all required artifact/hardware/VM
acceptance are recorded as passed. The generated release report records actual
results and any remaining acceptance work.
