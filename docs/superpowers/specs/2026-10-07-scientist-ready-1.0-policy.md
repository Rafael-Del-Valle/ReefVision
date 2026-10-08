You are continuing ReefVision Scientist-Ready 1.0 from the current validated repository state.

Repository:
C:\Users\rafae\Documents\ReefVision\reefvision

Branch:
feat/scientist-ready-phase12-ui-redesign-20261005

Validated starting commit:
8e4be364b70d50fa9f9a17587c04e758b64f0134

======================================================================
CRITICAL PRODUCT DECISION — READ FIRST
======================================================================

REEFVISION 1.0 MUST NOT SHIP, AUTO-DOWNLOAD, OR DEPEND ON PRETRAINED MODEL WEIGHTS.

This is now a deliberate product policy.

ReefVision is a scientific computer-vision platform intended for researchers working with organisms, structures, habitats, and imaging domains that often differ substantially from standard pretrained datasets.

Generic pretrained checkpoints — especially human- or consumer-dataset-biased weights — waste installer/cache space and may create misleading expectations for scientific users.

Therefore ReefVision 1.0 is now:

ARCHITECTURE-FIRST + TRAIN-YOUR-OWN + REGISTER-YOUR-OWN MODEL.

Users must either:

1. select a supported architecture and train a new model from scratch using their own scientist-verified ReefVision data, OR

2. register/import a trained model they already possess.

No pretrained weights should be bundled with ReefVision.

No pretrained weights should be automatically downloaded when an architecture is selected.

No background model-weight download should occur during training or inference.

No model should silently fall back to pretrained weights.

No provider should trigger an upstream framework's automatic checkpoint download.

Architecture/configuration files are acceptable because they are not trained weights and are small.

Examples:
- yolo11n.yaml: allowed
- yolo11n-pose.yaml: allowed
- yolo11n-seg.yaml: allowed
- yolo11n.pt: NOT bundled or automatically downloaded
- yolo11n-pose.pt: NOT bundled or automatically downloaded
- yolo11n-seg.pt: NOT bundled or automatically downloaded

The same policy applies to all model families.

If a feature requires pretrained weights and ReefVision cannot train that architecture from scratch, the feature must require the researcher to explicitly register/provide compatible weights.

Do not download those weights for them automatically.

======================================================================
CURRENT VALIDATED STATE
======================================================================

Batch 5 backend type hardening is COMPLETE.

Do not redo it.

Current state:
- backend Ruff clean
- backend mypy: 0 errors
- full backend regression previously passed
- production mypy errors: 0
- current Batch 5 commit is pushed
- Phase 12 branch remains the release-working branch

Do not reopen completed typing work unless later changes create a legitimate regression.

The remaining ReefVision 1.0 work is release closeout.

======================================================================
PRIMARY OBJECTIVE
======================================================================

Finish ReefVision Scientist-Ready 1.0 completely.

The remaining release work consists of:

1. Verify and preserve the completed backend/type-hardening checkpoint.
2. Finish Phase 12 native desktop/UI acceptance.
3. Convert the Model Catalog and training system to the final architecture-first/no-pretrained-weights policy.
4. Ensure users can train supported architectures from scratch and register their own trained models.
5. Normalize the public release version to ReefVision 1.0.0.
6. Build and validate the final Windows installer.
7. Perform clean-install/release smoke testing.
8. Finish release documentation and acceptance reporting.
9. Commit and push the complete release-ready state.
10. Tag v1.0.0 only when all acceptance criteria pass.

Do not add ReefVision 1.1 features.

Explicitly exclude:
- Copernicus/NOAA environmental current integration
- NullSchool-style current visualizer
- spawning-environment analysis
- environmental GIS overlays
- future current-relative animal-speed work
- workflow calculation/formula nodes
- general annotation/model disagreement heatmaps
- other explicitly deferred 1.1 features

======================================================================
A. PRE-FLIGHT
======================================================================

Confirm:

