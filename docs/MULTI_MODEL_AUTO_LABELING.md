# Multi-model segmentation auto-labeling

ReefVision can run SAM 3, Gemini, and GPT as one persisted Workflow. SAM 3 proposes source-aligned instance masks. Gemini and GPT independently review a source crop and a translucent mask overlay. A mask is promoted to a verified ReefVision raster annotation only when at least two of the three voters pass their configured confidence thresholds.

## Why SAM 3 runs as a sidecar

The official SAM 3 repository currently requires Python 3.12 or newer, PyTorch 2.7 or newer, and a CUDA-compatible GPU with CUDA 12.6 or newer. ReefVision therefore keeps SAM 3 in a separate environment and communicates only over localhost HTTP. This prevents SAM 3 dependency upgrades from changing the pinned desktop backend.

Official source: https://github.com/facebookresearch/sam3

## 1. Install SAM 3 in a separate environment

Follow the current official SAM 3 installation instructions. A representative setup is:

```powershell
conda create -n sam3 python=3.12
conda activate sam3
pip install torch==2.10.0 torchvision --index-url https://download.pytorch.org/whl/cu128
git clone https://github.com/facebookresearch/sam3.git
cd sam3
pip install -e .
hf auth login
```

Checkpoint access must be approved on the official SAM 3 Hugging Face repository before the sidecar can build the model.

The ReefVision sidecar script imports the official `build_sam3_image_model` and `Sam3Processor` APIs. Run it from the ReefVision repository while the `sam3` environment is active:

```powershell
$env:REEFVISION_SAM3_SIDECAR_TOKEN = "replace-with-a-long-random-token"
python scripts/sam3_sidecar_server.py --host 127.0.0.1 --port 8765
```

The token is optional but recommended. The server refuses non-loopback binding unless `--allow-non-loopback` is passed explicitly.

## 2. Register SAM 3 in ReefVision

Open **Workflows** and use **Connect SAM 3 to Workflows**.

1. Enter the localhost endpoint, normally `http://127.0.0.1:8765`.
2. Enter a concept prompt such as `Swiftia exserta colony`.
3. Map the prompt to one active ReefVision class.
4. Register the sidecar segmenter.
5. Copy the returned model ID into the Workflow segmenter node's `model_id` setting.

The registration creates a small immutable JSON descriptor, not a duplicate checkpoint. The descriptor stores the endpoint, concept prompt, class mapping, score threshold, and token environment-variable name. It never stores the bearer token.

## 3. Enable Gemini and GPT deliberately

Remote review is disabled by default. Set these variables in the ReefVision process environment:

```powershell
$env:REEFVISION_ALLOW_REMOTE_VISION = "true"
$env:REEFVISION_GEMINI_API_KEY = "your-google-api-key"
$env:REEFVISION_OPENAI_API_KEY = "your-openai-api-key"
$env:REEFVISION_SAM3_SIDECAR_TOKEN = "the-same-sidecar-token"
```

Then load the **SAM 3 + Gemini + GPT auto-labeling** template and change:

```json
{
  "multi_model_consensus": {
    "enabled": true,
    "allow_remote_review": true,
    "required_votes": 2,
    "auto_accept": true,
    "fail_closed": true
  }
}
```

The default reviewers are `gemini-2.5-flash` and `gpt-5-mini`. Both model IDs remain editable in the node configuration.

## Voting behavior

Each SAM 3 proposal receives three votes:

- **Primary segmenter vote:** passes when the SAM 3 proposal confidence reaches `sam_vote_threshold`.
- **Gemini vote:** reviews the source crop and red mask overlay, returning structured JSON with accept/reject, confidence, and reason.
- **GPT vote:** independently performs the same review using the OpenAI Responses API.

A remote accept vote counts only when it also reaches `minimum_reviewer_confidence`. With `required_votes: 2`, examples include:

- SAM 3 + Gemini accept: promote the mask.
- SAM 3 + GPT accept: promote the mask.
- Gemini + GPT accept while SAM confidence is low: promote the mask.
- Only one accepted vote: leave the proposal pending.

Failed or malformed remote responses are treated as abstentions when `fail_closed` is true. The Workflow fails instead when `fail_closed` is false.

## Annotation and provenance behavior

Promoted masks are stored as full-resolution binary PNG annotations and remain editable in ReefVision. Each mask records:

- Workflow run and node IDs
- SAM 3 proposal, model, checksum, and inference-job IDs
- Concept prompt and quorum settings
- All three decisions, confidences, reasons, and provider errors
- Promotion timestamp and source geometry metadata

The original proposal is linked to the accepted mask. Images that do not reach quorum remain reviewable rather than being silently discarded.

## Privacy, cost, and scientific validation

For every candidate mask, ReefVision sends two cropped images to Gemini and OpenAI: the source crop and the same crop with a translucent red overlay. Do not enable remote review for imagery that cannot be transferred to those providers under the project's data-use requirements.

Remote review creates per-mask API usage. Large datasets may generate substantial request counts. Start with a representative validation subset, measure precision/recall and cost, and tune the prompt and thresholds before running the complete dataset.

A 2-of-3 vote is a quality-control rule, not proof of biological ground truth. Scientific acceptance should still include a held-out manually reviewed subset, inter-annotator comparison, class-specific error analysis, and documented correction procedures.

## Current limitations

- Gemini and GPT review SAM 3 masks; they do not independently return source-aligned pixel masks in this implementation.
- Review requests are currently processed sequentially per candidate for deterministic provenance and rate-limit safety.
- The sidecar endpoint is registered but not health-checked during registration; unavailable sidecars fail safely at inference.
- Real SAM 3, Gemini, and OpenAI acceptance tests must be run on the target workstation before production use.
