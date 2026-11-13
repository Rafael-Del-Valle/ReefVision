import { StatusBadge } from "../../components/ui/StatusBadge";
import type {
  ScientificRecord,
  ScientificSourceKind,
} from "./environmentalContextApi";
export const SOURCE_LABELS: Record<ScientificSourceKind, string> = {
  observed: "Observed",
  remotely_sensed: "Remotely sensed",
  modeled: "Modeled",
  derived: "Derived",
};
export function utcTime(value: string): string {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "Unknown time";
  return date
    .toISOString()
    .replace("T", " ")
    .replace(/\.000Z$/, " UTC")
    .replace(/Z$/, " UTC");
}

export function sourceUrl(
  value: string | null | undefined,
): string | undefined {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:"
      ? url.href
      : undefined;
  } catch {
    return undefined;
  }
}

export function ScientificRecordCard({ record }: { record: ScientificRecord }) {
  const provenance = record.provenance;
  const link = sourceUrl(provenance.source_url);
  return (
    <article className="panel-card" aria-label={record.variable}>
      <h4>{record.variable}</h4>
      {record.environmental_snapshot_current === false && (
        <p role="status">
          Historical provider snapshot; excluded from current environmental
          lookup.
        </p>
      )}
      <dl className="training-kv-grid">
        <div>
          <dt>Original quantity</dt>
          <dd>
            {record.value} {record.unit}
          </dd>
        </div>
        <div>
          <dt>Normalized quantity</dt>
          <dd>
            {record.normalized_value} {record.normalized_unit}
          </dd>
        </div>
        <div>
          <dt>Observation time</dt>
          <dd>
            <time dateTime={record.observed_at}>
              {utcTime(record.observed_at)}
            </time>
          </dd>
        </div>
        <div>
          <dt>Depth</dt>
          <dd>
            {record.depth_m == null
              ? "Unknown depth"
              : `${record.depth_m} m (${record.depth_reference})`}
          </dd>
        </div>
        <div>
          <dt>Source kind</dt>
          <dd>{SOURCE_LABELS[record.source_kind]}</dd>
        </div>
        <div>
          <dt>Quality control</dt>
          <dd>
            <StatusBadge
              status={record.qc ?? "unassessed"}
              label={(record.qc ?? "unassessed").replace(/^./, (letter) =>
                letter.toUpperCase(),
              )}
            />
          </dd>
        </div>
        <div>
          <dt>Source</dt>
          <dd>{provenance.source}</dd>
        </div>
        <div>
          <dt>Location</dt>
          <dd>
            {record.location
              ? `${record.location.latitude}, ${record.location.longitude} (${record.location.crs ?? "EPSG:4326"})`
              : "Unknown location"}
          </dd>
        </div>
      </dl>
      {Boolean(record.qc_flags?.length) && (
        <p>
          QC flags: <span>{record.qc_flags?.join(", ")}</span>
        </p>
      )}
      {record.uncertainty && (
        <p>
          Original uncertainty: {record.uncertainty.value} {record.unit} (
          {record.uncertainty.kind})
        </p>
      )}
      {record.normalized_uncertainty != null && (
        <p>
          Normalized uncertainty: {record.normalized_uncertainty}{" "}
          {record.normalized_unit}
        </p>
      )}
      <details>
        <summary>Provenance and record details</summary>
        <dl className="training-kv-grid">
          <div>
            <dt>Acquired</dt>
            <dd>{utcTime(provenance.acquired_at)}</dd>
          </div>
          <div>
            <dt>Method</dt>
            <dd>{provenance.method ?? "Not recorded"}</dd>
          </div>
          <div>
            <dt>Dataset</dt>
            <dd>{provenance.dataset_id ?? "Not recorded"}</dd>
          </div>
          <div>
            <dt>Model version</dt>
            <dd>
              {provenance.model_version ?? "Not applicable / not recorded"}
            </dd>
          </div>
        </dl>
        {link && (
          <p>
            <a href={link} target="_blank" rel="noreferrer">
              Source reference
            </a>
          </p>
        )}
        <p>
          Record checksum: <code>{record.content_sha256}</code>
        </p>
        {record.calibration_current === false && (
          <p role="status">
            The source calibration has changed since this record was saved.
          </p>
        )}
        <pre className="json-block">
          {JSON.stringify(
            {
              id: record.id,
              subject: record.subject,
              pixel: record.pixel,
              provenance,
              calibration_snapshot: record.calibration_snapshot,
              calibration_sha256: record.calibration_sha256,
              calibration_current: record.calibration_current,
            },
            null,
            2,
          )}
        </pre>
      </details>
    </article>
  );
}
