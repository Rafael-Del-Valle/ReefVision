import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { useActionConfirmation } from "../../components/ui/ActionConfirmation";
import {
  fieldOriginalDownload,
  listFieldBatches,
} from "../field-capture/fieldCaptureApi";
import { saveWorkflowGraph } from "../workflow-graphs/workflowGraphApi";
import {
  captureAcquisition,
  changeAcquisitionSource,
  createAcquisitionSource,
  getAcquisitionCapture,
  getAcquisitionSource,
  listAcquisitionCaptures,
  listAcquisitionSources,
  type AcquisitionReceipt,
  type AcquisitionSource,
  type AcquisitionStateAction,
  type SourceConfiguration,
} from "./acquisitionSourceApi";
import "../field-capture/fieldCapture.css";

const sourceNames = {
  recorded: "Recorded field batch",
  simulated: "Simulated source",
  camera: "Local camera",
};

function Pages({
  page,
  count,
  size,
  setPage,
}: {
  page: number;
  count: number;
  size: number;
  setPage: (page: number) => void;
}) {
  if (count <= size) return null;
  return (
    <div className="button-row">
      <button
        type="button"
        disabled={page <= 1}
        onClick={() => setPage(page - 1)}
      >
        Previous page
      </button>
      <span>
        Page {page} of {Math.ceil(count / size)}
      </span>
      <button
        type="button"
        disabled={page * size >= count}
        onClick={() => setPage(page + 1)}
      >
        Next page
      </button>
    </div>
  );
}

function SourceForm({
  projectId,
  onCreated,
}: {
  projectId: string;
  onCreated: (source: AcquisitionSource) => void;
}) {
  const [kind, setKind] = useState<SourceConfiguration["kind"]>("simulated");
  const [label, setLabel] = useState("");
  const [batchId, setBatchId] = useState("");
  const [batchPage, setBatchPage] = useState(1);
  const [seed, setSeed] = useState("7");
  const [epoch, setEpoch] = useState("");
  const [period, setPeriod] = useState("30");
  const [cameraIndex, setCameraIndex] = useState("");
  const batches = useQuery({
    queryKey: ["field-batches", projectId, batchPage],
    queryFn: ({ signal }) => listFieldBatches(projectId, batchPage, signal),
    enabled: kind === "recorded",
  });
  const sealed =
    batches.data?.items.filter((batch) => batch.manifest_sha256) ?? [];
  const create = useMutation({
    mutationFn: (configuration: SourceConfiguration) =>
      createAcquisitionSource(projectId, label, configuration),
    onSuccess: (source) => {
      setLabel("");
      onCreated(source);
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    switch (kind) {
      case "recorded": {
        const batch = sealed.find((row) => row.id === batchId);
        if (batch?.manifest_sha256) {
          create.mutate({
            kind,
            batch_id: batch.id,
            manifest_sha256: batch.manifest_sha256,
          });
        }
        break;
      }
      case "simulated":
        create.mutate({
          kind,
          seed: Number(seed),
          start_at_utc: new Date(epoch + "Z").toISOString(),
          period_seconds: Number(period),
        });
        break;
      case "camera":
        create.mutate({ kind, camera_index: Number(cameraIndex) });
        break;
    }
  }

  return (
    <section
      className="field-capture-section"
      aria-label="Add an acquisition source"
    >
      <h3>Add a source</h3>
      <form onSubmit={submit}>
        <div className="field-capture-grid">
          <label>
            Source name
            <input
              required
              maxLength={200}
              value={label}
              onChange={(event) => setLabel(event.target.value)}
            />
          </label>
          <label>
            Source type
            <select
              value={kind}
              onChange={(event) =>
                setKind(event.target.value as SourceConfiguration["kind"])
              }
            >
              {Object.entries(sourceNames).map(([value, name]) => (
                <option key={value} value={value}>
                  {name}
                </option>
              ))}
            </select>
          </label>
        </div>
        {kind === "recorded" && (
          <>
            <label>
              Sealed field batch
              <select
                required
                value={batchId}
                onChange={(event) => setBatchId(event.target.value)}
              >
                <option value="">Choose a sealed batch</option>
                {sealed.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.label}
                  </option>
                ))}
              </select>
            </label>
            {batches.error && <p role="alert">{batches.error.message}</p>}
            {batches.data && sealed.length === 0 && (
              <p>
                No sealed batches on this page. Add and seal originals in Field
                Capture.
              </p>
            )}
            {batches.data && (
              <Pages
                page={batchPage}
                count={batches.data.total}
                size={batches.data.page_size}
                setPage={(page) => {
                  setBatchId("");
                  setBatchPage(page);
                }}
              />
            )}
          </>
        )}
        {kind === "simulated" && (
          <div className="field-capture-grid">
            <label>
              Simulation seed
              <input
                required
                type="number"
                min={0}
                max={4294967295}
                value={seed}
                onChange={(event) => setSeed(event.target.value)}
              />
            </label>
            <label>
              First timestamp (UTC)
              <input
                required
                type="datetime-local"
                value={epoch}
                onChange={(event) => setEpoch(event.target.value)}
              />
            </label>
            <label>
              Seconds per simulated observation
              <input
                required
                type="number"
                min={1}
                max={86400}
                value={period}
                onChange={(event) => setPeriod(event.target.value)}
              />
            </label>
          </div>
        )}
        {kind === "camera" && (
          <>
            <label>
              Local camera index
              <input
                required
                type="number"
                min={0}
                max={15}
                value={cameraIndex}
                onChange={(event) => setCameraIndex(event.target.value)}
              />
            </label>
            <p>
              Adding a camera records your selection. A later approval allows
              captures for 15 minutes.
            </p>
          </>
        )}
        {create.error && <p role="alert">{create.error.message}</p>}
        <div className="button-row">
          <button type="submit" disabled={create.isPending}>
            Add source
          </button>
        </div>
      </form>
    </section>
  );
}

