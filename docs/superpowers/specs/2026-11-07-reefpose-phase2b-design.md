# ReefPose Phase 2B GUI Design

## Intent

Expose the completed native ReefPose training path through ReefVision's existing Workflow Builder, training monitors, Model Hub, and pose review workflow. A researcher should not need to edit JSON or invoke Python to train, resume, register, inspect, or use a ReefPose checkpoint.

## Goals

- Select an immutable verified pose dataset and see its exact landmark schema identity.
- Configure ReefPose or Ultralytics through typed provider-specific controls.
- Validate device/CUDA availability and compatible registered initialization models before execution.
- Show persisted run progress, losses, best-checkpoint state, cancellation, and resume actions.
- Display ReefPose anatomy, training, dataset, run, and checkpoint provenance in Model Hub.
- Hand a registered pose model to the existing Pose Tracking workspace for inference and prediction review.
- Preserve saved-workflow replay and all Phase 1/2A behavior.

## Non-goals and anti-goals

- No new trainer, dataset system, annotation system, or parallel ReefPose-only page.
- No fabricated progress values, inferred scientific accuracy, or automatic pretrained downloads.
- No lockfile churn beyond the repository's existing locked dependency installation.

## Existing architecture

- `WorkflowGraphWorkspace` already loads frozen pose datasets, saves/runs graphs, and polls run state.
- `WorkflowVisualEditor` has a generic node inspector plus a small Ultralytics pose special case.
- `TrainingRunDetail` and `ProjectTrainingMonitor` already poll canonical `TrainingRun` records and cancel active jobs.
- `ModelManager` already loads Model Hub bootstrap data and renders registered models.
- `VideoTrackingWorkspace` already performs registered pose inference and exposes machine predictions to existing review controls.

## Approaches considered

1. **Keep JSON-only configuration.** Smallest code change, but fails the GUI objective and makes provider/schema mistakes easy.
2. **Build a dedicated ReefPose training page.** Could be polished quickly, but duplicates workflow, job, dataset, and registration systems.
3. **Extend existing provider-neutral surfaces. Chosen.** Add typed pose controls and contextual data to the current node editor; enrich the existing monitors and Model Hub; route inference into Pose Tracking.

## Design

### Workflow configuration

`WorkflowGraphWorkspace` loads Model Hub bootstrap data alongside frozen pose datasets and passes both into `WorkflowVisualEditor`. The pose-training inspector owns provider-specific normalization:

- ReefPose selects `reefpose-s` and exposes epochs, batch, input width/height, learning rate, workers, precision, and device.
- Ultralytics retains YOLO11 pose architecture selection and `imgsz` configuration.
- Switching providers preserves common values while replacing incompatible architecture/configuration defaults.
- Registered initialization requires an explicit connected `registered_model_source`; its dropdown shows only provider-, task-, and landmark-schema-compatible models.
- Dataset cards show schema revision and content hash. Validation dataset/schema mismatches are visible before planning and remain backend-rejected.

### CUDA status

Runtime status gains explicit `cuda_available` and `cuda_device_name` fields for PyTorch. The UI distinguishes runtime capability from live CUDA availability and blocks an explicit CUDA selection when unavailable.

### Progress and recovery

Existing polling remains authoritative. ReefPose metric names are included in preferred loss rendering. Active runs can be cancelled. Failed/cancelled ReefPose runs expose Resume only when the backend persisted a resume checkpoint; resume invokes the existing job retry contract and refetches canonical run state.

### Model Hub and inference handoff

Registered ReefPose cards render provider/architecture, keypoint count, schema name/revision/hash, training and dataset IDs/checksums, configuration, metrics, and checkpoint checksum/size. The backend registration snapshot adds schema name and training configuration fields. “Use in Pose Tracking” switches to the existing video workspace and selects the registered model; inference and review remain existing systems.

## Validation

- Component tests cover provider switching, configuration validation, CUDA state, schema-compatible initialization, progress, cancellation/resume, Model Hub metadata, inference handoff, saved workflow execution, and Ultralytics compatibility.
- Backend tests cover runtime status serialization and registration metadata.
- TypeScript, Prettier, Vitest, production build, focused backend tests, and Playwright are run.
- Actual GUI acceptance uses the local API and browser against synthetic engineering data. Scientific accuracy remains unvalidated.