git status --short
git branch --show-current
git rev-parse HEAD
git log -5 --oneline

Require the expected Phase 12 branch.

Confirm commit 8e4be364 is in history.

If the working tree contains unexpected changes:
- inspect them first
- preserve legitimate user work
- never blindly reset
- never blindly clean
- never discard user models, projects, annotations, databases, or datasets

Do not modify unrelated production functionality.

======================================================================
B. REMOVE THE PRETRAINED-WEIGHT ASSUMPTION FROM REEFVISION
======================================================================

Audit the entire model system.

Inspect at minimum:

config/model_catalog.json

apps/api/reefvision/api/routes/model_catalog.py
apps/api/reefvision/api/routes/models.py

apps/api/reefvision/ml/provider_hub.py
apps/api/reefvision/ml/model_bundles.py
apps/api/reefvision/ml/ultralytics_registry.py
apps/api/reefvision/ml/provider_adapters/ultralytics_multitask.py
apps/api/reefvision/ml/sleap_nn_provider.py

apps/api/reefvision/services/model_catalog.py
apps/api/reefvision/services/model_install.py
apps/api/reefvision/services/models.py
apps/api/reefvision/services/bundled_models.py
apps/api/reefvision/services/segmentation_models.py
apps/api/reefvision/services/semantic_models.py

apps/api/reefvision/jobs/pose_training.py

apps/api/reefvision/services/workflow_pose_training.py
apps/api/reefvision/services/pose_training_datasets.py
apps/api/reefvision/services/pose_training_exports.py

scripts/stage-bundled-models.py
scripts/install-remaining-models.py
scripts/install-remaining-models.ps1
scripts/audit-model-downloadability.py
scripts/repair-optional-model-catalog.py

and all related frontend Model Manager / Training workspace code and tests.

Identify every place ReefVision currently assumes that:
- a pretrained checkpoint exists
- a checkpoint should be downloaded automatically
- a catalog model is equivalent to a downloadable weight file
- training must begin from a seed .pt checkpoint
- model availability means pretrained weights can be retrieved

Replace that assumption with the architecture-first model.

======================================================================
C. CREATE A CLEAR MODEL TAXONOMY
======================================================================

ReefVision 1.0 should distinguish at least three concepts:

ARCHITECTURE

A lightweight model/config definition from which a completely new model can be trained.

Examples:
- YOLO11 Detect Nano
- YOLO11 Pose Small
- YOLO11 Segment Medium

Architecture entries contain no trained weights.

They may specify:
- architecture family
- task
- size
- architecture/config identifier
- supported provider
- supported training modes
- expected input constraints
- hardware recommendations
- task-specific capabilities

REGISTERED MODEL

A user-provided trained checkpoint that has been explicitly imported/registered into ReefVision.

Its provenance must include:
- original filename
- checksum
- provider
- task
- architecture if known
- landmark/class schema binding
- project association where applicable
- registration date
- user/model source metadata where applicable

TRAINED REEFVISION MODEL

A model produced by ReefVision training.

Its provenance must include:
- architecture
- random initialization / initialization policy
- training dataset revision
- validation dataset revision where applicable
- label or landmark schema revision
- hyperparameters
- provider/runtime version
- training run
- resulting checksum
- evaluation metrics where available

Do not describe an architecture as "Installed."

Architectures should instead have states such as:
- Available
- Supported
- Unsupported
- Training unavailable

Reserve "registered", "ready", or equivalent executable-model states for actual trained model files.

======================================================================
D. ULTRALYTICS ARCHITECTURE SUPPORT
======================================================================

Preserve the current Ultralytics provider.

Do not download Ultralytics pretrained .pt files.

Expose supported architectures as lightweight architecture choices.

At minimum, investigate and support the currently compatible YOLO11 architecture families for:

DETECTION
- YOLO11n
- YOLO11s
- YOLO11m
- YOLO11l
- YOLO11x

