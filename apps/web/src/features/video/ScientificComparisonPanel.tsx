import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import type { JobRecord } from "../../api/client";
import { getApiBaseUrl } from "../../runtime";

type Pair = {
  video_id: string;
  group_id: string;
  individual_id: string;
  frame: number | null;
  start_s: number | null;
  end_s: number | null;
  reference: number;
  estimate: number;
};
type Statistic = {
  sample_count: number;
  independent_groups: number;
  zero_reference_count: number;
  bias: number;
  mean_absolute_error: number;
  mean_absolute_percentage_error: number | null;
  limits_of_agreement: [number, number] | null;
  icc: number | null;
  bias_ci95: [number, number] | null;
  mae_ci95: [number, number] | null;
};
type Comparison = {
  id: string;
  content_sha256: string;
  stale: boolean;
  source_id_map: Record<string, string>;
  snapshot: {
    data_kind: "synthetic" | "biological";
    reference_sha256: string;
    rater_id: string;
    method: string;
    software_version: string;
    options: {
      metric: "event_count" | "measurement";
      name: string;
      unit: string | null;
      icc: string | null;
    };
    models: {
      source_job_id: string;
      source_result_sha256: string;
      model_name: string;
      checkpoint_sha256: string;
      statistics: Statistic;
      pairs: Pair[];
    }[];
    pairing: {
      absolute_error_change: number;
      absolute_error_change_ci95: [number, number] | null;
      sample_count: number;
    } | null;
    exclusions: {
      video_id: string;
      individual_id: string;
      source_job_id: string;
      frame: number | null;
      start_s: number | null;
      reason: string;
    }[];
    limitations: string[];
  };
};

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "The comparison request failed.",
    );
  }
  return data as T;
}

function decimal(value: number | null): string {
  return value === null ? "Unavailable" : value.toFixed(3);
}

function interval(value: [number, number] | null): string {
  return value ? value.map(decimal).join(" to ") : "Unavailable";
}

