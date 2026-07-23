# Multi-model segmentation auto-labeling

ReefVision provides two multi-model segmentation workflows:

1. **Semantic review:** SAM 3 generates a mask while Gemini and OpenAI independently review that candidate.
2. **Independent mask consensus:** SAM 3 generates one mask branch, Gemini detects boxes that SAM 2 refines into masks, and OpenAI independently detects boxes that SAM 2 refines into masks.

Both modes produce reviewable ReefVision predictions. Automatic acceptance is disabled by default.

## Architecture

### Semantic-review mode

```text
SAM 3 mask
    ├─ SAM 3 confidence vote
    ├─ Gemini crop-and-overlay review
    └─ OpenAI crop-and-overlay review
                 ↓
          configured quorum
                 ↓
       review or optional promotion
```

This mode is less expensive because Gemini and OpenAI review an existing candidate instead of finding every object independently.

### Independent-mask mode

```text
                    ┌─ SAM 3 text segmentation ───────── mask A
Image + concept ────┼─ Gemini box detection ── SAM 2 ── mask B
                    └─ OpenAI box detection ── SAM 2 ── mask C
                                      ↓
                     class-aware one-to-one instance matching
                                      ↓
                      configured 2-of-3 pixel aggregation
                                      ↓
                         reviewable consensus mask
```

Independent-mask mode can still propose an object when SAM 3 misses it, provided the Gemini/SAM 2 and OpenAI/SAM 2 branches match and satisfy the configured quorum.

## Why SAM 3 and SAM 2 can run as sidecars

SAM-family packages can require Python, PyTorch, CUDA, and compiled-extension versions that differ from ReefVision's pinned desktop backend. ReefVision therefore supports isolated localhost sidecars:

- SAM 3 sidecar: concept-prompted instance segmentation
- SAM 2 sidecar: box-prompted mask refinement

The desktop stores small immutable JSON connection descriptors, not duplicate checkpoints or bearer tokens. Sidecar endpoints must resolve to localhost.

## 1. Prepare the SAM 3 sidecar

Follow the current official SAM 3 installation instructions in a separate environment. Start the ReefVision sidecar from the repository while that environment is active:

```powershell
$env:REEFVISION_SAM3_SIDECAR_TOKEN = "replace-with-a-long-random-token"
python scripts/sam3_sidecar_server.py --host 127.0.0.1 --port 8765
```

The token is optional but recommended. The server refuses a non-loopback bind unless that behavior is explicitly enabled.

## 2. Prepare the SAM 2 sidecar

Install Meta SAM 2 and its dependencies in a separate environment. Supply the matching model configuration and checkpoint:

```powershell
$env:REEFVISION_SAM2_SIDECAR_TOKEN = "replace-with-a-different-long-random-token"
python scripts/sam2_sidecar_server.py `
  --config configs/sam2.1/sam2.1_hiera_l.yaml `
  --checkpoint checkpoints/sam2.1_hiera_large.pt `
  --device cuda:0 `
  --host 127.0.0.1 `
  --port 8766
```

The sidecar loads one checkpoint on one configured device. Start another sidecar on another port when a different checkpoint or GPU is needed.

## 3. Connect the sidecars in ReefVision

Open **Workflows** and use **Connect SAM 3 and SAM 2 to Workflows**.

For SAM 3:

1. Enter the localhost endpoint, normally `http://127.0.0.1:8765`.
2. Enter a concept such as `Swiftia exserta colony` or `octocoral fragment`.
3. Map that concept to one active ReefVision class.
4. Register the SAM 3 segmenter.

For SAM 2:

1. Enter the localhost endpoint, normally `http://127.0.0.1:8766`.
2. Enter the bearer-token environment-variable name.
3. Test the connection. ReefVision verifies the provider identity, status, model version, configured device, and whether a token is available in its own process.
4. Register the sidecar descriptor.
5. Select either that isolated sidecar or an existing compatible in-process SAM 2 registration.

Registration stores the environment-variable name but never stores the token value.

## 4. Enable remote model branches deliberately

Remote processing is disabled by default. Set these variables in the ReefVision process environment:

```powershell
$env:REEFVISION_ALLOW_REMOTE_VISION = "true"
$env:REEFVISION_GEMINI_API_KEY = "your-google-api-key"
$env:REEFVISION_OPENAI_API_KEY = "your-openai-api-key"
$env:REEFVISION_SAM3_SIDECAR_TOKEN = "the-same-SAM-3-sidecar-token"
$env:REEFVISION_SAM2_SIDECAR_TOKEN = "the-same-SAM-2-sidecar-token"
```

Then set `allow_remote_review` to `true` in the selected consensus configuration.

