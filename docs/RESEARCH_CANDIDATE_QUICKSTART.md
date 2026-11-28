# First project in the ReefVision 2.0 research candidate

The 2.0 candidate is a development build. Use an isolated project or a verified backup when evaluating it. The public Windows downloader selects published releases. A candidate installer can have a different set of cabinets from another build bearing the same version number.

## Launch

From the checkout root on Windows, run the bootstrap once in a development environment with Python 3.12, Node.js 22 and the supported Rust/MSVC desktop toolchain. Start the desktop shell with the second command.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev-desktop.ps1
```

The development shell starts the frontend and backend and uses the checkout's isolated desktop data directory. For a qualified installed copy, launch **ReefVision** from Start. Its desktop shell starts the packaged backend. When using an authorized candidate installer, verify the MSI and every external CAB against the manifest for that build and keep them in one directory. The packaging guide covers WebView2, missing resources, dependency checks and startup diagnostics. [Development setup](DEVELOPMENT.md) · [Windows packaging and troubleshooting](DESKTOP_BUILD_AND_INSTALL.md)

## Choose a research workflow

| Task | First steps and further instructions |
| --- | --- |
| Import a detector and improve it | Create a project, define its classes and group related images. Open **Models & AI → Model Hub → Register Existing Model**, select the Ultralytics detector and choose a trusted local `best.pt`. Verify the class bindings and retain the checkpoint digest. Generate proposals in the gallery before creating a model-filtered acquisition round. [Multi-round detector tutorial](DETECTOR_ACTIVE_LEARNING.md) |
| Detect small objects in large images | In **Images & annotation**, select images and a detector. Open the advanced tiling controls, specify the tile dimensions and overlap, and review detections on the full source image. [Rectangular tiling settings and limitations](research/TILED_DETECTION.md) |
| Review images and train | Correct geometry and reject false positives, mark the image reviewed, then complete its queue item. Freeze a reviewed dataset with independently assigned groups. The training draft records the seed model, dataset and settings. Inspect the run and register the chosen detector checkpoint explicitly. [Queue guide](REVIEW_QUEUE_GUIDE.md) · [Training and comparison steps](DETECTOR_ACTIVE_LEARNING.md) |
| Measure a mask | Review the source mask, open its skeleton analysis, inspect branches and junctions, then save the reviewed result before export. Total linear extension sums node-to-node centerlines. Record image-plane calibration for physical units and keep the raw mask, graph and scale evidence with the result. [Skeletonization methods](SKELETONIZATION_METHODS.md) |
| Study pose and behavior | Define named landmarks and edges for the animal, specify visibility, review tracks and freeze independent recordings or animals. Train through the native ReefPose workflow, review identities and landmark proposals on video, and retain the schema revision and evaluation reference. Inspect landmark error, coverage and event counts separately. [Native pose workflows](REEFVISION_1_2_REEFPOSE_INTEGRATION.md) · [Behavioral validation](reefpose/phase6-validation.md) |
| Reuse a workflow | Open **Video & automation → Workflow builder**, start from a supported template, select project-owned inputs, and save the revision. Run it, resolve any review gate and inspect each output. Reopen the saved revision to repeat the operation with recorded settings. [Workflow node types and review gates](PHASE_10_WORKFLOW_GRAPH_FOUNDATION.md) |
| Work with environmental observations | Use **Data & annotation → Environmental Context**. Inspect units, UTC timestamps, location, provider and method. Choose the saved cache when working offline. Keep estimated currents, observed temperatures and biological measurements distinguishable in exports. [Environmental context](SCIENTIFIC_ENVIRONMENTAL_CONTEXT.md) |

## Compatibility and scientific interpretation

The Windows source provider pins cover PyTorch 2.5.1 with CUDA 12.1 and Ultralytics 8.3.228. Manual annotation works without model weights. Model Hub shows providers available in the running installation. Use a compatible Ultralytics checkpoint for detector training or a matching native ReefPose checkpoint and anatomy schema for pose. General ONNX import, execution and training have no qualified workflow in this candidate. Optional providers can require separately provisioned assets. [Provider setup](DEVELOPMENT.md)

Use the detector validation set for development decisions and reserve an independent test set for final evaluation. Give repeated views, crops and frames from the same biological unit a common group key. Review possible near duplicates and unknown training provenance before making a performance claim. A successful run or a comparison on generated images establishes a software result. Field claims require independent biological observations, appropriate spatial or temporal calibration, and researcher review. [Scientific release gates](research/track-c-scientific-release-gates.md)
