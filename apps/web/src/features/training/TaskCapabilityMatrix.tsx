import { useQuery } from "@tanstack/react-query";

type Capability = {
  task_id: string;
  display_name: string;
  media: string[];
  annotation_kinds: string[];
  providers: string[];
  supports_training: boolean;
  supports_inference: boolean;
  state: "ready" | "foundation" | "blocked" | "planned";
  notes: string;
};

async function loadCapabilities(signal: AbortSignal): Promise<Capability[]> {
  const response = await fetch("/api/v1/capabilities/tasks", { signal });
  if (!response.ok) {
    throw new Error(`Capability request failed: ${response.status}`);
  }
  return response.json() as Promise<Capability[]>;
}

export function TaskCapabilityMatrix() {
  const query = useQuery({
    queryKey: ["task-capabilities"],
    queryFn: ({ signal }) => loadCapabilities(signal),
    staleTime: 60_000,
  });

  if (query.isPending) return <p>Loading task capabilities...</p>;
  if (query.error) return <p className="form-error">{query.error.message}</p>;

  return (
    <article className="system-card">
      <h4>Tasks and implementation status</h4>
      <div className="annotation-selection-list">
        {query.data?.map((task) => (
          <div className="annotation-selection-row" key={task.task_id}>
            <div>
              <strong>{task.display_name}</strong>
              <small>{task.notes}</small>
            </div>
            <div>
              <span className="status-chip">{task.state}</span>
              <small>
                {task.supports_training ? "Train" : "No training"} Â·{" "}
                {task.supports_inference ? "Run" : "No inference"}
              </small>
            </div>
          </div>
        ))}
      </div>
    </article>
  );
}