function savePinnedGraph(
  projectId: string,
  key: string,
  name: string,
  node_type: string,
  parameters: Record<string, string>,
) {
  return saveWorkflowGraph(projectId, {
    graph_id: key,
    name: name.slice(0, 120),
    nodes: [
      { node_id: "project", node_type: "project_source" },
      { node_id: "acquisition", node_type, parameters },
    ],
    edges: [
      {
        edge_id: "project-acquisition",
        source_node_id: "project",
        source_port_id: "project",
        target_node_id: "acquisition",
        target_port_id: "project",
      },
    ],
  });
}

function CaptureEvidence({
  capture,
  label,
}: {
  capture: AcquisitionReceipt;
  label: string;
}) {
  const item = capture.receipt;
  const cache = useQueryClient();
  const save = useMutation({
    mutationFn: async () => {
      const pinned = await getAcquisitionCapture(
        item.project_id,
        item.source_id,
        item.id,
      );
      return savePinnedGraph(
        item.project_id,
        "acquisition-receipt-" + item.id,
        "Acquisition receipt · " + label,
        "acquisition_capture_replay",
        { capture_id: item.id, content_sha256: pinned.content_sha256 },
      );
    },
    onSuccess: () =>
      cache.invalidateQueries({
        queryKey: ["workflow-graphs", item.project_id],
      }),
  });
  return (
    <article
      className="field-capture-section"
      aria-label={"Observation " + (item.ordinal + 1)}
    >
      <h4>Observation {item.ordinal + 1}</h4>
      <dl className="field-capture-evidence">
        <dt>Capture ID</dt>
        <dd>
          <code>{item.id}</code>
        </dd>
        <dt>Capture time (UTC)</dt>
        <dd>{item.time.captured_at_utc ?? "Unknown"}</dd>
        <dt>Time uncertainty</dt>
        <dd>
          {item.time.uncertainty_seconds === null
            ? "Unknown"
            : item.time.uncertainty_seconds + " s"}
        </dd>
        {item.time.host_received_at_utc && (
          <>
            <dt>Host receipt (UTC)</dt>
            <dd>{item.time.host_received_at_utc}</dd>
          </>
        )}
        {item.time.host_read_elapsed_seconds !== null && (
          <>
            <dt>Driver read elapsed</dt>
            <dd>{item.time.host_read_elapsed_seconds} s</dd>
          </>
        )}
        <dt>Clock evidence</dt>
        <dd>{item.time.clock.evidence}</dd>
        {item.synthetic_reading && (
          <>
            <dt>Simulation reading</dt>
            <dd>
              {item.synthetic_reading.value} {item.synthetic_reading.unit}
            </dd>
          </>
        )}
        <dt>Original identity</dt>
        <dd>
          <code>{item.media.original_observation_id}</code>
        </dd>
        <dt>Original SHA-256</dt>
        <dd>
          <code>{item.media.sha256}</code>
        </dd>
        <dt>Receipt SHA-256</dt>
        <dd>
          <code>{capture.content_sha256}</code>
        </dd>
        {item.dispatch.occurrence_id && (
          <>
            <dt>Schedule occurrence</dt>
            <dd>
              <code>{item.dispatch.occurrence_id}</code>
            </dd>
          </>
        )}
      </dl>
      <div className="button-row">
        <a
          href={fieldOriginalDownload(
            item.project_id,
            item.media.field_batch_id,
            item.media.field_observation_id,
          )}
        >
          Download original
        </a>
        <button
          className="secondary"
          type="button"
          onClick={() => save.mutate()}
          disabled={save.isPending}
        >
          Save receipt workflow
        </button>
      </div>
      {save.error && <p role="alert">{save.error.message}</p>}
      {save.isSuccess && (
        <p role="status">
          Receipt workflow saved. Open it in Workflow Builder to verify this
          observation.
        </p>
      )}
    </article>
  );
}

