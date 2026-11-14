import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { request } from "../../api/client";
import { getApiBaseUrl } from "../../runtime";
import { listEventRuns } from "../video/biologicalMovementApi";
import type { PoseEvidenceNavigation } from "../video/videoWorkspaceBridge";
import type { PoseLink } from "./poseOrganismLinksApi";

interface Rate {
  confirmed_complete_count: number;
  valid_duration_s: number;
  confirmed_events_per_minute: number | null;
}

interface Session extends Rate {
  link_revision_id: string;
  organism_key: string;
  video_id: string;
  identity_run_id: string;
  animal_identity_id: string;
  measurement_run_id: string;
  measurement_series_id: string;
  event_run_id: string;
  frame_start: number;
  frame_end: number;
  observed_at: string | null;
  invalid_frame_count: number;
  unreviewed_count: number;
  partial_count: number;
  excluded_confirmed_count: number;
  amplitude_unit: string;
  events: {
    id: string;
    start_frame: number;
    start_time_s: number;
    end_time_s: number;
    duration_s: number;
    amplitude: number | null;
  }[];
}

export interface EventSummary {
  id: string;
  content_sha256: string;
  stale_reasons: string[];
  source_id_map: Record<string, string>;
  snapshot: {
    selection: { name: string; reviewer: string; reason: string };
    method: string;
    protocol_sha256: string;
    sessions: Session[];
    organisms: (Rate & { organism_key: string; session_count: number })[];
    units: (Rate & {
      unit_type: string;
      unit_id: string;
      organism_count: number;
    })[];
  };
}

type Selection = {
  link_revision_id: string;
  event_run_id: string;
  measurement_series_id: string;
  observed_at: string | null;
};

function eventSummaryPath(projectId: string) {
  return `/projects/${projectId}/ecology/event-summaries`;
}

export function getEventSummary(
  projectId: string,
  id: string,
  signal?: AbortSignal,
) {
  return request<EventSummary>(`${eventSummaryPath(projectId)}/${id}`, {
    signal,
  });
}

export function listEventSummaries(projectId: string, signal?: AbortSignal) {
  return request<{ items: EventSummary[]; total: number }>(
    eventSummaryPath(projectId),
    { signal },
  );
}

const display = (value: number | null) =>
  value === null
    ? "Unavailable"
    : value.toLocaleString(undefined, { maximumFractionDigits: 3 });