## Semantic-review configuration

```json
{
  "multi_model_consensus": {
    "enabled": true,
    "mode": "semantic_voters",
    "required_primary_provider": "sam3_sidecar",
    "prompt": "octocoral colony or fragment",
    "required_votes": 2,
    "sam_vote_threshold": 0.35,
    "minimum_reviewer_confidence": 0.6,
    "gemini_model": "gemini-2.5-flash",
    "openai_model": "gpt-5-mini",
    "allow_remote_review": true,
    "auto_accept": false,
    "fail_closed": true
  }
}
```

Each SAM 3 proposal receives one primary confidence vote plus independent Gemini and OpenAI review decisions. A malformed or failed remote response becomes an abstention when `fail_closed` is true.

## Independent-mask configuration

```json
{
  "multi_model_consensus": {
    "enabled": true,
    "mode": "independent_masks",
    "required_primary_provider": "sam3_sidecar",
    "sam2_model_id": "<registered-SAM-2-model-id>",
    "label_class_id": "<project-class-id>",
    "predicted_label": "octocoral colony or fragment",
    "prompt": "octocoral colony or fragment",
    "required_votes": 2,
    "iou_threshold": 0.3,
    "aggregation": "pixel_majority",
    "minimum_vlm_confidence": 0.25,
    "gemini_model": "gemini-2.5-flash",
    "openai_model": "gpt-5-mini",
    "sam2_device": "auto",
    "allow_remote_review": true,
    "auto_accept": false,
    "fail_closed": true
  }
}
```

Gemini and OpenAI must return structured source-image boxes. ReefVision rejects malformed, non-finite, inverted, or out-of-bounds boxes before SAM 2 refinement.

## Instance matching and aggregation

ReefVision groups only masks that:

- belong to the same image and requested class,
- meet the configured mask-IoU threshold, and
- come from different branches.

One branch cannot contribute multiple votes to the same consensus group. Matching is one-to-one so crowded detections cannot reuse the same confirmation mask repeatedly.

Available aggregation modes:

- `pixel_majority`: retains a pixel when the configured number of branches include it; recommended starting point for thin coral structures.
- `intersection`: retains only shared pixels; the most conservative mode and the closest to the referenced article workflow.
- `union`: retains pixels from all agreeing masks; more inclusive but may expand false-positive boundaries.
- `best_confidence`: keeps the highest-confidence agreeing candidate unchanged.

## Review, provenance, and recovery

Consensus outputs are persisted as reviewable, source-aligned raster-mask proposals. Provenance includes:

- workflow run and node IDs,
- source image and model identifiers,
- model and checkpoint checksums,
- detector model names and confidence values,
- source detection boxes,
- SAM 2 refinement scores,
- participating branch and candidate IDs,
- pairwise mask IoU,
- quorum and aggregation settings,
- remote-provider warnings and failures.

Keep `auto_accept` false until the workflow has been tested on representative images. Accepted masks remain editable in ReefVision.

Workflow runs support retry and partial rerun. Terminal-run output files can be moved into reversible project quarantine. Restoration rechecks the original destination, shared references, file SHA-256, and quarantine location before moving a file back.

## Privacy and cost

The modes transmit different information:

- Semantic review sends padded source crops and highlighted-mask overlays.
- Independent-mask mode sends each selected full image to Gemini and OpenAI so both can find objects independently.

Do not enable either mode when provider transfer conflicts with project data-use requirements. Independent-mask mode can also create substantially more remote inference and SAM 2 refinement work. Begin with a small validation set and record request counts, latency, failure rate, and cost.

## Scientific validation

Model agreement is not biological ground truth. Before using consensus labels for training or inference claims, compare them against a held-out manually reviewed set. At minimum, evaluate:

- object-level precision and recall,
- mask IoU and boundary accuracy,
- class-specific false positives and false negatives,
- performance on crowded or overlapping colonies,
- thin-structure retention under each aggregation mode,
- disagreement between human reviewers,
- review time and correction burden,
- API cost and end-to-end latency.

## Current limitations

- Independent generation currently executes as one compound Workflow segmenter stage. The internal branches and final proposal preserve detailed provenance, but Gemini, OpenAI, and SAM 2 branch outputs are not yet separate persisted graph nodes that can each be rerun independently.
- Remote requests are deliberately sequential in several paths for deterministic provenance and rate-limit safety.
- A real SAM 3/SAM 2/Gemini/OpenAI acceptance run is still required on the target workstation.
- Thresholds and aggregation behavior have not yet been scientifically calibrated for a particular coral dataset.
- Full Windows packaging and clean-machine sidecar acceptance remain separate release gates.