function SourceDetails({
  projectId,
  sourceId,
}: {
  projectId: string;
  sourceId: string;
}) {
  const [page, setPage] = useState(1);
  const cache = useQueryClient();
  const { confirm, confirmationDialog } = useActionConfirmation();
  const sourceKey = ["acquisition-source", projectId, sourceId];
  const capturesKey = ["acquisition-captures", projectId, sourceId];
  const current = useQuery({
    queryKey: sourceKey,
    queryFn: ({ signal }) => getAcquisitionSource(projectId, sourceId, signal),
    refetchInterval: 3000,
  });
  const captures = useQuery({
    queryKey: [...capturesKey, page],
    queryFn: ({ signal }) =>
      listAcquisitionCaptures(projectId, sourceId, page, signal),
    refetchInterval: 3000,
  });
  const refresh = () =>
    Promise.all([
      cache.invalidateQueries({ queryKey: sourceKey }),
      cache.invalidateQueries({ queryKey: ["acquisition-sources", projectId] }),
      cache.invalidateQueries({ queryKey: capturesKey }),
    ]);
  const transition = useMutation({
    mutationFn: ({
      source,
      action,
    }: {
      source: AcquisitionSource;
      action: AcquisitionStateAction;
    }) => changeAcquisitionSource(projectId, source, action),
    onSettled: refresh,
  });
  const pendingKey =
    "reefvision.acquisition.pending." + projectId + "." + sourceId;
  const capture = useMutation({
    mutationFn: ({
      source,
      camera,
    }: {
      source: AcquisitionSource;
      camera: boolean;
    }) => {
      const key = sessionStorage.getItem(pendingKey) ?? crypto.randomUUID();
      sessionStorage.setItem(pendingKey, key);
      return captureAcquisition(projectId, source, key, camera);
    },
    onSuccess: () => {
      sessionStorage.removeItem(pendingKey);
      setPage(1);
    },
    onSettled: refresh,
  });
  const save = useMutation({
    mutationFn: (source: AcquisitionSource) =>
      savePinnedGraph(
        projectId,
        "acquisition-source-" + source.id,
        "Capture source · " + source.label,
        "acquisition_source_capture",
        { source_id: source.id, source_sha256: source.source_sha256 },
      ),
    onSuccess: () =>
      Promise.all([
        cache.invalidateQueries({ queryKey: ["workflow-graphs", projectId] }),
        cache.invalidateQueries({
          queryKey: ["saved-workflow-graphs", projectId],
        }),
      ]),
  });

  if (current.error) return <p role="alert">{current.error.message}</p>;
  const source = current.data;
  if (!source) return <p role="status">Loading source…</p>;
  const camera = source.configuration.kind === "camera";
  const approved = Boolean(
    source.local_consent_until &&
    Date.parse(source.local_consent_until) > Date.now(),
  );
  const busy = capture.isPending || transition.isPending;
  const stateError = transition.error ?? capture.error;

  async function collect() {
    if (!source) return;
    if (
      camera &&
      !(await confirm({
        title: "Capture one camera frame?",
        message:
          "ReefVision will open the approved local camera and save one frame in this project.",
        confirmLabel: "Capture frame",
      }))
    )
      return;
    transition.reset();
    capture.mutate({ source, camera });
  }

  async function change(action: AcquisitionStateAction) {
    if (!source) return;
    if (
      action === "approve_camera" &&
      !(await confirm({
        title: "Approve this local camera?",
        message:
          "For 15 minutes, this project’s explicit captures and matching acquisition schedules can open the selected camera. You can revoke approval at any time.",
        confirmLabel: "Approve camera",
      }))
    )
      return;
    capture.reset();
    transition.mutate({ source, action });
  }

  return (
    <section
      className="field-capture-section"
      aria-label={source.label + " acquisition source"}
    >
      <h3>{source.label}</h3>
      <p role="status">
        {sourceNames[source.configuration.kind]} · {source.state} ·{" "}
        {source.cursor} captured
      </p>
      <dl className="field-capture-evidence">
        <dt>Source ID</dt>
        <dd>
          <code>{source.id}</code>
        </dd>
        <dt>Source SHA-256</dt>
        <dd>
          <code>{source.source_sha256}</code>
        </dd>
        {source.configuration.kind === "recorded" && (
          <>
            <dt>Sealed field batch</dt>
            <dd>
              <code>{source.configuration.batch_id}</code>
            </dd>
          </>
        )}
        {source.configuration.kind === "camera" && (
          <>
            <dt>Camera index</dt>
            <dd>{source.configuration.camera_index}</dd>
          </>
        )}
        {camera && (
          <>
            <dt>Camera approval</dt>
            <dd>
              {approved
                ? "Active until " + source.local_consent_until
                : "Approval required"}
            </dd>
          </>
        )}
        {source.next_retry_at && (
          <>
            <dt>Reconnect after (UTC)</dt>
            <dd>{source.next_retry_at}</dd>
          </>
        )}
      </dl>
      {source.last_error && <p role="alert">{source.last_error}</p>}
      {stateError && stateError.message !== source.last_error && (
        <p role="alert">{stateError.message}</p>
      )}
      <div className="button-row">
        <button
          type="button"
          disabled={busy || source.state !== "ready" || (camera && !approved)}
          onClick={() => void collect()}
        >
          Capture once
        </button>
        {source.state === "ready" && (
          <button
            className="secondary"
            type="button"
            disabled={busy}
            onClick={() => void change("pause")}
          >
            Pause source
          </button>
        )}
        {source.state === "paused" && (
          <button
            className="secondary"
            type="button"
            disabled={busy}
            onClick={() => void change("resume")}
          >
            Resume source
          </button>
        )}
        {source.state === "disconnected" && (
          <button
            className="secondary"
            type="button"
            disabled={busy}
            onClick={() => void change("resume")}
          >
            Reconnect source
          </button>
        )}
        {camera && source.state === "ready" && !approved && (
          <button
            className="secondary"
            type="button"
            disabled={busy}
            onClick={() => void change("approve_camera")}
          >
            Approve camera
          </button>
        )}
        {camera && approved && (
          <button
            className="secondary"
            type="button"
            disabled={busy}
            onClick={() => void change("revoke_camera")}
          >
            Revoke camera approval
          </button>
        )}
        <button
          className="secondary"
          type="button"
          disabled={save.isPending}
          onClick={() => save.mutate(source)}
        >
          Save capture workflow
        </button>
      </div>
      {save.error && <p role="alert">{save.error.message}</p>}
      {save.isSuccess && (
        <p role="status">
          Capture workflow saved. Select it in Schedules under Acquisition.
        </p>
      )}
      <h4>Capture history</h4>
      {captures.error && <p role="alert">{captures.error.message}</p>}
      {captures.data?.total === 0 && <p>No observations captured yet.</p>}
      {captures.data?.items.map((item) => (
        <CaptureEvidence
          key={item.receipt.id}
          capture={item}
          label={source.label}
        />
      ))}
      {captures.data && (
        <Pages
          page={page}
          count={captures.data.total}
          size={captures.data.page_size}
          setPage={setPage}
        />
      )}
      {confirmationDialog}
    </section>
  );
}

