# ReefVision 1.9 integration audit — workflow planner contract

Status: development only; no release acceptance implied.

## Verified source-level defect

The extended Workflow Builder registry advertises `pose_training_dataset` as
executable, and the pose-training runtime registers its adapter. However, the
graph planner uses a direct `_ACTIONS[node.node_type]` lookup and the original
action table did not contain `pose_training_dataset`. Valid graphs containing
that node could therefore fail during planning before execution.

## Bounded correction

- Add the missing planner action without altering the node's dataset contract,
  runtime adapter, human-verification requirements, or manifest provenance.
- Add a regression invariant across all advertised nodes and runtime adapters.
- Test a pose dataset source graph through API planning, saved graph revision,
  graph SHA-256 persistence, and workflow-run queueing.
- The synthetic dataset identifier in this planner test is intentionally not
  executed or represented as verified scientific evidence. Dataset validation
  remains the runtime adapter's responsibility.

## Outstanding 1.9 acceptance

Run focused tests, complete backend/frontend CI, saved-workflow execution with
a real immutable verified dataset, scientific provenance and review checks,
migration and compatibility roundtrips, Windows MSI/CAB build and native GUI
acceptance. Audit upstream 1.0.x–1.8 features before cross-version integration;
do not merge unfinished development branches. 2.0 remains isolated.