SEGMENTATION
- YOLO11n-seg
- YOLO11s-seg
- YOLO11m-seg
- YOLO11l-seg
- YOLO11x-seg

POSE
- YOLO11n-pose
- YOLO11s-pose
- YOLO11m-pose
- YOLO11l-pose
- YOLO11x-pose

Use architecture/config definitions, not pretrained checkpoints.

Verify each architecture can be instantiated without downloading weights.

For Ultralytics this generally means architecture/config construction rather than:
YOLO("something.pt")

Training from scratch must never cause Ultralytics to resolve/download a pretrained model.

Explicitly verify this behavior.

If YOLOv8 architecture support is already important to backward compatibility, preserve architecture-based YOLOv8 training as well, but do not add pretrained YOLOv8 weights.

Do not increase scope merely for symmetry.

YOLO11 should be the preferred new-project architecture family if the current pinned runtime supports it reliably.

======================================================================
E. POSE — CRITICAL ACCEPTANCE ITEM
======================================================================

ReefVision already contains substantial native pose infrastructure.

Preserve it.

ReefVision canonical pose functionality includes concepts such as:
- landmark schemas
- repeated semantic landmarks
- occurrence indices
- persistent landmark identities
- confidence
- visible / occluded / absent states
- identity breaks
- temporal association
- human corrections
- pose training datasets
- pose active learning
- interoperability
- workflow integration
- provenance

The Ultralytics provider already supports task=pose.

However the current pose-training workflow appears to require a registered seed pose checkpoint.

REMOVE THAT REQUIREMENT FOR FROM-SCRATCH TRAINING.

ReefVision must support:

YOLO11 pose architecture
→ ReefVision landmark schema
→ scientist-verified pose dataset
→ train from random initialization
→ produce ReefVision registered pose checkpoint
→ run video pose inference
→ ReefVision temporal association/tracking
→ review/correct
→ active-learning/retraining workflow

Support at least:
- YOLO11n-pose
- YOLO11s-pose
- YOLO11m-pose
- YOLO11l-pose
- YOLO11x-pose

No corresponding .pt file should be downloaded automatically.

Architecture definitions may be provided by the pinned Ultralytics package/config registry.

The pose trainer must support two explicit initialization modes:

FROM SCRATCH
- architecture required
- no initial checkpoint
- random initialization
- no pretrained weights

REGISTERED MODEL
- user selects an existing registered compatible pose model
- model checkpoint is used as initialization
- checksum/provenance is preserved

Do not silently switch between these modes.

Record initialization mode in provenance.

For from-scratch training, provenance should explicitly record something like:

initialization_mode = "random"
pretrained_weights = false
initial_checkpoint_model_id = null

For registered-model continuation/fine-tuning:

initialization_mode = "registered_model"
pretrained_weights = unknown/user_provided unless provenance proves otherwise
initial_checkpoint_model_id = ...

Do not call a user-supplied model pretrained unless that is explicitly known.

======================================================================
F. SLEAP-NN
======================================================================

Keep SLEAP-NN as an optional user-model backend.

Do not download a generic SLEAP pretrained model.

ReefVision currently supports explicit managed SLEAP-NN bundles and expects the validated SLEAP runtime versions.

Preserve:
- model bundle registration
- schema inspection
- video inference
- multi-instance handling
- normalization into ReefVision canonical pose observations
- ReefVision-native repeated-landmark temporal identities
- SLEAP interoperability

SLEAP models are skeleton/domain-specific.

Therefore:
- users bring/register their own trained SLEAP bundle
- ReefVision does not pretend there is a universal SLEAP checkpoint
- ReefVision does not auto-download species-specific models

If native SLEAP-NN training is not currently implemented, do not build an entire new SLEAP training system for 1.0.

Clearly present:
SLEAP-NN = REGISTER USER-TRAINED MODEL

Ultralytics pose = TRAIN FROM ARCHITECTURE OR REGISTER USER MODEL