export function AcquisitionSourcesWorkspace({
  projectId,
}: {
  projectId: string;
}) {
  const [selection, setSelection] = useState<{
    projectId: string;
    sourceId: string;
  }>();
  const sourceId = selection?.projectId === projectId ? selection.sourceId : "";
  const [page, setPage] = useState(1);
  const cache = useQueryClient();
  const sources = useQuery({
    queryKey: ["acquisition-sources", projectId, page],
    queryFn: ({ signal }) => listAcquisitionSources(projectId, page, signal),
  });

  return (
    <section
      className="field-capture-workspace"
      aria-label="Acquisition sources workspace"
    >
      <h2>Acquisition sources</h2>
      <SourceForm
        key={projectId}
        projectId={projectId}
        onCreated={(source) => {
          setSelection({ projectId, sourceId: source.id });
          setPage(1);
          void cache.invalidateQueries({
            queryKey: ["acquisition-sources", projectId],
          });
        }}
      />
      {sources.error && <p role="alert">{sources.error.message}</p>}
      <div className="button-row" aria-label="Saved acquisition sources">
        {sources.data?.items.map((row) => (
          <button
            className="secondary"
            type="button"
            key={row.id}
            aria-pressed={sourceId === row.id}
            onClick={() => setSelection({ projectId, sourceId: row.id })}
          >
            {row.label}
          </button>
        ))}
      </div>
      {sources.data && (
        <Pages
          page={page}
          count={sources.data.total}
          size={sources.data.page_size}
          setPage={setPage}
        />
      )}
      {sourceId && (
        <SourceDetails
          key={projectId + ":" + sourceId}
          projectId={projectId}
          sourceId={sourceId}
        />
      )}
    </section>
  );
}
