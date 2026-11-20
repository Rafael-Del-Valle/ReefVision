import { useInfiniteQuery } from "@tanstack/react-query";

import {
  listMonitoringAssessments,
  type MonitoringAssessment,
} from "./monitoringApi";

export const monitoringLabel = (key: string) => key.replaceAll("_", " ");

export function monitoringUtc(stamp: string) {
  return new Date(stamp)
    .toISOString()
    .replace(".000Z", "Z")
    .replace("T", " ")
    .replace(/Z$/, " UTC");
}

export function assessmentLabel(record: MonitoringAssessment) {
  const result = record.result;
  return `${monitoringLabel(result.metric)} · ${result.unit} · ${monitoringUtc(record.window_start)} to ${monitoringUtc(record.window_end)} · Saved ${monitoringUtc(record.created_at)}${record.source_status === "stale" ? " · Stale" : ""}`;
}

export function useMonitoringAssessments(projectId: string) {
  return useInfiniteQuery({
    queryKey: ["monitoring-assessments", projectId],
    enabled: Boolean(projectId),
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      listMonitoringAssessments(projectId, pageParam, signal),
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce(
        (count, page) => count + page.items.length,
        0,
      );
      return loaded < last.total && last.items.length ? loaded : undefined;
    },
  });
}

export function MonitoringFields({
  fields,
}: {
  fields: Record<string, unknown>;
}) {
  return (
    <dl className="monitoring-fields">
      {Object.entries(fields).map(([key, value]) => (
        <div key={key}>
          <dt>{monitoringLabel(key)}</dt>
          <dd>
            {value === null || value === undefined ? (
              "Unavailable"
            ) : typeof value === "object" ? (
              <pre>{JSON.stringify(value, null, 2)}</pre>
            ) : (
              String(value)
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}