======================================================================
G. DETECTION / SEGMENTATION / CLASSIFICATION / BEHAVIOR
======================================================================

Apply the same policy consistently.

Where ReefVision already has training support:

Architecture
→ verified data
→ train from scratch
→ registered trained checkpoint

Where ReefVision does not currently have training support:

User must explicitly register a compatible trained model.

Do not download pretrained weights.

Do not present generic pretrained biological detectors as first-party scientific models.

Training and model registration must remain explicit.

======================================================================
H. FOUNDATION / ASSIST / DEPTH / OCR MODELS
======================================================================

The "no pretrained models" requirement applies here too.

Do NOT automatically download:
- SAM
- SAM 2
- MobileSAM
- FastSAM
- Depth Anything
- Metric Video Depth Anything
- Grounding DINO
- OWLv2
- Florence
- SmolVLM
- TrOCR
- RT-DETR pretrained weights
- YOLO-World pretrained weights
- YOLOE pretrained weights
- nnU-Net pretrained assets
- or similar external checkpoints

If an assistive feature fundamentally requires a trained model that ReefVision cannot currently train from scratch:

require the researcher to explicitly register/provide the compatible checkpoint.

The UI should communicate:

"Model required — register a compatible model to use this feature."

Do not silently fetch it.

Do not mark such tools broken merely because no weights are bundled.

Differentiate:
- capability supported
- model not registered

from:
- capability not implemented

This distinction must be clear in the UI and API.

======================================================================
I. MODEL CATALOG REDESIGN
======================================================================

Update config/model_catalog.json and related schemas/services so the catalog does not behave primarily as a pretrained-checkpoint marketplace.

Prefer an architecture catalog.

For architecture entries, store fields such as:
- architecture_id
- provider_id
- family
- task
- size/variant
- configuration reference
- training_supported
- inference requires registered model
- CPU/CUDA support
- precision support
- recommended RAM
- recommended VRAM
- provider/runtime version
- known limitations

Do not include:
- pretrained checkpoint URLs
- pretrained SHA256
- pretrained expected size
- automatic install actions

unless needed only for backward compatibility/history and clearly disabled.

If existing schemas require those fields, migrate them carefully rather than stuffing fake values into them.

Preserve compatibility with previously registered user models and project records.

Do not break existing model registrations.

Existing user-trained models must continue to load.

======================================================================
J. MODEL MANAGER UI
======================================================================

Update Model Manager to match the new policy.

The Model Manager should clearly separate concepts such as:

ARCHITECTURES
Used to create/train new models.

REGISTERED MODELS
Actual executable trained checkpoints.

PROJECT MODELS
Models associated with the current project.

TRAINING RUN OUTPUTS
Models created by ReefVision.

OPTIONAL PROVIDERS
Providers/runtimes available for user-registered models.

Remove or disable misleading actions such as:
- Download pretrained
- Install pretrained model
- Install all models
- automatic weight retrieval

Replace with:
- Train New Model
- Choose Architecture
- Register Existing Model
- View Model Provenance
- Bind Class Schema
- Bind Pose Landmark Schema

Do not make the UI more complicated than necessary.

Use understandable researcher-facing terminology.

======================================================================
K. MODEL REGISTRATION
======================================================================

Ensure model registration remains robust.

A user must be able to register compatible:
- detection models
- segmentation models
- pose models
- classification models
- behavior models
- assist/foundation models where supported
- SLEAP-NN bundles

Registration must:
- copy model into managed ReefVision storage
- compute SHA-256
- preserve original filename
- validate provider compatibility
- validate task
- inspect model metadata where possible
- require explicit schema/class mapping
- reject unsupported/incompatible models clearly
- never mutate original user files
- record provenance

Pose registration must support binding to a ReefVision landmark schema.

======================================================================
L. FROM-SCRATCH TRAINING
======================================================================

Audit every ReefVision training path for pretrained initialization.

