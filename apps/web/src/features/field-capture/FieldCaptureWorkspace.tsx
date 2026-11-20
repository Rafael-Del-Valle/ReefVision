import {
  useIsMutating,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useRef, useState, type FormEvent } from "react";

import { saveWorkflowGraph } from "../workflow-graphs/workflowGraphApi";
import { FieldCaptureObservationForm } from "./FieldCaptureObservationForm";
import {
  FieldEvidence,
  FieldReconciliationPanel,
} from "./FieldReconciliationPanel";
import {
  createFieldBatch,
  fieldBatchDownload,
  fieldOriginalDownload,
  getFieldBatch,
  importFieldBatch,
  listFieldBatches,
  sealFieldBatch,
  type FieldBatch,
} from "./fieldCaptureApi";
import "./fieldCapture.css";

type FieldNavigation = { onOpenQC: () => void; onOpenWorkflow: () => void };

function FieldBatchDetails({
  projectId,
  batchId,
  onOpenQC,
  onOpenWorkflow,
}: FieldNavigation & {
  projectId: string;
  batchId: string;
}) {
  const queryClient = useQueryClient();
  const key = ["field-batch", projectId, batchId];
  const capturing =
    useIsMutating({
      mutationKey: ["field-capture-upload", projectId, batchId],
    }) > 0;
  const batch = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => getFieldBatch(projectId, batchId, signal),
  });
  const seal = useMutation({
    mutationFn: () => sealFieldBatch(projectId, batchId),
    onSuccess: async (saved) => {
      queryClient.setQueryData(key, saved);
      await queryClient.invalidateQueries({
        queryKey: ["field-batches", projectId],
      });
    },
  });
  const graph = useMutation({
    mutationFn: (source: FieldBatch) =>
      saveWorkflowGraph(projectId, {
        graph_id: `field-capture-${source.id}`,
        name: `Field capture · ${source.label}`.slice(0, 120),
        nodes: [
          { node_id: "project", node_type: "project_source" },
          {
            node_id: "reconcile",
            node_type: "field_capture_reconcile",
            parameters: {
              batch_id: source.id,
              manifest_sha256: source.manifest_sha256,
            },
          },
        ],
        edges: [
          {
            edge_id: "project-reconcile",
            source_node_id: "project",
            source_port_id: "project",
            target_node_id: "reconcile",
            target_port_id: "project",
          },
        ],
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ["workflow-graphs", projectId],
      }),
  });

  if (batch.isPending) return <p role="status">Loading field batch…</p>;
  if (batch.error) return <p role="alert">{batch.error.message}</p>;
  const current = batch.data;
  if (!current) return null;

  return (
    <section className="field-capture-section" aria-label={current.label}>
      <h3>{current.label}</h3>
      <p>
        {current.manifest_sha256 ? "Sealed" : "Draft"} ·{" "}
        {current.observations.length} observations
      </p>
      {current.origin_project_id !== current.project_id && (
        <details>
          <summary>Originating field batch</summary>
          <code>{current.origin_batch_id}</code>
        </details>
      )}
      {current.manifest_sha256 ? (
        <div className="button-row">
          <a href={fieldBatchDownload(projectId, batchId)}>
            Download field batch
          </a>
          <button
            type="button"
            disabled={graph.isPending}
            onClick={() => graph.mutate(current)}
          >
            Save field workflow
          </button>
          {graph.isSuccess && (
            <button type="button" onClick={onOpenWorkflow}>
              Open saved workflows
            </button>
          )}
        </div>
      ) : (
        <>
          <FieldCaptureObservationForm
            projectId={projectId}
            batchId={batchId}
            disabled={seal.isPending}
          />
          <p>
            Seal the batch to make it portable and ready for reconciliation.
          </p>
          <button
            type="button"
            disabled={
              seal.isPending || capturing || !current.observations.length
            }
            onClick={() => seal.mutate()}
          >
            {seal.isPending ? "Sealing…" : "Seal field batch"}
          </button>
        </>
      )}
      {(seal.error || graph.error) && (
        <p role="alert">{(seal.error || graph.error)?.message}</p>
      )}
      {current.observations.length > 0 && (
        <ul className="field-capture-list" aria-label="Captured observations">
          {current.observations.map((observation) => (
            <li key={observation.id}>
              <h4>{observation.filename}</h4>
              <p>
                {observation.captured_at_utc
                  ? `Capture UTC ${observation.captured_at_utc}`
                  : "Capture UTC unknown"}
              </p>
              <FieldEvidence evidence={observation} />
              <a
                href={fieldOriginalDownload(projectId, batchId, observation.id)}
              >
                Download original
              </a>
            </li>
          ))}
        </ul>
      )}
      {current.manifest_sha256 && (
        <FieldReconciliationPanel batch={current} onOpenQC={onOpenQC} />
      )}
    </section>
  );
}