export function PairPlot({
  modelName,
  pairs,
  unit,
  difference,
  bias,
  limits,
}: {
  modelName: string;
  pairs: Pick<Pair, "reference" | "estimate" | "individual_id">[];
  unit: string;
  difference: boolean;
  bias: number;
  limits: [number, number] | null;
}) {
  const points = pairs.map((pair) =>
    difference
      ? {
          x: (pair.estimate + pair.reference) / 2,
          y: pair.estimate - pair.reference,
        }
      : { x: pair.reference, y: pair.estimate },
  );
  let xMin = Infinity,
    xMax = -Infinity,
    yMin = Infinity,
    yMax = -Infinity;
  for (const point of points) {
    xMin = Math.min(xMin, point.x);
    xMax = Math.max(xMax, point.x);
    yMin = Math.min(yMin, point.y);
    yMax = Math.max(yMax, point.y);
  }
  if (difference) {
    yMin = Math.min(yMin, bias, 0, ...(limits ?? []));
    yMax = Math.max(yMax, bias, 0, ...(limits ?? []));
  } else {
    xMin = yMin = Math.min(xMin, yMin);
    xMax = yMax = Math.max(xMax, yMax);
  }
  const x = (value: number) => 72 + (335 * (value - xMin)) / (xMax - xMin || 1);
  const y = (value: number) =>
    180 - (157 * (value - yMin)) / (yMax - yMin || 1);
  const caption = difference
    ? "Bland–Altman difference plot"
    : "Reference against estimate";
  return (
    <figure>
      <figcaption>
        {caption} · {modelName}
      </figcaption>
      <svg
        role="img"
        aria-label={caption + " for " + modelName}
        viewBox="0 0 455 228"
        style={{ width: "100%", maxWidth: 450 }}
      >
        <path d="M72 23V180H407" stroke="currentColor" fill="none" />
        <text x="70" y="198" fontSize="10" fill="currentColor">
          {decimal(xMin)}
        </text>
        <text
          x="405"
          y="198"
          textAnchor="end"
          fontSize="10"
          fill="currentColor"
        >
          {decimal(xMax)}
        </text>
        <text x="68" y="180" textAnchor="end" fontSize="10" fill="currentColor">
          {decimal(yMin)}
        </text>
        <text x="68" y="26" textAnchor="end" fontSize="10" fill="currentColor">
          {decimal(yMax)}
        </text>
        <text
          x="239"
          y="218"
          textAnchor="middle"
          fontSize="12"
          fill="currentColor"
        >
          {difference ? "Paired mean" : "Reference"} ({unit})
        </text>
        <text
          x="19"
          y="105"
          transform="rotate(-90 19 105)"
          textAnchor="middle"
          fontSize="12"
          fill="currentColor"
        >
          {difference ? "Model − reference" : "Model estimate"} ({unit})
        </text>
        {difference ? (
          <>
            <path
              d={`M72 ${y(bias)}H407`}
              stroke="currentColor"
              strokeDasharray="5 3"
            />
            {limits?.map((limit, index) => (
              <path
                key={index}
                d={`M72 ${y(limit)}H407`}
                stroke="currentColor"
                strokeDasharray="2 4"
              />
            ))}
          </>
        ) : (
          <path
            d={`M${x(xMin)} ${y(xMin)} L${x(xMax)} ${y(xMax)}`}
            stroke="currentColor"
            strokeDasharray="5 3"
          />
        )}
        {points.slice(0, 500).map((point, index) => (
          <circle
            key={index}
            cx={x(point.x)}
            cy={y(point.y)}
            r="3.4"
            fill="currentColor"
            fillOpacity=".78"
          >
            <title>
              {pairs[index].individual_id} · {decimal(point.x)},{" "}
              {decimal(point.y)}
            </title>
          </circle>
        ))}
      </svg>
      {points.length > 500 && (
        <small>
          Showing the first 500 pairs. Export CSV for all {points.length}.
        </small>
      )}
    </figure>
  );
}

