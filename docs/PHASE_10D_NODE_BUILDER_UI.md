# ReefVision Scientist-Ready Phase 10D — Node Builder UI Integration

## Objective

Expose the Phase 10 workflow engine as a scientist-facing visual workflow system without creating a second execution path. The UI remains a view/editor over the canonical workflow graph, node registry, persisted node runs, artifacts, review state, and provenance created by the backend.

## Implemented scope

- Existing typed visual canvas retained and upgraded rather than replaced.
- Node cards distinguish automated execution, Active Learning, scientific analysis, and human-review truth boundaries.
- Live node-run state is shown directly on the visual graph, including queued, running, waiting for review, succeeded, failed, and cancelled states.
- Plan readiness is shown before execution when a run does not yet exist.
- Primitive node parameters are editable through scientist-friendly controls while advanced JSON remains available for nested provider/training settings.
- A dedicated **Pose Active Learning → retrain** template covers project/video source, seed pose model, pose inference, temporal association, scientist pose review, pose Active Learning, scientist Active Learning review, immutable dataset freeze, pose export, retraining, trained-model registration, and Results Package generation.
- The trained model is connected back to inference only through a dashed **next iteration** metadata cue. It is intentionally not a graph edge, so the executable workflow remains acyclic and resumable.
- Terminal provenance SHA-256 and the complete provenance manifest are inspectable from the run panel.
- Saved graph metadata and node positions remain part of the canonical graph JSON.

## Scientific UX rules

1. Machine output is never styled or labeled as scientist-verified truth.
2. Human-review gates are visually distinct and continue to pause the backend workflow.
3. The Active Learning loop must pass through explicit scientist verification before dataset freeze.
4. Feedback-loop visualization must never create an executable cycle.
5. Run-state overlays are derived from persisted WorkflowNodeRun state rather than local optimistic UI state.
6. Provenance shown in the UI is the backend-generated canonical manifest from Phase 10C.
7. Advanced JSON remains available so visual convenience never removes exact reproducibility controls.

## Acceptance

Automated acceptance is in `scripts/phase10d-acceptance.ps1`.

Focused tests cover scientist-review visual semantics, waiting-for-review node state, next-iteration feedback visualization, primitive parameter editing, the pose Active Learning retraining template, and the absence of an executable register → inference cycle.

Phase 10 is complete only after the Phase 10D focused tests, full frontend suite, TypeScript validation, production build, and manual scientist UI checks pass.