Explicitly ensure:
- pretrained=False where applicable
- no provider-level automatic download
- no fallback checkpoint resolution
- no checkpoint shorthand that causes a network retrieval

Network access should not be required merely to begin training from an architecture already provided by the runtime/package.

For each supported trainable task, verify architecture construction from scratch.

At minimum verify:
- detection
- pose

Also verify segmentation if current ReefVision 1.0 training genuinely supports it.

Do not fabricate segmentation training support if it does not exist yet.

Training should always record:
- architecture
- architecture version/reference
- initialization mode
- provider version
- dataset version
- seed/random state where available
- training parameters
- resulting model checksum

======================================================================
M. REMOVE / RETIRE PRETRAINED DOWNLOAD INFRASTRUCTURE
======================================================================

Review:
scripts/install-remaining-models.py
scripts/install-remaining-models.ps1
scripts/stage-bundled-models.py
scripts/audit-model-downloadability.py
scripts/repair-optional-model-catalog.py

These were created around an older pretrained-model strategy.

They must not remain as the normal ReefVision 1.0 workflow.

Either:
- remove them if no longer needed, OR
- repurpose them for architecture/provider validation, OR
- clearly mark them legacy/internal and ensure they are not used by the release/UI

Do not leave a hidden path that downloads pretrained weights automatically.

Search the entire repository for:
- urllib downloads of model weights
- requests/http downloads
- Hugging Face download helpers
- Ultralytics auto-download references
- checkpoint source URLs
- expected pretrained checksums
- install model endpoints
- "download model" UI text

Classify every match.

Disable/remove automatic pretrained weight acquisition.

Do not disable user-directed import/registration.

======================================================================
N. EXISTING LOCAL PRETRAINED MODEL CACHE
======================================================================

Do not delete user models.

Do not delete project-trained models.

Do not delete registered user checkpoints.

If old ReefVision-managed pretrained catalog downloads exist in:

%APPDATA%\org.reefvision.desktop

they may be cleaned up ONLY if ReefVision can prove through its own manifest/catalog provenance that they were automatically downloaded catalog assets and not user-provided models.

If provenance is uncertain:
leave the file untouched and report it.

Add or provide a safe cleanup mechanism such as:

"Remove legacy ReefVision pretrained cache"

It must show what will be removed and never touch:
- registered user models
- ReefVision-trained models
- project assets
- annotations
- databases
- datasets

Do not make destructive cleanup the prerequisite for upgrade.

======================================================================
O. OFFLINE / NETWORK POLICY
======================================================================

With this new architecture, ordinary ReefVision scientific workflows should not require internet access after installation, except for explicitly user-directed external operations.

Training from a supported built-in architecture must work offline provided the required runtime is installed.

Inference with registered models must work offline.

Opening projects must work offline.

Model registration must work offline.

No attempt to resolve a missing `.pt` from the internet should occur automatically.

Add tests that detect accidental network-dependent model loading where practical.

======================================================================
P. PHASE 12 NATIVE / UI ACCEPTANCE
======================================================================

Complete the remaining Phase 12 desktop acceptance using the existing ReefVision UI.

Do not replace the current GUI architecture.

Validate:

HOME / PROJECT LAUNCHER
- app launches
- recent projects
- pinned projects
- new/open/import project
- version
- GPU status
- API status
- storage status
- release/What's New presentation where implemented

PROJECT WORKBENCH
- left navigation
- main image/video viewer
- context-sensitive right inspector
- bottom gallery
- selection state
- scientific tools remain reachable

WORKSPACE PRESETS
Verify implemented presets such as:
- Detection
- Annotation
- Segmentation
- Pose Tracking
- Morphometrics
- Workflow Builder
- Review / QA
- Custom Layout

PANELS
Verify:
- collapse
- resize
- dock
- detach/pop-out where implemented
- close/reopen
- persisted layout
- no orphan windows

MULTI-MONITOR
Where supported:
- detach panel
- move between monitors
- close app
- reopen
- geometry restores appropriately
- disconnected-monitor layouts recover windows safely