function ComparisonResult({
  record,
  base,
}: {
  record: Comparison;
  base: string;
}) {
  const data = record.snapshot;
  const unit = data.options.unit ?? "events";
  const exportPath = base + "/" + record.id + "/export";
  return (
    <section aria-label="Saved scientific comparison" aria-live="polite">
      <h5>
        {data.options.name} · {unit}
      </h5>
      <p>
        {data.data_kind === "synthetic"
          ? "Synthetic engineering reference"
          : "Held-out biological reference"}{" "}
        · Rater {data.rater_id}
      </p>
      {record.stale && (
        <p role="status">
          Historical result. The source report is missing or has changed.
        </p>
      )}
      <p>
        <a href={exportPath + "?format=csv"}>Download paired CSV</a>
        {" · "}
        <a href={exportPath}>Download methods and provenance JSON</a>
      </p>
      {data.models.map((model) => {
        const stats = model.statistics;
        return (
          <section key={model.source_job_id} aria-label={model.model_name}>
            <h6>{model.model_name}</h6>
            <p>
              {stats.sample_count} pairs across {stats.independent_groups}{" "}
              declared recording groups.
            </p>
            <dl>
              <dt>Signed bias ({unit})</dt>
              <dd>{decimal(stats.bias)}</dd>
              <dt>Mean absolute error ({unit})</dt>
              <dd>{decimal(stats.mean_absolute_error)}</dd>
              <dt>Mean absolute percentage error</dt>
              <dd>
                {decimal(stats.mean_absolute_percentage_error)}
                {stats.mean_absolute_percentage_error !== null
                  ? "%"
                  : ""} · {stats.zero_reference_count} zero references
              </dd>
              <dt>Bias and MAE 95% bootstrap intervals</dt>
              <dd>
                {interval(stats.bias_ci95)} · {interval(stats.mae_ci95)}
              </dd>
              <dt>Bland–Altman limits ({unit})</dt>
              <dd>{interval(stats.limits_of_agreement)}</dd>
              {data.options.icc && (
                <>
                  <dt>ICC({data.options.icc})</dt>
                  <dd>{decimal(stats.icc)}</dd>
                </>
              )}
            </dl>
            <div className="feature-grid">
              <PairPlot
                modelName={model.model_name}
                pairs={model.pairs}
                unit={unit}
                difference={false}
                bias={stats.bias}
                limits={null}
              />
              <PairPlot
                modelName={model.model_name}
                pairs={model.pairs}
                unit={unit}
                difference
                bias={stats.bias}
                limits={stats.limits_of_agreement}
              />
            </div>
          </section>
        );
      })}
      {data.pairing && (
        <p>
          Paired change in absolute error, second minus first ·{" "}
          {decimal(data.pairing.absolute_error_change)} {unit} over{" "}
          {data.pairing.sample_count} common pairs. 95% bootstrap interval{" "}
          {interval(data.pairing.absolute_error_change_ci95)}.
        </p>
      )}
      <details>
        <summary>
          Methods, provenance, and {data.exclusions.length} exclusions
        </summary>
        <p>
          {data.method} · ReefVision {data.software_version} · Frozen reference{" "}
          <code>{data.reference_sha256}</code>
        </p>
        <p>
          Comparison UUID <code>{record.id}</code> · Result SHA-256{" "}
          <code>{record.content_sha256}</code>
        </p>
        <ul>
          {data.limitations.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
        <ul>
          {data.models.map((model) => (
            <li key={model.source_job_id}>
              {model.model_name} · Checkpoint{" "}
              <code>{model.checkpoint_sha256}</code> · Source report{" "}
              <code>{model.source_result_sha256}</code>
            </li>
          ))}
        </ul>
        {data.exclusions.length > 0 && (
          <ul>
            {data.exclusions.slice(0, 30).map((excluded, index) => (
              <li key={index}>
                {excluded.individual_id} ·{" "}
                {excluded.frame !== null
                  ? "frame " + excluded.frame
                  : "window at " + excluded.start_s + " s"}{" "}
                · {excluded.reason.replaceAll("_", " ")}
              </li>
            ))}
          </ul>
        )}
        {data.exclusions.length > 30 && (
          <p>CSV and JSON include every exclusion.</p>
        )}
      </details>
    </section>
  );
}

export function ScientificComparisonPanel({
  projectId,
  jobs,
}: {
  projectId: string;
  jobs: JobRecord[];
}) {
  const [open, setOpen] = useState(false);
  const [first, setFirst] = useState("");
  const [second, setSecond] = useState("");
  const [metric, setMetric] = useState<"event_count" | "measurement">(
    "event_count",
  );
  const [name, setName] = useState("");
  const [unit, setUnit] = useState("");
  const [icc, setIcc] = useState("");
  const [groups, setGroups] = useState(false);
  const [limits, setLimits] = useState(false);
  const [savedId, setSavedId] = useState("");
  const base = `${getApiBaseUrl()}/projects/${projectId}/scientific-comparisons`;
  const candidates = jobs.filter(
    (row) => row.status === "succeeded" && row.result_json?.split === "test",
  );
  const saved = useQuery({
    queryKey: ["scientific-comparison", projectId],
    enabled: open,
    queryFn: ({ signal }) => fetchJson<Comparison[]>(base, { signal }),
  });
  const create = useMutation({
    mutationFn: () =>
      fetchJson<Comparison>(base, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_job_ids: [first, second].filter(Boolean),
          metric,
          name: name.trim(),
          unit: metric === "measurement" ? unit.trim() : null,
          icc: icc || null,
          independent_groups: groups,
          homoscedastic_normal_differences: groups && limits,
        }),
      }),
    onSuccess: (result) => {
      setSavedId(result.id);
      void saved.refetch();
    },
  });
  const selected =
    saved.data?.find((row) => row.id === savedId) ??
    (create.data?.id === savedId ? create.data : undefined);
  const reportLabel = (job: JobRecord) => {
    const models = Object.values(
      (job.result_json?.models ?? {}) as Record<string, { name?: string }>,
    );
    const modelNames = models
      .map((model) => model.name)
      .filter(Boolean)
      .join(", ");
    return `${modelNames || "Held-out report"} · ${job.id.slice(0, 8)}`;
  };
  const error = create.error ?? saved.error;
  return (
    <details
      className="management-card"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>Scientific human–model comparison</summary>
      <p>
        Compare one or two completed held-out reports on the same frozen human
        reference and scoring protocol.
      </p>
      {candidates.length === 0 ? (
        <p>
          Complete held-out ReefPose validation with a registered checkpoint to
          enable comparison.
        </p>
      ) : (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate();
          }}
        >
          <div className="form-row">
            <label>
              Primary held-out report
              <select
                value={first}
                onChange={(event) => {
                  setFirst(event.target.value);
                  if (event.target.value === second) setSecond("");
                }}
              >
                <option value="">Choose a report</option>
                {candidates.map((job) => (
                  <option key={job.id} value={job.id}>
                    {reportLabel(job)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Second held-out report
              <select
                value={second}
                onChange={(event) => setSecond(event.target.value)}
              >
                <option value="">One model only</option>
                {candidates
                  .filter((job) => job.id !== first)
                  .map((job) => (
                    <option key={job.id} value={job.id}>
                      {reportLabel(job)}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Comparison metric
              <select
                value={metric}
                onChange={(event) =>
                  setMetric(
                    event.target.value === "measurement"
                      ? "measurement"
                      : "event_count",
                  )
                }
              >
                <option value="event_count">Complete event count</option>
                <option value="measurement">Anatomical measurement</option>
              </select>
            </label>
            <label>
              {metric === "event_count"
                ? "Event label"
                : "Measurement definition"}
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                maxLength={200}
              />
            </label>
            {metric === "measurement" && (
              <label>
                Measurement unit
                <input
                  value={unit}
                  onChange={(event) => setUnit(event.target.value)}
                  maxLength={40}
                />
              </label>
            )}
          </div>
          <details>
            <summary>Agreement and uncertainty settings</summary>
            <label>
              <input
                type="checkbox"
                checked={groups}
                onChange={(event) => setGroups(event.target.checked)}
              />{" "}
              I confirm the declared recording groups are independent
            </label>
            <label>
              <input
                type="checkbox"
                disabled={!groups}
                checked={limits}
                onChange={(event) => setLimits(event.target.checked)}
              />{" "}
              Differences are approximately normal with constant variance
            </label>
            <label>
              Intraclass correlation
              <select
                value={icc}
                onChange={(event) => setIcc(event.target.value)}
              >
                <option value="">Omit ICC</option>
                <option value="A,1">ICC(A,1) absolute agreement</option>
                <option value="C,1">ICC(C,1) consistency</option>
              </select>
            </label>
          </details>
          <button
            type="submit"
            disabled={
              !first ||
              !name.trim() ||
              (metric === "measurement" && !unit.trim()) ||
              create.isPending
            }
          >
            {create.isPending
              ? "Saving comparison…"
              : "Save scientific comparison"}
          </button>
        </form>
      )}
      {error && (
        <p role="alert" className="form-error">
          {error.message}
        </p>
      )}
      {open && saved.isPending && (
        <p role="status">Loading saved comparisons…</p>
      )}
      {saved.data && saved.data.length > 0 && (
        <label>
          Saved comparison
          <select
            value={savedId}
            onChange={(event) => setSavedId(event.target.value)}
          >
            <option value="">Choose a saved comparison</option>
            {saved.data.map((row) => (
              <option key={row.id} value={row.id}>
                {row.snapshot.options.name} · {row.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
      )}
      {selected && <ComparisonResult record={selected} base={base} />}
    </details>
  );
}
