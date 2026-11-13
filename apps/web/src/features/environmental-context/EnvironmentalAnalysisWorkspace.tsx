import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { ErrorState } from "../../components/ui/AsyncState";
import { StatusBadge } from "../../components/ui/StatusBadge";
import {
  createEventWindowAnalysis,
  createLaggedComparison,
  createLunarAnalysis,
  createObservationEnvironmentJoin,
  createTidalAnalysis,
  environmentalAnalysisCsvUrl,
  importNOAATides,
  listEnvironmentalAnalysisResults,
  type EnvironmentalAnalysisKind,
  type EnvironmentalAnalysisResult,
  type EnvironmentalAnalysisSingle,
} from "./environmentalAnalysisApi";

const KIND_LABELS: Record<EnvironmentalAnalysisKind, string> = {
  lunar_context: "Lunar context",
  tidal_context: "Tidal context",
  event_window: "Event window",
  observation_environment_join: "Observation–environment join",
  lagged_comparison: "Lagged comparison",
};

const CACHE_LABELS = {
  downloaded: "Downloaded from NOAA",
  fresh: "Fresh cached data",
  stale_offline: "Stale cache used offline",
};

function splitValues(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function AnalysisEvidence({
  projectId,
  result,
}: {
  projectId: string;
  result: EnvironmentalAnalysisResult;
}) {
  const effort = result.payload.sampling_effort as
    { requested: number; matched: number; unmatched: number } | undefined;
  return (
    <article
      className="panel-card training-content"
      aria-label="Saved environmental analysis"
    >
      <h4>{KIND_LABELS[result.analysis_kind]}</h4>
      <p>Analysis time: {result.observed_at}</p>
      <p>
        Quality control: {String(result.quality_control.status ?? "unassessed")}
      </p>
      <p>
        Content SHA-256: <code>{result.content_sha256}</code>
      </p>
      <p>
        Source records: {result.source_record_ids.length}; source analyses:{" "}
        {result.source_analysis_result_ids.length}
      </p>
      {effort && (
        <p>
          Matched {effort.matched} of {effort.requested} requested observations.{" "}
          Unmatched: {effort.unmatched}.
        </p>
      )}
      <a href={environmentalAnalysisCsvUrl(projectId, result.id)}>
        Download evidence CSV
      </a>
      <details>
        <summary>Analysis evidence and methodological output</summary>
        <pre>{JSON.stringify(result.payload, null, 2)}</pre>
        {result.uncertainty && (
          <pre>{JSON.stringify(result.uncertainty, null, 2)}</pre>
        )}
      </details>
    </article>
  );
}

export function EnvironmentalAnalysisWorkspace({
  projectId,
}: {
  projectId: string;
}) {
  const [stationId, setStationId] = useState("");
  const [day, setDay] = useState("");
  const [product, setProduct] = useState<"predictions" | "water_level">(
    "water_level",
  );
  const [datum, setDatum] = useState("MLLW");
  const [offline, setOffline] = useState(false);
  const [kind, setKind] = useState<EnvironmentalAnalysisKind>("lunar_context");
  const [name, setName] = useState("");
  const [observedAt, setObservedAt] = useState("");
  const [latitude, setLatitude] = useState("");
  const [longitude, setLongitude] = useState("");
  const [maxTime, setMaxTime] = useState("3600");
  const [maxDistance, setMaxDistance] = useState("1000");
  const [eventDefinitionId, setEventDefinitionId] = useState("");
  const [beforeSeconds, setBeforeSeconds] = useState("3600");
  const [afterSeconds, setAfterSeconds] = useState("3600");
  const [boundaryPolicy, setBoundaryPolicy] = useState<
    "inclusive" | "exclusive"
  >("inclusive");
  const [observationIds, setObservationIds] = useState("");
  const [environmentalVariable, setEnvironmentalVariable] =
    useState("water_temperature");
  const [depthMatch, setDepthMatch] = useState(false);
  const [retainUnmatched, setRetainUnmatched] = useState(false);
  const [studyAssignments, setStudyAssignments] = useState("");
  const [maxDepth, setMaxDepth] = useState("0");
  const [joinResultId, setJoinResultId] = useState("");
  const [lags, setLags] = useState("-3600, 0, 3600");

  const tideImport = useMutation({
    mutationFn: () =>
      importNOAATides(projectId, {
        station_id: stationId,
        day,
        product,
        datum,
        offline,
      }),
  });
  const analysis = useMutation<EnvironmentalAnalysisSingle, Error>({
    mutationFn: () => {
      if (kind === "lunar_context") {
        return createLunarAnalysis(projectId, {
          name,
          observed_at: [observedAt],
        });
      }
      if (kind === "tidal_context") {
        return createTidalAnalysis(projectId, {
          name,
          observed_at: observedAt,
          location: {
            latitude: Number(latitude),
            longitude: Number(longitude),
          },
          station_id: stationId,
          datum,
          max_time_delta_s: Number(maxTime),
          max_distance_m: Number(maxDistance),
        });
      }
      if (kind === "event_window") {
        return createEventWindowAnalysis(projectId, {
          name,
          event_definition_id: eventDefinitionId,
          before_s: Number(beforeSeconds),
          after_s: Number(afterSeconds),
          boundary_policy: boundaryPolicy,
        });
      }
      if (kind === "observation_environment_join") {
        const assignments: unknown = studyAssignments.trim()
          ? JSON.parse(studyAssignments)
          : [];
        if (!Array.isArray(assignments)) {
          throw new Error("Study assignments must be a JSON list.");
        }
        return createObservationEnvironmentJoin(projectId, {
          name,
          observation_record_ids: splitValues(observationIds),
          environmental_variable: environmentalVariable,
          max_time_delta_s: Number(maxTime),
          max_distance_m: Number(maxDistance),
          require_depth_match: depthMatch,
          max_depth_delta_m: depthMatch ? Number(maxDepth) : 0,
          ...(retainUnmatched ? { unmatched_policy: "retain" } : {}),
          ...(assignments.length ? { study_assignments: assignments } : {}),
        });
      }
      return createLaggedComparison(projectId, {
        name,
        join_result_id: joinResultId,
        lags_s: splitValues(lags).map(Number),
      });
    },
  });
  const history = useMutation({
    mutationFn: () => listEnvironmentalAnalysisResults(projectId),
  });

  function submitAnalysis(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    analysis.mutate();
  }

  return (
    <section className="training-content" aria-label="Environmental analyses">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Immutable contextual evidence</p>
          <h3>Tidal, lunar, event, and lag analyses</h3>
          <p>
            Observed and predicted water levels remain separate. Joins enforce
            explicit time, location, and optional depth tolerances.
          </p>
          <p>
            Outputs provide descriptive context, not causation or significance.
            Reused samples are surfaced as a pseudoreplication warning.
          </p>
        </div>
      </div>

      <form
        className="panel-card training-content"
        onSubmit={(event) => {
          event.preventDefault();
          tideImport.mutate();
        }}
      >
        <h4>NOAA CO-OPS tidal records</h4>
        <div className="training-form-grid">
          <label>
            Tidal station ID
            <input
              required
              pattern="[0-9]{7}"
              value={stationId}
              onChange={(event) => setStationId(event.target.value)}
            />
          </label>
          <label>
            Tidal day (UTC)
            <input
              type="date"
              required
              value={day}
              onChange={(event) => setDay(event.target.value)}
            />
          </label>
          <label>
            Tidal product
            <select
              value={product}
              onChange={(event) =>
                setProduct(event.target.value as typeof product)
              }
            >
              <option value="water_level">Observed water level</option>
              <option value="predictions">Predicted water level</option>
            </select>
          </label>
          <label>
            Tidal datum
            <input
              required
              value={datum}
              onChange={(event) => setDatum(event.target.value.toUpperCase())}
            />
          </label>
        </div>
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={offline}
            onChange={(event) => setOffline(event.target.checked)}
          />
          Use tidal cache only (offline)
        </label>
        <button type="submit" disabled={tideImport.isPending}>
          Import tidal records
        </button>
        {tideImport.error && (
          <ErrorState
            title="Tidal import failed"
            message={tideImport.error.message}
          />
        )}
        {tideImport.data && (
          <div role="status" aria-label="Tidal import result">
            <StatusBadge
              status={
                tideImport.data.cache_status === "stale_offline"
                  ? "warning"
                  : "ready"
              }
              label={CACHE_LABELS[tideImport.data.cache_status]}
            />
            <p>{tideImport.data.items.length} immutable records available.</p>
          </div>
        )}
      </form>

      <form className="panel-card training-content" onSubmit={submitAnalysis}>
        <h4>Persist environmental analysis</h4>
        <label>
          Analysis type
          <select
            value={kind}
            onChange={(event) => {
              setKind(event.target.value as EnvironmentalAnalysisKind);
              analysis.reset();
            }}
          >
            {Object.entries(KIND_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Analysis name
          <input
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        {(kind === "lunar_context" || kind === "tidal_context") && (
          <label>
            Analysis timestamp (UTC)
            <input
              required
              placeholder="2026-04-03T13:00:00Z"
              value={observedAt}
              onChange={(event) => setObservedAt(event.target.value)}
            />
          </label>
        )}
        {kind === "tidal_context" && (
          <div className="training-form-grid">
            <label>
              Latitude
              <input
                required
                value={latitude}
                onChange={(event) => setLatitude(event.target.value)}
              />
            </label>
            <label>
              Longitude
              <input
                required
                value={longitude}
                onChange={(event) => setLongitude(event.target.value)}
              />
            </label>
            <label>
              Maximum time delta (seconds)
              <input
                required
                type="number"
                min="1"
                value={maxTime}
                onChange={(event) => setMaxTime(event.target.value)}
              />
            </label>
            <label>
              Maximum distance (metres)
              <input
                required
                type="number"
                min="0"
                value={maxDistance}
                onChange={(event) => setMaxDistance(event.target.value)}
              />
            </label>
          </div>
        )}
        {kind === "event_window" && (
          <div className="training-form-grid">
            <label>
              Threshold definition ID
              <input
                required
                value={eventDefinitionId}
                onChange={(event) => setEventDefinitionId(event.target.value)}
              />
            </label>
            <label>
              Seconds before
              <input
                required
                type="number"
                min="0"
                value={beforeSeconds}
                onChange={(event) => setBeforeSeconds(event.target.value)}
              />
            </label>
            <label>
              Seconds after
              <input
                required
                type="number"
                min="0"
                value={afterSeconds}
                onChange={(event) => setAfterSeconds(event.target.value)}
              />
            </label>
            <label>
              Boundary policy
              <select
                value={boundaryPolicy}
                onChange={(event) =>
                  setBoundaryPolicy(event.target.value as typeof boundaryPolicy)
                }
              >
                <option value="inclusive">Inclusive</option>
                <option value="exclusive">Exclusive</option>
              </select>
            </label>
          </div>
        )}
        {kind === "observation_environment_join" && (
          <>
            <label>
              Observation record IDs (comma-separated)
              <input
                required
                value={observationIds}
                onChange={(event) => setObservationIds(event.target.value)}
              />
            </label>
            <div className="training-form-grid">
              <label>
                Environmental variable
                <input
                  required
                  value={environmentalVariable}
                  onChange={(event) =>
                    setEnvironmentalVariable(event.target.value)
                  }
                />
              </label>
              <label>
                Maximum time delta (seconds)
                <input
                  required
                  type="number"
                  min="1"
                  value={maxTime}
                  onChange={(event) => setMaxTime(event.target.value)}
                />
              </label>
              <label>
                Maximum distance (metres)
                <input
                  required
                  type="number"
                  min="0"
                  value={maxDistance}
                  onChange={(event) => setMaxDistance(event.target.value)}
                />
              </label>
            </div>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={depthMatch}
                onChange={(event) => setDepthMatch(event.target.checked)}
              />
              Require matching depth reference and tolerance
            </label>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={retainUnmatched}
                onChange={(event) => setRetainUnmatched(event.target.checked)}
              />
              Retain unmatched observations
            </label>
            <label>
              Study assignments (JSON)
              <textarea
                rows={3}
                value={studyAssignments}
                onChange={(event) => setStudyAssignments(event.target.value)}
                placeholder="Optional. Supply one subject, experimental unit, treatment and timepoint per observation."
              />
            </label>
            {depthMatch && (
              <label>
                Maximum depth delta (metres)
                <input
                  type="number"
                  min="0"
                  value={maxDepth}
                  onChange={(event) => setMaxDepth(event.target.value)}
                />
              </label>
            )}
          </>
        )}
        {kind === "lagged_comparison" && (
          <>
            <label>
              Join result ID
              <input
                required
                value={joinResultId}
                onChange={(event) => setJoinResultId(event.target.value)}
              />
            </label>
            <label>
              Lags in seconds (comma-separated)
              <input
                required
                value={lags}
                onChange={(event) => setLags(event.target.value)}
              />
            </label>
          </>
        )}
        <button type="submit" disabled={analysis.isPending}>
          Persist analysis
        </button>
        {analysis.error && (
          <ErrorState
            title="Analysis failed"
            message={analysis.error.message}
          />
        )}
      </form>

      {analysis.data && (
        <AnalysisEvidence projectId={projectId} result={analysis.data.result} />
      )}

      <section className="training-content">
        <button
          type="button"
          disabled={history.isPending}
          onClick={() => history.mutate()}
        >
          Load saved analyses
        </button>
        {history.error && (
          <ErrorState
            title="Analysis history failed"
            message={history.error.message}
          />
        )}
        {history.data && (
          <div aria-label="Environmental analysis history">
            <h4>Saved analysis history ({history.data.total})</h4>
            {history.data.items.map((item) => (
              <AnalysisEvidence
                key={item.id}
                projectId={projectId}
                result={item}
              />
            ))}
          </div>
        )}
      </section>
    </section>
  );
}