export function EventSummaryPanel({
  projectId,
  onOpenPoseEvidence,
}: {
  projectId: string;
  onOpenPoseEvidence?: (
    evidence: PoseEvidenceNavigation,
    organismKey: string,
  ) => void;
}) {
  const cache = useQueryClient();
  const base = eventSummaryPath(projectId);
  const [name, setName] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [observed, setObserved] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState("");
  const [offset, setOffset] = useState(0);
  const links = useQuery({
    queryKey: ["event-summary-links", projectId, offset],
    queryFn: ({ signal }) =>
      request<{ items: PoseLink[]; total: number; limit: number }>(
        `/projects/${projectId}/ecology/pose-links?limit=25&offset=${offset}`,
        { signal },
      ),
  });
  const runs = useQuery({
    queryKey: ["event-summary-runs", projectId],
    queryFn: ({ signal }) => listEventRuns(projectId, signal),
  });
  const records = useQuery({
    queryKey: ["ecology-event-summaries", projectId],
    queryFn: ({ signal }) => listEventSummaries(projectId, signal),
  });
  const detail = useQuery({
    queryKey: ["ecology-event-summary", projectId, selected],
    queryFn: ({ signal }) => getEventSummary(projectId, selected, signal),
    enabled: !!selected,
  });
  const save = useMutation({
    mutationFn: () => {
      const sessions: Selection[] = Object.entries(choices)
        .filter(([, value]) => !!value)
        .map(([link_revision_id, option]) => {
          const [event_run_id, measurement_series_id] = option.split("/");
          const time = observed[link_revision_id];
          return {
            link_revision_id,
            event_run_id,
            measurement_series_id,
            observed_at: time ? new Date(`${time}Z`).toISOString() : null,
          };
        });
      return request<EventSummary>(base, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          reviewer,
          reason,
          confirm: confirmed,
          sessions,
        }),
      });
    },
    onSuccess: (result) => {
      setSelected(result.id);
      setConfirmed(false);
      void cache.invalidateQueries({
        queryKey: ["ecology-event-summaries", projectId],
      });
    },
  });
  const data = detail.data;
  const mapped = (id: string) => data?.source_id_map[id] ?? id;
  const ready =
    confirmed &&
    name.trim() &&
    reviewer.trim() &&
    reason.trim().length >= 3 &&
    Object.values(choices).some(Boolean);

  return (
    <section className="panel-card" aria-label="Reviewed biological events">
      <h3>Biological event summaries</h3>
      <p>
        Choose reviewed pose links and matching event runs. Only confirmed
        complete events linked to the organism contribute. Rates use time
        between adjacent valid frames.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        {links.isPending || runs.isPending ? (
          <p>Loading reviewed evidence…</p>
        ) : null}
        {links.data?.items
          .filter(
            (link) =>
              link.status === "current" && link.source.measurements.length > 0,
          )
          .map((link) => {
            const detectors = link.source.measurements.flatMap((series) =>
              (runs.data ?? []).flatMap((run) => {
                const cycles = run.configuration_json.cycles;
                return run.status === "completed" &&
                  run.measurement_run_id === series.run_id &&
                  Array.isArray(cycles) &&
                  cycles.some(
                    (cycle) => cycle.measurement_series_id === series.id,
                  )
                  ? [{ runId: run.id, series }]
                  : [];
              }),
            );
            return (
              <fieldset key={link.id}>
                <legend>
                  {link.organism_key} · frames {link.frame_start}–
                  {link.frame_end} · link revision {link.revision}
                </legend>
                <label>
                  Event detector for {link.organism_key}
                  <select
                    value={choices[link.id] ?? ""}
                    onChange={(event) =>
                      setChoices({ ...choices, [link.id]: event.target.value })
                    }
                  >
                    <option value="">Exclude this session</option>
                    {detectors.map(({ runId, series }) => (
                      <option
                        key={`${runId}/${series.id}`}
                        value={`${runId}/${series.id}`}
                      >
                        {series.name} · run {runId.slice(0, 8)}
                      </option>
                    ))}
                  </select>
                </label>
                {choices[link.id] && (
                  <label>
                    Session time (UTC, optional)
                    <input
                      type="datetime-local"
                      value={observed[link.id] ?? ""}
                      onChange={(event) =>
                        setObserved({
                          ...observed,
                          [link.id]: event.target.value,
                        })
                      }
                    />
                  </label>
                )}
              </fieldset>
            );
          })}
        {links.data &&
          !links.data.items.some(
            (link) =>
              link.status === "current" && link.source.measurements.length > 0,
          ) && (
            <p>
              Confirm an organism's pose link with a scientific measurement
              series under Pose measurements.
            </p>
          )}
        {!!offset && (
          <button
            type="button"
            onClick={() => setOffset(Math.max(0, offset - 25))}
          >
            Previous links
          </button>
        )}
        {links.data && offset + links.data.limit < links.data.total && (
          <button type="button" onClick={() => setOffset(offset + 25)}>
            More links
          </button>
        )}
        <label>
          Summary name
          <input
            required
            maxLength={150}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label>
          Reviewer
          <input
            required
            maxLength={100}
            value={reviewer}
            onChange={(event) => setReviewer(event.target.value)}
          />
        </label>
        <label>
          Review reason
          <textarea
            required
            maxLength={500}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </label>
        <label>
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
          />
          I confirm the scope, event protocol, and review coverage.
        </label>
        <button type="submit" disabled={!ready || save.isPending}>
          Save reviewed event summary
        </button>
      </form>
      {[links.error, runs.error, records.error, detail.error, save.error]
        .filter(Boolean)
        .map((error, index) => (
          <p role="alert" key={index}>
            {error?.message}
          </p>
        ))}
      <label>
        Saved event summaries
        <select
          value={selected}
          onChange={(event) => setSelected(event.target.value)}
        >
          <option value="">Select a saved summary</option>
          {records.data?.items.map((row) => (
            <option key={row.id} value={row.id}>
              {row.snapshot.selection.name}
            </option>
          ))}
        </select>
      </label>
      {detail.isFetching && <p role="status">Checking saved evidence…</p>}
      {data && (
        <article>
          <h4>{data.snapshot.selection.name}</h4>
          {data.stale_reasons.length > 0 && (
            <p role="alert">
              Historical result. {data.stale_reasons.join(" · ")}
            </p>
          )}
          <table aria-label="Confirmed organism event rates">
            <thead>
              <tr>
                <th>Organism</th>
                <th>Sessions</th>
                <th>Confirmed events</th>
                <th>Valid seconds</th>
                <th>Events/min</th>
              </tr>
            </thead>
            <tbody>
              {data.snapshot.organisms.map((row) => (
                <tr key={row.organism_key}>
                  <th scope="row">{row.organism_key}</th>
                  <td>{row.session_count}</td>
                  <td>{row.confirmed_complete_count}</td>
                  <td>{display(row.valid_duration_s)}</td>
                  <td>{display(row.confirmed_events_per_minute)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.snapshot.units.length > 0 && (
            <table aria-label="Declared unit event rates">
              <thead>
                <tr>
                  <th>Declared independent unit</th>
                  <th>Organisms</th>
                  <th>Confirmed events</th>
                  <th>Valid seconds</th>
                  <th>Events/min</th>
                </tr>
              </thead>
              <tbody>
                {data.snapshot.units.map((row) => (
                  <tr key={row.unit_id}>
                    <th scope="row">
                      {row.unit_type} {row.unit_id}
                    </th>
                    <td>{row.organism_count}</td>
                    <td>{row.confirmed_complete_count}</td>
                    <td>{display(row.valid_duration_s)}</td>
                    <td>{display(row.confirmed_events_per_minute)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {data.snapshot.sessions.map((row) => (
            <details key={row.link_revision_id}>
              <summary>
                {row.organism_key} · {row.observed_at ?? "Time unrecorded"} ·
                frames {row.frame_start}–{row.frame_end}
              </summary>
              <p>
                {row.partial_count} partial · {row.unreviewed_count} unreviewed
                complete · {row.excluded_confirmed_count} excluded confirmed ·{" "}
                {row.invalid_frame_count} missing or invalid frames
              </p>
              <ul>
                {row.events.map((event) => (
                  <li key={event.id}>
                    {display(event.start_time_s)}–{display(event.end_time_s)} s
                    · duration {display(event.duration_s)} s · amplitude{" "}
                    {display(event.amplitude)} {row.amplitude_unit}
                    {onOpenPoseEvidence && (
                      <button
                        type="button"
                        onClick={() =>
                          onOpenPoseEvidence(
                            {
                              videoId: mapped(row.video_id),
                              frameIndex: event.start_frame,
                              identityRunId: mapped(row.identity_run_id),
                              animalIdentityId: mapped(row.animal_identity_id),
                              measurementRunId: mapped(row.measurement_run_id),
                              measurementSeriesId: mapped(
                                row.measurement_series_id,
                              ),
                              eventRunId: mapped(row.event_run_id),
                              eventRevisionId: mapped(event.id),
                            },
                            row.organism_key,
                          )
                        }
                      >
                        Open reviewed event
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </details>
          ))}
          <div className="button-row">
            <a
              href={`${getApiBaseUrl()}${base}/${data.id}/results.csv`}
              download
            >
              Download event summary CSV
            </a>
            <a href={`${getApiBaseUrl()}${base}/${data.id}`} download>
              Download event summary JSON
            </a>
          </div>
          <details>
            <summary>Methods and provenance</summary>
            <p>
              {data.snapshot.method} · {data.snapshot.selection.reviewer} ·{" "}
              {data.snapshot.selection.reason}
            </p>
            <p>
              Protocol <code>{data.snapshot.protocol_sha256}</code>
            </p>
            <p>
              Result <code>{data.content_sha256}</code>
            </p>
          </details>
        </article>
      )}
    </section>
  );
}
