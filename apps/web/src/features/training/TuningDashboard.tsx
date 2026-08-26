import { useMemo, useState, type CSSProperties } from "react";
import type { TuningResults, TuningTrial } from "../../api/client";

export function bestFitnessSoFar(trials: TuningTrial[]): number[] {
  let best = Number.NEGATIVE_INFINITY;
  return trials.map((trial) => {
    if (typeof trial.fitness === "number") best = Math.max(best, trial.fitness);
    return best;
  });
}

export function rankedTrials(trials: TuningTrial[]): TuningTrial[] {
  return [...trials]
    .filter(
      (trial) =>
        trial.status === "completed" && typeof trial.fitness === "number",
    )
    .sort(
      (left, right) =>
        right.fitness! - left.fitness! ||
        left.trial_number - right.trial_number,
    );
}

function TrialChart({
  title,
  values,
  highlight,
}: {
  title: string;
  values: Array<number | null>;
  highlight?: number | null;
}) {
  const finite = values.filter((value): value is number =>
    Number.isFinite(value),
  );
  if (!finite.length)
    return <p className="system-subtle">No {title.toLowerCase()} data.</p>;
  const low = Math.min(...finite);
  const high = Math.max(...finite);
  const range = high - low || 1;
  const points = values
    .map((value, index) =>
      typeof value === "number"
        ? `${values.length === 1 ? 50 : (index / (values.length - 1)) * 100},${40 - ((value - low) / range) * 34}`
        : null,
    )
    .filter(Boolean)
    .join(" ");
  return (
    <figure className="training-metric-chart">
      <figcaption>{title}</figcaption>
      <svg
        viewBox="0 0 100 44"
        role="img"
        aria-label={`${title} in chronological trial order`}
      >
        <polyline points={points} />
        {highlight && (
          <line
            className="best-marker"
            x1={((highlight - 1) / Math.max(values.length - 1, 1)) * 100}
            x2={((highlight - 1) / Math.max(values.length - 1, 1)) * 100}
            y1="2"
            y2="42"
          />
        )}
      </svg>
      <small>
        {values.length.toLocaleString()} trials · raw values available below
      </small>
    </figure>
  );
}