WORKFLOW BUILDER
- opens
- nodes render
- connections render
- pan/zoom
- saved workflow reloads
- no clipping
- existing active-learning workflows remain functional
- pose architecture training nodes function correctly
- no v1.1 calculation nodes added

REVIEW MODE
- scientist review state works
- persistence works
- accepted/rejected/corrected outputs remain auditable

POSE
- landmark schema editor
- pose model registration
- pose architecture training
- video inference
- temporal tracking
- repeated landmarks
- occlusion states
- identity handling
- pose review
- active-learning workflow
- training dataset creation
- retraining workflow
- export/interoperability

Record the results in a final Phase 12 acceptance report.

Repair actual defects.

Add regression tests when practical.

======================================================================
Q. VERSION NORMALIZATION TO 1.0.0
======================================================================

The public release identity must be:

ReefVision 1.0.0

Audit the full repository for:
- 1.0.3
- 1.0.4
- 1.0.5
- release candidates
- development identifiers

Check:
- package.json
- Cargo.toml
- Tauri config
- Python package metadata
- backend version
- API version
- UI version
- About screen
- build scripts
- installer metadata
- installer filename
- checksum filename
- README
- release documentation

Normalize current public-release sources to 1.0.0.

Do not rewrite legitimate historical changelog entries.

Create or retain a validation test/script that fails if public version sources disagree.

======================================================================
R. FINAL WINDOWS INSTALLER
======================================================================

Build final Windows x64 ReefVision 1.0.0.

The installer must NOT bundle pretrained model weights.

This should substantially reduce model-related installer size.

Bundle only:
- ReefVision application
- backend sidecar/runtime
- frontend assets
- required Python/provider packages
- lightweight architecture/config definitions
- migrations
- required static scientific metadata
- licenses
- documentation/resources necessary for operation

Do not bundle `.pt`, `.pth`, `.ckpt`, `.safetensors`, etc. merely as pretrained starter weights.

Exceptions are not allowed unless the file is not a trained model and its nature is explicitly verified.

Architecture YAML/config files are allowed.

Build:
- frontend production bundle
- packaged backend
- Tauri app
- MSI
- release checksums

Verify installer filenames say 1.0.0 consistently.

======================================================================
S. CLEAN-INSTALL ACCEPTANCE
======================================================================

Perform a clean/fresh-profile test.

Existing developer AppData must not mask release defects.

Validate:

1. ReefVision installs.
2. ReefVision launches.
3. Backend launches automatically.
4. UI connects to packaged backend.
5. Database initializes.
6. Home screen works.
7. New project works.
8. Image import works.
9. Video import works.
10. Annotation works.
11. Architecture catalog appears.
12. No pretrained models appear as already installed.
13. Selecting an architecture does not initiate a model download.
14. Detection model can be trained from scratch using a small test dataset.
15. Resulting trained model is registered.
16. Registered model can run inference.
17. Pose architecture can be selected.
18. Pose model can be trained from scratch using a tiny valid test pose dataset where practical.
19. Trained pose model becomes a registered ReefVision model.
20. Pose inference/tracking path works.
21. User model registration works.
22. Restart persistence works.
23. Workflow Builder works.
24. Review mode works.
25. Model Manager distinguishes architecture from actual trained model.
26. Missing model produces a clear "register or train a model" state.
27. No network access is attempted simply because a pretrained model is absent.
28. Registered/trained models work offline.
29. Packaged application does not depend on:
    - source checkout
    - .venv
    - developer Python
    - source node_modules
    - user-specific development paths

Training acceptance may use very small synthetic/scientific test datasets strictly to verify execution.

Do not claim resulting tiny smoke-test models are scientifically useful.

======================================================================
T. AUTOMATED VALIDATION
======================================================================

After changes run the complete appropriate validation matrix.

BACKEND
- Ruff
- formatting
- mypy apps/api/reefvision
- full backend pytest

