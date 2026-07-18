# Phase 10 — Workflow Graph Foundation

## Scope

The repository did not contain an existing node-editor, edge, port, fusion, or workflow-execution contract. This phase therefore defines only the semantics that can be mapped directly to existing ReefVision operations.

There is no graph executor, scheduler, persistence model, drag-and-drop canvas, automatic retry system, or automatic continuation through human review gates.

## Data types

The initial graph type system includes:

- project reference
- image collection
- immutable dataset version
- registered model reference
- source video reference
- existing box and mask annotations
- detection proposals
- mask proposals
- classification predictions
- reviewed boxes, masks, and labels
- measurement table
- video tracks
- project exchange package

## Node registry

### Sources

- Current Project
- Project Images
- Immutable Dataset Version
- Registered Model
- Project Video
- Verified Masks

### Existing operations

- Detection Inference
- Segmentation Inference
- Classification Inference
- Coral Mask Measurements
- Video Tracking
- Project Exchange Export

### Human review gates

- Detection Review Gate
- Mask Review Gate
- Classification Review Gate

Human review gates are explicit pause points. They do not automatically accept predictions.

## Validation

Validation checks:

- supported graph schema
- unique node and edge IDs
- known node types
- required parameters
- source and target node existence
- port existence
- compatible data types
- required input connections
- single-input multiplicity
- project ownership for datasets, models, and videos
- complete dataset-version status
- model-purpose compatibility
- self edges and cycles

## Dry-run planning

A valid graph can be converted to a topological plan containing:

- ordered steps
- resolved default parameters
- input bindings and data types
- output contracts
- the established ReefVision operation each node would map to

Every plan returns `executable: false` with an explicit blocker stating that no graph executor exists.

## Why execution is deferred

Execution still requires design decisions for:

1. graph persistence and immutable revisions
2. job dependency and cancellation behavior
3. intermediate artifact identity and retention
4. resuming after human review gates
5. failure and retry semantics
6. parameter templating and secrets
7. GPU resource scheduling
8. partial reruns and cache invalidation
9. provenance across every generated artifact
10. visual editor interaction and accessibility

Those decisions should be made before implementing a generic executor or visual node canvas.
