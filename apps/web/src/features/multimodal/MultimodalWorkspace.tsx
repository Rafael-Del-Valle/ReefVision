import { useState } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { request } from "../../api/client";
import { getApiBaseUrl } from "../../runtime";
import { saveWorkflowGraph } from "../workflow-graphs/workflowGraphApi";

interface Option {
  id: string;
  label: string;
  digest: string;
}
interface Summary {
  id: string;
  name: string;
  content_sha256: string;
  status: "available" | "withheld";
}
interface Exposure {
  index: string;
  box: string;
  start: string;
  end: string;
  uncertainty: string;
  dx: string;
  dy: string;
  clock: string;
  registration: string;
}
interface Outcome {
  exposure: string;
  roi_mean: number | null;
  valid_pixels: number;
  grid_error_px: number | null;
  index_sha256: string;
}
interface Study extends Summary {
  snapshot: {
    result: {
      status: "available" | "withheld";
      reasons: string[];
      observations: Outcome[];
      optical_sources?: {
        sensor: string;
        acquisition_sha256: string;
        bands: {
          role: string;
          name: string;
          wavelength_nm: number;
          calibration: { reference: string } | null;
        }[];
      }[];
      exposed_minus_control: number | null;
      unit: string;
    };
    reviewer: { name: string };
    request: {
      event_label: string;
      footprint: { grid: string; station: string };
      exposures: { start_utc: string; end_utc: string }[];
    };
    boxes: {
      organism_key: string;
      organism_revision: number;
      bounds_xyxy: number[];
    }[];
  };
}
const emptyExposure = (): Exposure => ({
  index: "",
  box: "",
  start: "",
  end: "",
  uncertainty: "",
  dx: "0",
  dy: "0",
  clock: "",
  registration: "",
});

