import { useQuery } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";

import { listEventSummaries } from "../ecology/EventSummaryPanel";
import type {
  MonitoringKind,
  MonitoringRuleCreate,
  MonitoringSourceKind,
} from "./monitoringApi";

const sourceKinds: Record<MonitoringSourceKind, string> = {
  observed: "Observed",
  remotely_sensed: "Remotely sensed",
  modeled: "Modeled",
  derived: "Derived",
};

function numberField(form: FormData, name: string): number | undefined {
  const value = form.get(name);
  return typeof value === "string" && value !== "" ? Number(value) : undefined;
}

export function MonitoringRuleForm({
  projectId,
  pending,
  onCreate,
  onCancel,
}: {
  projectId: string;
  pending: boolean;
  onCreate: (rule: MonitoringRuleCreate) => void;
  onCancel: () => void;
}) {
  const id = useId();
  const [kind, setKind] = useState<MonitoringKind>("environmental");
  const [selectedSummaries, setSelectedSummaries] = useState<string[]>([]);
  const [invalid, setInvalid] = useState("");
  const summaries = useQuery({
    queryKey: ["ecology-event-summaries", projectId],
    queryFn: ({ signal }) => listEventSummaries(projectId, signal),
    enabled: kind === "biological",
  });
  const selected =
    summaries.data?.items.filter((row) => selectedSummaries.includes(row.id)) ??
    [];
  const protocol = selected[0]?.snapshot.protocol_sha256;
  const canUseBiological =
    selected.length > 0 &&
    selected.length === selectedSummaries.length &&
    selected.every(
      (row) =>
        !row.stale_reasons.length && row.snapshot.protocol_sha256 === protocol,
    );

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const read = (name: string) => String(form.get(name) ?? "").trim();
    const lower = numberField(form, "lower");
    const upper = numberField(form, "upper");
    if (
      !read("label") ||
      (lower !== undefined && upper !== undefined && lower > upper)
    ) {
      setInvalid(
        "Enter a rule name and keep the lower limit at or below the upper limit.",
      );
      return;
    }
    setInvalid("");
    const thresholds = { lower_limit: lower, upper_limit: upper };
    if (kind === "biological") {
      if (!canUseBiological || !protocol) return;
      const effort = Number(read("effort"));
      if (!(effort > 0)) {
        setInvalid("Enter a positive minimum effort in seconds.");
        return;
      }
      onCreate({
        label: read("label"),
        kind,
        protocol,
        metric: "confirmed_events_per_minute",
        unit: "events/min",
        parameters: {
          ...thresholds,
          summary_ids: selectedSummaries,
          minimum_effort_seconds: effort,
        },
      });
      return;
    }
    const source = read("source");
    const drift = numberField(form, "drift");
    if (drift !== undefined && !(drift > 0)) {
      setInvalid("Enter a positive maximum change or leave it blank.");
      return;
    }
    if (!read("protocol") || !read("metric") || !read("unit")) {
      setInvalid("Enter the recorded protocol, metric and normalized unit.");
      return;
    }
    onCreate({
      label: read("label"),
      kind,
      protocol: read("protocol"),
      metric: read("metric"),
      unit: read("unit"),
      parameters: {
        ...thresholds,
        cadence_seconds: Number(read("cadence")),
        source_kind: read("source-kind") as MonitoringSourceKind,
        source: source || undefined,
        max_drift: drift,
        max_delay_seconds: numberField(form, "delay"),
      },
    });
  }

  return (
    <form className="panel" aria-labelledby={id} onSubmit={submit}>
      <h3 id={id}>New monitoring rule</h3>
      <div className="dashboard-grid">
        <label>
          Rule name
          <input name="label" required maxLength={200} />
        </label>
        <label>
          Source type
          <select
            value={kind}
            onChange={(event) =>
              setKind(event.currentTarget.value as MonitoringKind)
            }
          >
            <option value="environmental">Environmental</option>
            <option value="biological">Biological</option>
          </select>
        </label>
        {kind === "environmental" ? (
          <>
            <label>
              Protocol
              <input required name="protocol" />
            </label>
            <label>
              Metric
              <input required name="metric" placeholder="water_temperature" />
            </label>
            <label>
              Unit
              <input required name="unit" placeholder="degC" />
            </label>
            <label>
              Source kind
              <select name="source-kind" defaultValue="observed">
                {Object.entries(sourceKinds).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Source name (optional)
              <input name="source" />
            </label>
            <label>
              Cadence (seconds)
              <input
                name="cadence"
                required
                type="number"
                min={1}
                max={86_400}
                step={1}
              />
            </label>
            <label>
              Maximum change between adjacent accepted observations
              <input name="drift" type="number" min="0" step="any" />
            </label>
            <label>
              Maximum acquisition delay (seconds)
              <input name="delay" type="number" min="0" step="any" />
            </label>
          </>
        ) : (
          <label>
            Minimum effort (seconds)
            <input
              name="effort"
              required
              type="number"
              min="0"
              step="any"
              defaultValue={1}
            />
          </label>
        )}
        <label>
          Lower limit
          <input name="lower" type="number" step="any" />
        </label>
        <label>
          Upper limit
          <input name="upper" type="number" step="any" />
        </label>
      </div>
      {kind === "environmental" ? (
        <p className="muted">
          Use the protocol and normalized unit recorded with the observations.
          Limits and changes use that unit.
        </p>
      ) : (
        <fieldset>
          <legend>Reviewed biological summaries</legend>
          <p>
            Complete confirmed events per minute of valid effort. Select
            summaries with the same protocol.
          </p>
          {summaries.isPending && <p>Loading biological summaries…</p>}
          {summaries.error && (
            <p className="form-error" role="alert">
              {summaries.error.message}
            </p>
          )}
          {summaries.isSuccess && !summaries.data.items.length && (
            <p>No reviewed biological summaries in this project.</p>
          )}
          {summaries.data?.items.map((summary) => (
            <div key={summary.id} className="monitoring-summary-source">
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={selectedSummaries.includes(summary.id)}
                  disabled={
                    summary.stale_reasons.length > 0 ||
                    Boolean(
                      protocol && summary.snapshot.protocol_sha256 !== protocol,
                    )
                  }
                  onChange={(event) => {
                    const checked = event.currentTarget.checked;
                    setSelectedSummaries((rows) =>
                      checked
                        ? [...rows, summary.id]
                        : rows.filter((id) => id !== summary.id),
                    );
                  }}
                />
                {summary.snapshot.selection.name}
              </label>
              {!!summary.stale_reasons.length && (
                <p className="muted">
                  Stale · {summary.stale_reasons.join(" ")}
                </p>
              )}
            </div>
          ))}
        </fieldset>
      )}
      {invalid && (
        <p className="form-error" role="alert">
          {invalid}
        </p>
      )}
      <div className="dashboard-actions">
        <button
          type="submit"
          disabled={pending || (kind === "biological" && !canUseBiological)}
        >
          Create monitoring rule
        </button>
        <button type="button" className="secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