FRONTEND
- TypeScript
- full Vitest suite
- production build

POSE
- pose provider tests
- temporal tracking tests
- pose active-learning tests
- pose training dataset tests
- pose training/export tests
- workflow pose training tests
- video pose tracking tests
- interoperability tests that do not require unavailable optional runtimes

MODEL SYSTEM
- model registration tests
- architecture catalog tests
- provider tests
- model-manager tests
- tests proving pretrained auto-download is disabled
- tests proving architectures can instantiate without pretrained weights
- tests proving user-trained/user-registered models still execute

PACKAGING
- Rust/Tauri checks
- packaged backend self-test
- final MSI build
- clean-profile launch

If optional SLEAP runtime is installed, run its integration tests too.

Do not make the 1.0 release depend on SLEAP being installed.

======================================================================
U. TEST THE NO-PRETRAINED GUARANTEE
======================================================================

Create automated release checks that fail if prohibited pretrained weight files are included.

Inspect installer staging/output recursively.

Fail release validation if unnecessary trained-model extensions appear in bundled model directories, including:

.pt
.pth
.ckpt
.safetensors
.engine
.onnx

Be careful: some non-model package/runtime assets could theoretically use similar extensions.

Validate based on intended bundle locations and manifest, not only extension globally.

Also inspect the final model catalog.

Fail if an architecture entry:
- has an automatic pretrained source URL
- is presented as a downloadable pretrained model
- requires auto-installation of external weights

Add a test ensuring a fresh ReefVision profile contains no pretrained model cache.

======================================================================
V. RELEASE DOCUMENTATION
======================================================================

Document the model philosophy clearly.

Include text equivalent in meaning to:

"ReefVision does not bundle or automatically download pretrained scientific model weights. Researchers train models from supported architectures using their own verified datasets or explicitly register compatible trained models. This reduces installation size, avoids inappropriate assumptions from generic pretrained datasets, and keeps model provenance explicit."

Document:
- supported architecture families
- trainable tasks
- registerable model formats
- pose architecture support
- SLEAP-NN registration
- initialization behavior
- random/from-scratch training
- model provenance
- storage locations
- hardware recommendations
- offline behavior
- known limitations

Do not imply that from-scratch training necessarily performs better than transfer learning.

This is a ReefVision product/provenance policy, not a universal scientific claim.

======================================================================
W. RELEASE COMMIT STRATEGY
======================================================================

Use logical commits.

Suggested checkpoints:

1.
refactor(models): adopt architecture-first no-pretrained policy

2.
feat(training): support from-scratch Ultralytics pose architectures

3.
fix(ui): finalize architecture and registered-model workflows

4.
fix(ui): close Phase 12 desktop acceptance defects

5.
chore(release): normalize ReefVision 1.0.0

6.
chore(release): finalize Windows release validation

Do not rewrite published history.

Push validated checkpoints.

Working tree must be clean at the end.

======================================================================
X. FINAL 1.0 ACCEPTANCE CRITERIA
======================================================================

ReefVision 1.0 is complete only when all applicable criteria pass:

CORE QUALITY

[ ] Ruff clean
[ ] mypy = 0 errors
[ ] backend full test suite passes
[ ] TypeScript passes
[ ] frontend tests pass
[ ] production frontend build passes
[ ] Tauri build passes

MODEL POLICY

[ ] no pretrained model weights bundled
[ ] no automatic pretrained downloads
[ ] no silent provider auto-download
[ ] architecture catalog implemented
[ ] registered-model catalog/workflow implemented
[ ] architecture and trained model concepts clearly separated
[ ] existing user model registration preserved
[ ] user-trained model provenance preserved

DETECTION

[ ] supported detection architecture can train from scratch
[ ] trained output registers correctly
[ ] trained output runs inference

POSE