function usePages<T>(url: string, key: string) {
  return useInfiniteQuery({
    queryKey: ["multimodal", key, url],
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      request<T[]>(
        url + (url.includes("?") ? "&" : "?") + "limit=50&offset=" + pageParam,
        { signal },
      ),
    getNextPageParam: (last, pages) =>
      last.length === 50 ? pages.length * 50 : undefined,
  });
}
function SourceSelect({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: Option[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label>
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Choose source</option>
        {options.map((row) => (
          <option key={row.id} value={row.id}>
            {row.label}
          </option>
        ))}
      </select>
    </label>
  );
}
function Field({
  label,
  value,
  set,
  numeric = false,
}: {
  label: string;
  value: string;
  set: (v: string) => void;
  numeric?: boolean;
}) {
  return (
    <label>
      {label}
      <input
        type={numeric ? "number" : "text"}
        step={numeric ? "any" : undefined}
        value={value}
        onChange={(e) => set(e.target.value)}
      />
    </label>
  );
}

export function MultimodalWorkspace({ projectId }: { projectId: string }) {
  const base = "/projects/" + encodeURIComponent(projectId) + "/multimodal";
  const cache = useQueryClient();
  const audio = usePages<Option>(base + "/sources?kind=audio", "audio");
  const indexes = usePages<Option>(base + "/sources?kind=index", "indexes");
  const boxes = usePages<Option>(base + "/sources?kind=box", "boxes");
  const studies = usePages<Summary>(base + "/studies", "studies");
  const allAudio = audio.data?.pages.flat() ?? [],
    allIndex = indexes.data?.pages.flat() ?? [],
    allBoxes = boxes.data?.pages.flat() ?? [];
  const [name, setName] = useState("Paired station survey");
  const [audioId, setAudioId] = useState("");
  const [event, setEvent] = useState("");
  const [channel, setChannel] = useState("0");
  const [clockLimit, setClockLimit] = useState("");
  const [full, setFull] = useState(false);
  const [coverage, setCoverage] = useState("");
  const [common, setCommon] = useState("");
  const [station, setStation] = useState("");
  const [bounds, setBounds] = useState(["", "", "", ""]);
  const [error, setError] = useState("");
  const [limit, setLimit] = useState("");
  const [proof, setProof] = useState("");
  const [identity, setIdentity] = useState("uncertain");
  const [identityProof, setIdentityProof] = useState("");
  const [role, setRole] = useState("");
  const [exposures, setExposures] = useState([
    emptyExposure(),
    emptyExposure(),
  ]);
  const [detail, setDetail] = useState<Study | null>(null);
  const selectExposure = (i: number, key: keyof Exposure, v: string) =>
    setExposures((previous) =>
      previous.map((item, index) =>
        index === i ? { ...item, [key]: v } : item,
      ),
    );
  const selectBound = (i: number, v: string) =>
    setBounds((previous) =>
      previous.map((item, index) => (index === i ? v : item)),
    );
  const create = useMutation({
    mutationFn: () =>
      request<Study>(base + "/studies", {
        method: "POST",
        headers: { Authorization: "Bearer " + role },
        body: JSON.stringify({
          operation_id: crypto.randomUUID(),
          name,
          audio_report_id: audioId,
          audio_report_sha256: allAudio.find((a) => a.id === audioId)?.digest,
          event_label: event,
          channel: Number(channel),
          maximum_time_uncertainty_us: Number(clockLimit),
          full_recording_reviewed: full,
          coverage_evidence: coverage,
          identity_review: identity,
          identity_evidence: identityProof,
          footprint: {
            station,
            grid: common,
            bounds_xyxy: bounds.map(Number),
            registration_error_px: Number(error),
            maximum_total_error_px: Number(limit),
            evidence: proof,
          },
          exposures: exposures.map((e) => ({
            index_id: e.index,
            index_sha256: allIndex.find((i) => i.id === e.index)?.digest,
            annotation_evidence_id: e.box,
            start_utc: e.start,
            end_utc: e.end,
            uncertainty_us: Number(e.uncertainty),
            clock_evidence: e.clock,
            station_grid_offset_xy: [Number(e.dx), Number(e.dy)],
            registration_evidence: e.registration,
          })),
        }),
      }),
    onSuccess: (study) => {
      setDetail(study);
      setRole("");
      void cache.invalidateQueries({ queryKey: ["multimodal", "studies"] });
    },
  });
  const open = useMutation({
    mutationFn: (id: string) => request<Study>(base + "/studies/" + id),
    onSuccess: setDetail,
  });
  const replay = useMutation({
    mutationFn: (s: Study) =>
      request<Study>(base + "/studies/" + s.id + "/replay", {
        method: "POST",
        body: JSON.stringify({ study_sha256: s.content_sha256 }),
      }),
    onSuccess: setDetail,
  });
  const graph = useMutation({
    mutationFn: (s: Study) =>
      saveWorkflowGraph(projectId, {
        graph_id: "multimodal-" + s.id,
        name: "Replay " + s.name,
        nodes: [
          { node_id: "project", node_type: "project_source" },
          {
            node_id: "survey",
            node_type: "multimodal_study_replay",
            parameters: { study_id: s.id, study_sha256: s.content_sha256 },
          },
        ],
        edges: [
          {
            edge_id: "project-survey",
            source_node_id: "project",
            source_port_id: "project",
            target_node_id: "survey",
            target_port_id: "project",
          },
        ],
      }),
  });
  const complete = [
    name,
    audioId,
    event,
    channel,
    clockLimit,
    coverage,
    common,
    station,
    ...bounds,
    error,
    limit,
    proof,
    identityProof,
    role,
    ...exposures.flatMap((e) => Object.values(e)),
  ].every((v) => v.trim().length > 0);
  const errors = [
    audio.error,
    indexes.error,
    boxes.error,
    studies.error,
    open.error,
    create.error,
    replay.error,
    graph.error,
  ].filter(Boolean);
  return (
    <section className="panel-card" aria-label="Multimodal analysis">
      <h3>Multimodal analysis</h3>
      <p>
        Compare calibrated reflectance inside two reviewed organism boxes during
        and outside a reviewed acoustic event at the same station.
      </p>
      <Field label="Study name" value={name} set={setName} />
      <fieldset>
        <legend>Acoustic coverage</legend>
        <SourceSelect
          label="Frozen acoustic report"
          options={allAudio}
          value={audioId}
          onChange={setAudioId}
        />
        <Field label="Reviewed event label" value={event} set={setEvent} />
        <Field
          label="Acoustic channel (zero-based)"
          numeric
          value={channel}
          set={setChannel}
        />
        <Field
          label="Maximum combined clock uncertainty (µs)"
          numeric
          value={clockLimit}
          set={setClockLimit}
        />
        <label>
          <input
            type="checkbox"
            checked={full}
            onChange={(e) => setFull(e.target.checked)}
          />
          The complete recording was reviewed for this event and channel
        </label>
        <Field
          label="Acoustic review coverage evidence"
          value={coverage}
          set={setCoverage}
        />
      </fieldset>
      <fieldset>
        <legend>Station footprint and common grid</legend>
        <Field label="Station" value={station} set={setStation} />
        <Field label="Reference grid name" value={common} set={setCommon} />
        {["left", "top", "right", "bottom"].map((side, i) => (
          <Field
            key={side}
            label={"Footprint " + side + " (px)"}
            value={bounds[i]}
            numeric
            set={(v) => selectBound(i, v)}
          />
        ))}
        <Field
          label="Footprint registration uncertainty (px)"
          numeric
          value={error}
          set={setError}
        />
        <Field
          label="Maximum total spatial uncertainty (px)"
          numeric
          value={limit}
          set={setLimit}
        />
        <Field label="Footprint evidence" value={proof} set={setProof} />
      </fieldset>
      {exposures.map((e, i) => (
        <fieldset key={i}>
          <legend>Optical observation {i + 1}</legend>
          <p>
            Add the translations to source pixel coordinates to locate this box
            in the station grid.
          </p>
          <SourceSelect
            label="Calibrated index"
            options={allIndex}
            value={e.index}
            onChange={(v) => selectExposure(i, "index", v)}
          />
          <SourceSelect
            label="Reviewed organism box"
            options={allBoxes}
            value={e.box}
            onChange={(v) => selectExposure(i, "box", v)}
          />
          <Field
            label="Exposure start with UTC offset"
            value={e.start}
            set={(v) => selectExposure(i, "start", v)}
          />
          <Field
            label="Exposure end with UTC offset"
            value={e.end}
            set={(v) => selectExposure(i, "end", v)}
          />
          <Field
            label="Exposure time uncertainty (µs)"
            numeric
            value={e.uncertainty}
            set={(v) => selectExposure(i, "uncertainty", v)}
          />
          <Field
            label="Clock evidence"
            value={e.clock}
            set={(v) => selectExposure(i, "clock", v)}
          />
          <Field
            label="Grid translation X (px)"
            numeric
            value={e.dx}
            set={(v) => selectExposure(i, "dx", v)}
          />
          <Field
            label="Grid translation Y (px)"
            numeric
            value={e.dy}
            set={(v) => selectExposure(i, "dy", v)}
          />
          <Field
            label="Translation evidence"
            value={e.registration}
            set={(v) => selectExposure(i, "registration", v)}
          />
        </fieldset>
      ))}
      {[
        ["acoustic reports", audio],
        ["indices", indexes],
        ["organism boxes", boxes],
      ].map(
        ([label, list]) =>
          typeof list !== "string" &&
          list.hasNextPage && (
            <button
              key={String(label)}
              onClick={() => void list.fetchNextPage()}
            >
              Load more {String(label)}
            </button>
          ),
      )}
      <fieldset>
        <legend>Identity review</legend>
        <label>
          Organism correspondence
          <select
            value={identity}
            onChange={(e) => setIdentity(e.target.value)}
          >
            <option>uncertain</option>
            <option>same organism</option>
            <option>different organisms</option>
          </select>
        </label>
        <Field
          label="Identity evidence"
          value={identityProof}
          set={setIdentityProof}
        />
        <label>
          Reviewer Lab role key
          <input
            type="password"
            autoComplete="off"
            value={role}
            onChange={(e) => setRole(e.target.value)}
          />
        </label>
      </fieldset>
      <button
        type="button"
        disabled={!complete || create.isPending}
        onClick={() => create.mutate()}
      >
        Freeze paired study
      </button>
      <label>
        Saved multimodal studies
        <select
          value={detail?.id ?? ""}
          onChange={(e) =>
            e.target.value ? open.mutate(e.target.value) : setDetail(null)
          }
        >
          <option value="">Choose study</option>
          {studies.data?.pages.flat().map((s) => (
            <option key={s.id} value={s.id}>
              {s.name} · {s.status}
            </option>
          ))}
        </select>
      </label>
      {studies.hasNextPage && (
        <button onClick={() => void studies.fetchNextPage()}>
          Load more studies
        </button>
      )}
      {detail && (
        <article aria-label="Paired survey result">
          <h4>{detail.name}</h4>
          <p>
            {detail.snapshot.request.footprint.station} ·{" "}
            {detail.snapshot.request.footprint.grid} · reviewed by{" "}
            {detail.snapshot.reviewer.name}
          </p>
          <table>
            <caption>Paired optical observations</caption>
            <thead>
              <tr>
                {[
                  "Organism",
                  "UTC exposure",
                  "Acoustic coverage",
                  "Valid pixels",
                  "Mean index",
                ].map((x) => (
                  <th key={x}>{x}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {detail.snapshot.result.observations.map((r, i) => (
                <tr key={i}>
                  <td>
                    {detail.snapshot.boxes[i].organism_key} · rev{" "}
                    {detail.snapshot.boxes[i].organism_revision}
                  </td>
                  <td>
                    {detail.snapshot.request.exposures[i].start_utc}–
                    {detail.snapshot.request.exposures[i].end_utc}
                  </td>
                  <td>{r.exposure}</td>
                  <td>{r.valid_pixels}</td>
                  <td>{r.roi_mean?.toFixed(4) ?? "Unavailable"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {detail.snapshot.result.optical_sources && (
            <details>
              <summary>Optical calibration and source records</summary>
              {detail.snapshot.result.optical_sources.map((source, i) => (
                <section key={source.acquisition_sha256}>
                  <h5>
                    Observation {i + 1} · {source.sensor}
                  </h5>
                  <p>
                    Acquisition SHA-256 <code>{source.acquisition_sha256}</code>
                  </p>
                  {source.bands.map((b) => (
                    <p key={b.role}>
                      {b.name} · {b.wavelength_nm} nm · {b.role} band ·{" "}
                      {b.calibration?.reference ?? "Missing panel calibration"}
                    </p>
                  ))}
                </section>
              ))}
            </details>
          )}
          {detail.status === "withheld" ? (
            <>
              <strong>Shared result withheld</strong>
              <ul>
                {detail.snapshot.result.reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </>
          ) : (
            <p>
              Exposed minus control:{" "}
              {detail.snapshot.result.exposed_minus_control?.toFixed(4)} (
              {detail.snapshot.result.unit}).
            </p>
          )}
          <button
            disabled={replay.isPending}
            onClick={() => replay.mutate(detail)}
          >
            Recompute from originals
          </button>
          {replay.data?.id === detail.id && (
            <p role="status">Recomputed the frozen study.</p>
          )}
          <button
            disabled={graph.isPending}
            onClick={() => graph.mutate(detail)}
          >
            Save replay in Workflow Builder
          </button>
          {graph.data && <p role="status">Saved workflow {graph.data.name}.</p>}
          <a
            href={getApiBaseUrl() + base + "/studies/" + detail.id + "/export"}
            download
          >
            Export survey report
          </a>
        </article>
      )}
      {errors.map((e, i) => (
        <p role="alert" key={i}>
          {e instanceof Error ? e.message : "Survey operation failed"}
        </p>
      ))}
    </section>
  );
}
