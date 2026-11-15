import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  getSubjectEnvironment,
  importScientificRecords,
  type ScientificSubject,
  type ScientificSourceKind,
} from "./environmentalContextApi";
import { ScientificRecordCard, utcTime } from "./ScientificRecordCard";

interface Props {
  projectId: string;
  subject: ScientificSubject;
}
export function EnvironmentalSubjectInspector(props: Props) {
  return (
    <SubjectInspector
      key={`${props.projectId}:${JSON.stringify(props.subject)}`}
      {...props}
    />
  );
}
function SubjectInspector({ projectId, subject }: Props) {
  const [open, setOpen] = useState(false);
  const [positionId, setPositionId] = useState("");
  const [distance, setDistance] = useState(1000);
  const [seconds, setSeconds] = useState(3600);
  const [depthDelta, setDepthDelta] = useState(0);
  const [latitude, setLatitude] = useState("");
  const [longitude, setLongitude] = useState("");
  const [timestamp, setTimestamp] = useState("");
  const [depth, setDepth] = useState("");
  const [depthReference, setDepthReference] = useState("");
  const [source, setSource] = useState("");
  const [sourceKind, setSourceKind] =
    useState<ScientificSourceKind>("observed");
  const [uncertainty, setUncertainty] = useState("");
  const client = useQueryClient();
  const boundsValid =
    Number.isFinite(distance) &&
    distance >= 0 &&
    distance <= 100000 &&
    Number.isFinite(seconds) &&
    seconds >= 0 &&
    seconds <= 604800 &&
    Number.isFinite(depthDelta) &&
    depthDelta >= 0 &&
    depthDelta <= 1000;
  const query = useQuery({
    queryKey: [
      "subject-environment",
      projectId,
      subject,
      positionId,
      distance,
      seconds,
      depthDelta,
    ],
    enabled: open && boundsValid,
    queryFn: ({ signal }) =>
      getSubjectEnvironment(
        projectId,
        {
          subject,
          position_record_id: positionId || undefined,
          max_distance_m: distance,
          max_time_delta_s: seconds,
          max_depth_delta_m: depthDelta,
        },
        signal,
      ),
  });
  const save = useMutation({
    mutationFn: () =>
      importScientificRecords(projectId, {
        records: [
          {
            variable: "geographic_position",
            value: 1,
            unit: "1",
            subject,
            observed_at: new Date(`${timestamp}Z`).toISOString(),
            source_kind: sourceKind,
            location: {
              crs: "EPSG:4326",
              latitude: Number(latitude),
              longitude: Number(longitude),
              horizontal_uncertainty_m:
                uncertainty === "" ? null : Number(uncertainty),
            },
            depth_m: depth === "" ? null : Number(depth),
            depth_reference: depth === "" ? null : depthReference,
            provenance: {
              source,
              acquired_at: new Date().toISOString(),
              method: "user_supplied_subject_position",
            },
          },
        ],
      }),
    onSuccess: async (result) => {
      setPositionId(result.items[0].id);
      await client.invalidateQueries({
        queryKey: ["subject-environment", projectId],
      });
      await client.invalidateQueries({
        queryKey: ["scientific-records", projectId],
      });
    },
  });
  return (
    <section
      className="management-card"
      aria-label="Subject environmental context"
    >
      <h3>Environmental context</h3>
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? "Close environmental context" : "Inspect environmental context"}
      </button>
      {open && (
        <>
          <p>
            Nearby context is not an exact measurement at the organism. Original
            observations and model values remain distinct; no interpolation is
            performed.
          </p>
          <label>
            Maximum separation (m)
            <input
              type="number"
              min="0"
              max="100000"
              value={distance}
              onChange={(e) => setDistance(e.target.valueAsNumber)}
            />
          </label>
          <label>
            Maximum time separation (s)
            <input
              type="number"
              min="0"
              max="604800"
              value={seconds}
              onChange={(e) => setSeconds(e.target.valueAsNumber)}
            />
          </label>
          <label>
            Maximum depth separation (m)
            <input
              type="number"
              min="0"
              max="1000"
              value={depthDelta}
              onChange={(e) => setDepthDelta(e.target.valueAsNumber)}
            />
          </label>
          {!boundsValid && (
            <p role="alert">Enter valid nonnegative lookup bounds.</p>
          )}
          {query.isFetching && (
            <p role="status">Looking up local environmental records…</p>
          )}
          {query.error && <p role="alert">{query.error.message}</p>}
          {query.data?.reason && <p role="status">{query.data.reason}</p>}
          {(query.data?.positions.length ?? 0) > 1 && (
            <label>
              Position/time reference
              <select
                value={positionId}
                onChange={(e) => setPositionId(e.target.value)}
              >
                <option value="">Choose reference</option>
                {query.data!.positions.map((item) => (
                  <option key={item.id} value={item.id}>
                    {utcTime(item.observed_at)} — {item.provenance.source} (
                    {item.id})
                  </option>
                ))}
              </select>
            </label>
          )}
          {query.data?.position && (
            <p>
              Subject reference: {query.data.position.location?.latitude},{" "}
              {query.data.position.location?.longitude} (WGS84),{" "}
              {utcTime(query.data.position.observed_at)}. Position uncertainty:{" "}
              {query.data.position.location?.horizontal_uncertainty_m == null
                ? "unknown"
                : `${query.data.position.location.horizontal_uncertainty_m} m`}
              . Source: {query.data.position.provenance.source}.
            </p>
          )}
          {boundsValid &&
            Object.entries(query.data?.matches ?? {}).map(
              ([variable, matches]) => (
                <div key={variable}>
                  {matches.length === 0 ? (
                    <p>{variable}: unavailable within the selected bounds.</p>
                  ) : (
                    matches.map((match) => (
                      <div key={match.record.id}>
                        <p>
                          {match.distance_m.toFixed(1)} m away;{" "}
                          {Math.abs(match.time_delta_s).toFixed(0)} s{" "}
                          {match.time_delta_s < 0 ? "before" : "after"} subject
                          time; depth separation:{" "}
                          {match.depth_delta_m == null
                            ? "not constrained / unknown"
                            : `${match.depth_delta_m} m`}
                          .
                        </p>
                        <p>
                          {match.offline_available
                            ? "Available offline"
                            : "Not available offline"}
                          .{" "}
                          {match.cache_age_s == null
                            ? "Local scientific record; no provider cache age."
                            : `Provider cache: ${(match.cache_age_s / 3600).toFixed(1)} h old; expires ${utcTime(match.cache_expires_at!)}.`}
                        </p>
                        <ScientificRecordCard record={match.record} />
                      </div>
                    ))
                  )}
                </div>
              ),
            )}
          <details>
            <summary>Add position/time reference</summary>
            <p>
              Enter a documented location and UTC capture time for this exact
              image, frame or object. Do not enter a monitoring station's
              coordinates as the organism's position. Saving creates a new
              immutable reference.
            </p>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                save.mutate();
              }}
            >
              <label>
                Subject latitude
                <input
                  type="number"
                  min="-90"
                  max="90"
                  step="any"
                  required
                  value={latitude}
                  onChange={(e) => setLatitude(e.target.value)}
                />
              </label>
              <label>
                Subject longitude
                <input
                  type="number"
                  min="-180"
                  max="180"
                  step="any"
                  required
                  value={longitude}
                  onChange={(e) => setLongitude(e.target.value)}
                />
              </label>
              <label>
                Capture time (UTC)
                <input
                  type="datetime-local"
                  step="1"
                  required
                  value={timestamp}
                  onChange={(e) => setTimestamp(e.target.value)}
                />
              </label>
              <label>
                Position uncertainty (m, optional)
                <input
                  type="number"
                  min="0"
                  step="any"
                  value={uncertainty}
                  onChange={(e) => setUncertainty(e.target.value)}
                />
              </label>
              <label>
                Depth (m, positive down, optional)
                <input
                  type="number"
                  min="0"
                  step="any"
                  value={depth}
                  onChange={(e) => setDepth(e.target.value)}
                />
              </label>
              <label>
                Depth reference
                <input
                  required={depth !== ""}
                  placeholder="sea_surface"
                  value={depthReference}
                  onChange={(e) => setDepthReference(e.target.value)}
                />
              </label>
              <label>
                Position source kind
                <select
                  value={sourceKind}
                  onChange={(e) =>
                    setSourceKind(e.target.value as ScientificSourceKind)
                  }
                >
                  <option value="observed">Observed</option>
                  <option value="derived">Derived</option>
                  <option value="modeled">Modeled</option>
                  <option value="remotely_sensed">Remotely sensed</option>
                </select>
              </label>
              <label>
                Position evidence/source
                <input
                  required
                  value={source}
                  onChange={(e) => setSource(e.target.value)}
                />
              </label>
              <button type="submit" disabled={save.isPending}>
                Save position reference
              </button>
              {save.error && <p role="alert">{save.error.message}</p>}
            </form>
          </details>
        </>
      )}
    </section>
  );
}