export function FieldCaptureWorkspace({
  projectId,
  onOpenQC,
  onOpenWorkflow,
}: FieldNavigation & { projectId: string }) {
  const client = useQueryClient();
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<string | null>(null);
  const [label, setLabel] = useState("");
  const archiveForm = useRef<HTMLFormElement>(null);
  const batches = useQuery({
    queryKey: ["field-batches", projectId, page],
    queryFn: ({ signal }) => listFieldBatches(projectId, page, signal),
  });

  async function openBatch(batch: FieldBatch) {
    client.setQueryData(["field-batch", projectId, batch.id], batch);
    setPage(1);
    setSelected(batch.id);
    await client.invalidateQueries({ queryKey: ["field-batches", projectId] });
  }

  const create = useMutation({
    mutationFn: (name: string) => createFieldBatch(projectId, name),
    onSuccess: (batch) => {
      setLabel("");
      return openBatch(batch);
    },
  });
  const portable = useMutation({
    mutationFn: (file: File) => importFieldBatch(projectId, file),
    onSuccess: ({ batch }) => {
      archiveForm.current?.reset();
      return openBatch(batch);
    },
  });

  function importArchive(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const file = new FormData(event.currentTarget).get("archive");
    if (file instanceof File && file.size && !portable.isPending)
      portable.mutate(file);
  }

  return (
    <section
      className="panel field-capture-workspace"
      aria-label="Field capture workspace"
    >
      <h2>Field capture</h2>
      <p>
        Record local images and video with the source clock and field
        observations.
      </p>
      <div className="field-capture-grid">
        <form
          aria-label="New field batch"
          onSubmit={(event) => {
            event.preventDefault();
            if (label.trim() && !create.isPending) create.mutate(label.trim());
          }}
        >
          <label>
            Batch name
            <input
              required
              maxLength={200}
              value={label}
              onChange={(event) => setLabel(event.target.value)}
            />
          </label>
          <button type="submit" disabled={create.isPending}>
            Create field batch
          </button>
          {create.error && <p role="alert">{create.error.message}</p>}
        </form>
        <form
          aria-label="Import portable field batch"
          ref={archiveForm}
          onSubmit={importArchive}
        >
          <label>
            Local field batch archive
            <input
              type="file"
              name="archive"
              accept=".zip,application/zip"
              required
            />
          </label>
          <button type="submit" disabled={portable.isPending}>
            {portable.isPending ? "Importing…" : "Import field batch"}
          </button>
          {portable.error && <p role="alert">{portable.error.message}</p>}
          {portable.data && (
            <p role="status">
              {portable.data.duplicate
                ? "This field batch was already imported."
                : "Field batch imported."}
            </p>
          )}
        </form>
      </div>
      <section
        className="field-capture-section"
        aria-label="Saved field batches"
      >
        <h3>Saved batches</h3>
        {batches.error && <p role="alert">{batches.error.message}</p>}
        {batches.isPending && <p role="status">Loading field batches…</p>}
        {batches.data?.total === 0 && <p>No field batches yet.</p>}
        {!!batches.data?.items.length && (
          <ul className="field-capture-list">
            {batches.data.items.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  aria-pressed={selected === item.id}
                  aria-label={`Open batch ${item.label}`}
                  onClick={() => setSelected(item.id)}
                >
                  {item.label}
                </button>
                <span> {item.manifest_sha256 ? "Sealed" : "Draft"}</span>
              </li>
            ))}
          </ul>
        )}
        {batches.data && batches.data.total > batches.data.page_size && (
          <div className="button-row">
            <button
              type="button"
              disabled={page === 1}
              onClick={() => setPage(page - 1)}
            >
              Previous batches
            </button>
            <span>Page {page}</span>
            <button
              type="button"
              disabled={page * batches.data.page_size >= batches.data.total}
              onClick={() => setPage(page + 1)}
            >
              Next batches
            </button>
          </div>
        )}
      </section>
      {selected && (
        <FieldBatchDetails
          key={selected}
          projectId={projectId}
          batchId={selected}
          onOpenQC={onOpenQC}
          onOpenWorkflow={onOpenWorkflow}
        />
      )}
    </section>
  );
}
