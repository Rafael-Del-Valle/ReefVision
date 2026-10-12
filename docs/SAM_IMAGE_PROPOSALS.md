# Full-image SAM proposals (1.0.1)

`POST /api/v1/projects/{project_id}/sam-image-proposals` accepts
`SamImageProposalsRequest` and returns a persisted `JobResponse` with HTTP 202.
Poll, cancel, and retry through the existing jobs routes. The job type is
`sam_image_proposals`; `result_json.proposal_ids` names ordinary pending raster
predictions consumed by the existing prediction review routes. No project
detector is required and no class is inferred. Acceptance requires an explicit
project class and researcher action. There is no database migration.

The request selects an already installed SAM 2.1 variant. Missing/corrupt local
weights produce an actionable Model Hub error; this endpoint never downloads.
Only the explicit SAM installation action downloads the upstream Apache-2.0
checkpoint and records its revision and SHA-256. Proposals retain that provenance,
the job ID, source image ID, generation policy, thresholds, prompt, stability,
resolved execution device, and source-sized PNG checksum. A SAM model is not
trained on project labels, so its training dataset ID is null.

## Generation policy

- Transformers `Sam2Model.get_image_embeddings` encodes each tile once.
  `forward(image_embeddings=..., input_points=..., input_labels=...,
  multimask_output=True)` produces three genuine model alternatives per positive
  point. The worker caches one model/processor pair and serializes use with mask
  refinement. The installed Transformers 4.57.2 implementation and its source
  coordinate scaling were inspected and exercised with a real checkpoint.
- Tiles default to 1,536 source pixels with 25% overlap. The last tile is aligned
  to the image edge. A deterministic 4-by-4 grid samples each tile by default.
  The API allows 1–8 points per side and 512–2,048 pixel tiles, but rejects more
  than 16 tiles, 256 prompts, or 64 million source pixels. No image is silently
  resized before tiling. Masks touching an internal tile edge are rejected as
  incomplete; image-border objects remain eligible.
- Candidates need the requested predicted-IoU confidence, minimum source-pixel
  area, and stability. Stability is mask area above logit +1 divided by area
  above logit -1. Holes and disconnected components are preserved.
- Candidate suppression uses actual binary-mask intersection/union, not boxes.
  The defaults are IoU >= 0.85 between candidates/pending proposals and >= 0.80
  against verified masks. Touching/disjoint masks therefore survive even when
  their boxes overlap. Score-ranked storage retains at most 32 candidates
  (configurable to 64). Verified masks are read only for final suppression and
  never used as implicit prompts or modified.
- Progress and cancellation are checked between inference operations, tiles,
  reference-mask comparisons, and before the final transaction. All proposals
  and success status commit together. Failure/cancellation leaves no partially
  published proposals. Interrupted running jobs are requeued on restart; pending
  cancellation becomes cancelled. Incomplete files after a process crash can
  remain unreferenced in managed storage; they are not verified annotations.

## Limits and evidence

The time budget is cooperative (default 120 seconds, maximum 600). A native Torch
operation or model load cannot be interrupted mid-call; this is not an isolated
hard-kill worker. GPU exhaustion reports CPU/Tiny retry guidance rather than
silently changing device. Coarse grids can miss small objects, overlapping tiles
can miss very large boundary-crossing objects, and hierarchical/background
alternatives can remain. The capped candidate list is filtered against verified
masks afterward, so suppression can leave fewer results than the requested cap.
No recall, calibrated confidence, coral-specific accuracy, or exhaustive object
count is claimed.

The opt-in `test_patch_101_live_sam2_acceptance.py` test downloads Tiny only into
temporary pytest storage, runs real CPU point-grid inference without a detector,
and asserts multiple pending, unclassified source-sized masks. Local live
acceptance produced seven candidates on a four-object 320-by-192 synthetic image,
using revision `de431c4043854a71d8101e17995dfe596bf101a5` and checkpoint SHA-256
`48c14467e5cf9e51870511feb72c89688e82dd74523142c0538b663e193ac2a7`.
An earlier smaller-circle fixture had no foreground points on the coarse grid
and produced one background candidate; this observed limitation is not hidden.
This evidence is source-runtime CPU validation, not coral accuracy, GPU, packaged
Windows GUI, clean MSI installation, or release approval.
