import type { PoseTrainingDataset } from "../video/poseActiveLearningApi";
import type { VideoAssetRecord } from "../video/videoApi";

export interface WorkflowSourceNode {
  node_id: string;
  node_type: string;
  parameters?: Record<string, unknown>;
}

export interface WorkflowSourceEdge {
  source_node_id: string;
  target_node_id: string;
  target_port_id: string;
}

interface SourceFieldsProps {
  nodes: WorkflowSourceNode[];
  edges: WorkflowSourceEdge[];
  datasets: PoseTrainingDataset[];
  recordings: VideoAssetRecord[];
  onPick: (nodeId: string, id: string, digest: string) => void;
}

function SourcePin({ pinned, current }: { pinned: string; current?: string }) {
  if (!pinned) return <small>Choose a source to pin its checksum.</small>;
  return (
    <small>
      SHA-256 <code title={pinned}>{pinned.slice(0, 12)}…</code>
      {current &&
        pinned !== current &&
        " — Saved checksum differs. Choose the source again to update this draft."}
    </small>
  );
}

export function WorkflowPoseSourceFields({
  nodes,
  edges,
  datasets,
  recordings,
  onPick,
}: SourceFieldsProps) {
  const frozen = nodes.filter(
    (node) => node.node_type === "pose_training_dataset",
  );
  const videos = nodes.filter(
    (node) => node.node_type === "project_video_source",
  );
  function label(node: WorkflowSourceNode) {
    const connections = edges.filter(
      (edge) => edge.source_node_id === node.node_id,
    );
    if (node.node_type === "project_video_source") {
      return connections.some(
        (edge) =>
          nodes.find((target) => target.node_id === edge.target_node_id)
            ?.parameters?.require_held_out_recording === true,
      )
        ? "Held-out recording"
        : "Project recording";
    }
    if (frozen.length > 1) {
      if (
        connections.some((edge) => edge.target_port_id === "validation_dataset")
      )
        return "Frozen validation dataset";
      if (
        connections.some(
          (edge) =>
            edge.target_port_id === "dataset" &&
            nodes.find((target) => target.node_id === edge.target_node_id)
              ?.node_type === "pose_model_training",
        )
      )
        return "Frozen training dataset";
    }
    return "Frozen pose dataset";
  }
  return (
    <>
      {frozen.map((node) => {
        const selectedId = String(node.parameters?.dataset_id ?? "");
        const selected = datasets.find((item) => item.id === selectedId);
        const heading = label(node);
        return (
          <label key={node.node_id}>
            {heading}
            <select
              aria-label={heading}
              value={selectedId}
              onChange={(event) => {
                const item = datasets.find(
                  ({ id }) => id === event.target.value,
                );
                onPick(
                  node.node_id,
                  item?.id ?? "",
                  item?.manifest_sha256 ?? "",
                );
              }}
            >
              <option value="">Choose a verified pose dataset</option>
              {selectedId && !selected && (
                <option value={selectedId}>Saved dataset unavailable</option>
              )}
              {datasets
                .filter((item) => item.status === "complete")
                .map((dataset) => (
                  <option key={dataset.id} value={dataset.id}>
                    {dataset.name} — {dataset.item_count} observations — schema
                    revision {dataset.pose_schema_revision}
                  </option>
                ))}
            </select>
            <SourcePin
              pinned={String(node.parameters?.manifest_sha256 ?? "")}
              current={selected?.manifest_sha256}
            />
          </label>
        );
      })}
      {videos.map((node) => {
        const selectedId = String(node.parameters?.video_id ?? "");
        const selected = recordings.find((item) => item.id === selectedId);
        const heading = label(node);
        return (
          <label key={node.node_id}>
            {heading}
            <select
              aria-label={heading}
              value={selectedId}
              onChange={(event) => {
                const item = recordings.find(
                  ({ id }) => id === event.target.value,
                );
                onPick(node.node_id, item?.id ?? "", item?.sha256 ?? "");
              }}
            >
              <option value="">Choose a managed original recording</option>
              {selectedId && !selected && (
                <option value={selectedId}>Saved recording unavailable</option>
              )}
              {recordings.map((video) => (
                <option key={video.id} value={video.id}>
                  {video.original_filename}
                </option>
              ))}
            </select>
            <SourcePin
              pinned={String(node.parameters?.video_sha256 ?? "")}
              current={selected?.sha256}
            />
          </label>
        );
      })}
    </>
  );
}