[ ] YOLO11 pose architecture supported
[ ] n pose architecture available
[ ] s pose architecture available
[ ] m pose architecture available
[ ] l pose architecture available
[ ] x pose architecture available
[ ] no YOLO11 pose pretrained weights required
[ ] from-scratch pose training works
[ ] registered user pose model works
[ ] landmark schema binding works
[ ] pose video inference works
[ ] ReefVision temporal pose tracking works
[ ] repeated landmarks work
[ ] occlusion states work
[ ] active learning remains functional
[ ] pose training datasets remain immutable/auditable
[ ] workflow pose retraining works
[ ] SLEAP-NN user-model registration remains supported

MODEL MANAGER

[ ] Architecture tab/state works
[ ] Registered Models works
[ ] Train New Model works
[ ] Register Existing Model works
[ ] no "Install pretrained model" path remains active
[ ] features missing required models explain what user must register/train

PHASE 12

[ ] desktop workbench accepted
[ ] workspace presets accepted
[ ] dock/detach behavior accepted
[ ] multi-monitor behavior accepted where supported
[ ] Review Mode accepted
[ ] Workflow Builder accepted
[ ] pose workspace accepted

RELEASE

[ ] version consistently 1.0.0
[ ] final MSI builds
[ ] MSI does not contain pretrained weights
[ ] packaged backend starts
[ ] clean-profile test passes
[ ] architecture training works on packaged release
[ ] registered-model inference works on packaged release
[ ] application works offline with local architectures/models
[ ] release checksums generated
[ ] release documentation complete
[ ] repository clean
[ ] commits pushed

Only after all applicable acceptance criteria pass:

[ ] create v1.0.0 tag
[ ] record tag SHA
[ ] prepare final release artifacts

======================================================================
Y. IMPORTANT ENGINEERING RULES
======================================================================

Do not weaken tests.

Do not use blanket skips.

Do not add type: ignore simply to silence failures.

Do not fake architecture support.

Do not fake model compatibility.

Do not label an architecture as an executable model.

Do not silently download weights.

Do not permit upstream packages to silently download weights.

Do not bundle human COCO pose weights.

Do not bundle generic pretrained detection weights.

Do not bundle generic pretrained segmentation weights.

Do not bundle generic foundation-model checkpoints.

Do not delete user data.

Do not delete user-registered models.

Do not delete ReefVision-trained models.

Do not destroy existing project compatibility.

Do not create fake checksums or provenance.

Keep ReefVision local-first.

Keep ReefVision-native scientific schemas canonical.

Preserve:
- human review
- provenance
- immutable verified datasets
- pose identities
- annotation history
- reproducible training records

Prefer root-cause fixes.

Do not stop after producing a plan.

Execute the work.

======================================================================
Z. FINAL CLOSEOUT REPORT
======================================================================

When all work possible in the current environment is finished, provide one final report containing:

1. Final ReefVision version
2. Branch
3. Final commit SHA
4. v1.0.0 tag SHA if created
5. Backend test result
6. Frontend test result
7. mypy result
8. Ruff result
9. Tauri/build result
10. MSI filename/path
11. MSI SHA-256
12. MSI size
13. Confirmation that no pretrained model weights are bundled
14. Confirmation that no automatic pretrained-weight download path remains
15. Supported architecture count
16. Supported architecture IDs
17. Supported detection architectures
18. Supported segmentation architectures
19. Supported pose architectures
20. Which tasks train from scratch in ReefVision
21. Which tasks require user-registered models
22. SLEAP-NN runtime/registration status
23. From-scratch YOLO pose training result
24. Registered-model inference result
25. Phase 12 manual acceptance result
26. Clean-profile installation result
27. Offline behavior result
28. Remaining known limitations
29. git status
30. RELEASE READY: YES or NO

If RELEASE READY is NO, identify the exact blocking items.

Do not call it release ready while a required acceptance criterion is failing.

Proceed now from the existing validated Batch 5 checkpoint and carry ReefVision Scientist-Ready 1.0 through architecture-policy conversion, Phase 12 closeout, version normalization, packaging, validation, and final release preparation.