export function TuningDashboard({
  results,
  onApply,
}: {
  results: TuningResults;
  onApply?: (trial: TuningTrial) => void;
}) {
  const chronological = useMemo(
    () => [...results.trials].sort((a, b) => a.trial_number - b.trial_number),
    [results.trials],
  );
  const ranked = useMemo(() => rankedTrials(chronological), [chronological]);
  const [selectedNumber, setSelectedNumber] = useState(
    results.best_trial_number ?? chronological[0]?.trial_number,
  );
  const [parameter, setParameter] = useState("");
  const selected = chronological.find(
    (trial) => trial.trial_number === selectedNumber,
  );
  const parameters = [
    ...new Set(
      chronological.flatMap((trial) => Object.keys(trial.hyperparameters)),
    ),
  ];
  const activeParameter = parameter || parameters[0] || "";
  const completed = chronological.filter(
    (trial) => trial.status === "completed",
  ).length;
  const failed = chronological.filter(
    (trial) => trial.status === "failed",
  ).length;

  return (
    <section className="tuning-dashboard" aria-label="Tuning results">
      <div className="training-result-facts">
        <div>
          <span>Trials</span>
          <strong>
            {completed} / {results.max_trials ?? "—"}
          </strong>
          <small>{failed} failed retained</small>
        </div>
        <div>
          <span>Best trial</span>
          <strong>#{results.best_trial_number ?? "—"}</strong>
          <small>{ranked[0]?.fitness?.toFixed(5) ?? "No valid fitness"}</small>
        </div>
        <div>
          <span>Epochs per trial</span>
          <strong>{results.epochs_per_trial ?? "—"}</strong>
          <small>Patience {results.patience ?? "not recorded"}</small>
        </div>
      </div>
      <div className="editor-message">
        <strong>Fitness definition</strong>
        <p>{results.fitness_definition}</p>
      </div>
      <div className="training-chart-grid">
        <TrialChart
          title="Fitness vs Trial"
          values={chronological.map((trial) => trial.fitness)}
          highlight={results.best_trial_number}
        />
        <TrialChart
          title="Best Fitness So Far vs Trial"
          values={bestFitnessSoFar(chronological)}
          highlight={results.best_trial_number}
        />
        {Object.keys(chronological[0]?.metrics ?? {})
          .slice(0, 4)
          .map((metric) => (
            <TrialChart
              key={metric}
              title={`${metric.replaceAll("/", " ")} vs Trial`}
              values={chronological.map(
                (trial) => trial.metrics[metric] ?? null,
              )}
            />
          ))}
      </div>
      <section>
        <div className="section-heading">
          <div>
            <h5>Parameter analysis</h5>
            <span>Observed values; no causal claim or fitted trend</span>
          </div>
          <label>
            Parameter
            <select
              aria-label="Parameter to analyze"
              value={activeParameter}
              onChange={(event) => setParameter(event.target.value)}
            >
              {parameters.map((name) => (
                <option key={name}>{name}</option>
              ))}
            </select>
          </label>
        </div>
        {activeParameter && (
          <div
            className="parameter-fitness-table"
            role="img"
            aria-label={`${activeParameter} versus fitness scatter data`}
          >
            {chronological
              .filter(
                (trial) =>
                  typeof trial.hyperparameters[activeParameter] === "number" &&
                  typeof trial.fitness === "number",
              )
              .map((trial) => (
                <span
                  key={trial.trial_number}
                  title={`Trial ${trial.trial_number}: ${activeParameter} ${trial.hyperparameters[activeParameter]}, fitness ${trial.fitness}`}
                  style={
                    {
                      "--x": String(trial.hyperparameters[activeParameter]),
                      "--y": String(trial.fitness),
                    } as CSSProperties
                  }
                >
                  #{trial.trial_number}
                </span>
              ))}
          </div>
        )}
      </section>
      <section>
        <h5>Ranked trials</h5>
        <div className="training-table-wrap">
          <table>
            <thead>
              <tr>
                <th>Rank</th>
                <th>Trial</th>
                <th>Fitness</th>
                <th>Status</th>
                <th>Duration</th>
              </tr>
            </thead>
            <tbody>
              {ranked.slice(0, 100).map((trial, index) => (
                <tr key={trial.trial_number}>
                  <td>{index + 1}</td>
                  <td>
                    <button
                      type="button"
                      onClick={() => setSelectedNumber(trial.trial_number)}
                    >
                      #{trial.trial_number}
                    </button>
                  </td>
                  <td>{trial.fitness?.toFixed(6)}</td>
                  <td>{trial.status}</td>
                  <td>
                    {trial.duration_seconds == null
                      ? "—"
                      : `${trial.duration_seconds.toFixed(1)} s`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      {selected && (
        <aside
          className="system-card"
          aria-label={`Trial ${selected.trial_number} inspector`}
        >
          <div className="section-heading">
            <div>
              <p className="eyebrow">Trial inspector</p>
              <h5>Trial #{selected.trial_number}</h5>
            </div>
            <strong>{selected.fitness?.toFixed(6) ?? selected.status}</strong>
          </div>
          {selected.error_message && (
            <p className="form-error">{selected.error_message}</p>
          )}
          <h6>Hyperparameters</h6>
          <pre className="json-block">
            {JSON.stringify(selected.hyperparameters, null, 2)}
          </pre>
          <h6>Metrics</h6>
          <pre className="json-block">
            {JSON.stringify(selected.metrics, null, 2)}
          </pre>
          <p>{selected.epoch_history.length} persisted epoch rows</p>
          {onApply && selected.status === "completed" && (
            <button type="button" onClick={() => onApply(selected)}>
              Apply to New Training Run
            </button>
          )}
        </aside>
      )}
    </section>
  );
}
