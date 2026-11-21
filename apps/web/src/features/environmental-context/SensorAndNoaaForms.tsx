import { useMutation } from "@tanstack/react-query";
import { useId, useState } from "react";
import { ErrorState } from "../../components/ui/AsyncState";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { sourceUrl, utcTime } from "./ScientificRecordCard";
import {
  importNOAARecords,
  importScientificRecords,
  type ScientificRecordCreate,
} from "./environmentalContextApi";

const CACHE_LABELS = {
  downloaded: "Downloaded from NOAA",
  fresh: "Fresh cached data",
  stale_offline: "Stale cache used offline",
};

function readSensorFile(
  file: File,
): Promise<{ records: ScientificRecordCreate[] }> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () =>
      reject(new Error("The selected JSON file could not be read."));
    reader.onload = () => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(String(reader.result));
      } catch {
        reject(new Error("The selected file is not valid JSON."));
        return;
      }
      if (
        !parsed ||
        typeof parsed !== "object" ||
        !("records" in parsed) ||
        !Array.isArray(parsed.records) ||
        parsed.records.length < 1 ||
        parsed.records.length > 5000
      ) {
        reject(
          new Error(
            "The JSON file must contain a records array with 1 to 5000 records.",
          ),
        );
        return;
      }
      // The backend validates units, subjects, timestamps, and each record's provenance.
      resolve(parsed as { records: ScientificRecordCreate[] });
    };
    reader.readAsText(file);
  });
}

export function SensorAndNoaaForms({
  projectId,
  source,
  onImported,
}: {
  projectId: string;
  source: "local" | "noaa" | null;
  onImported: () => Promise<void>;
}) {
  const fileHint = useId();
  const noaaHint = useId();
  const [file, setFile] = useState<File | null>(null);
  const [stationId, setStationId] = useState("");
  const [day, setDay] = useState("");
  const [offline, setOffline] = useState(false);
  const sensorMutation = useMutation({
    mutationKey: ["environment-workspace", projectId, "Sensor JSON import"],
    mutationFn: async () => {
      if (!file) throw new Error("Choose a sensor JSON file first.");
      return importScientificRecords(projectId, await readSensorFile(file));
    },
    onSuccess: onImported,
  });
  const noaaMutation = useMutation({
    mutationKey: ["environment-workspace", projectId, "NOAA station import"],
    mutationFn: () =>
      importNOAARecords(projectId, { station_id: stationId, day, offline }),
    onSuccess: onImported,
  });
  const importing = sensorMutation.isPending || noaaMutation.isPending;
  const noaaLink = sourceUrl(noaaMutation.data?.source_url);

  return (
    <>
      <form
        hidden={source !== "local"}
        className="panel-card training-content"
        onSubmit={(event) => {
          event.preventDefault();
          sensorMutation.mutate();
        }}
      >
        <p className="secondary-text">
          Import measurements from a local sensor file.
        </p>
        <details className="rv-advanced">
          <summary>Sensor JSON format</summary>
          <div>
            <p>
              Use a JSON object with a <code>records</code> array of 1 to 5,000
              entries. Include variable, value, unit, a timestamp with UTC
              offset, source kind, and provenance with source and acquisition
              time.
            </p>
            <pre className="json-block">
              {JSON.stringify(
                {
                  records: [
                    {
                      variable: "water_temperature",
                      value: 20,
                      unit: "degC",
                      observed_at: "2026-04-03T13:00:00Z",
                      source_kind: "observed",
                      provenance: {
                        source: "Sensor name",
                        acquired_at: "2026-04-03T13:01:00Z",
                      },
                    },
                  ],
                },
                null,
                2,
              )}
            </pre>
          </div>
        </details>
        <label>
          Sensor JSON file
          <input
            type="file"
            accept=".json,application/json"
            disabled={importing}
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              sensorMutation.reset();
            }}
          />
        </label>
        {!file && (
          <p id={fileHint} className="secondary-text">
            Choose a JSON file to enable import.
          </p>
        )}
        <button
          type="submit"
          disabled={!file || importing}
          aria-describedby={!file ? fileHint : undefined}
        >
          {sensorMutation.isPending
            ? "Importing sensor JSON…"
            : "Import sensor JSON"}
        </button>
        {sensorMutation.error && (
          <ErrorState
            title="Sensor import failed"
            message={sensorMutation.error.message}
          />
        )}
        {sensorMutation.isSuccess && (
          <p role="status">
            Imported {sensorMutation.data.total} scientific{" "}
            {sensorMutation.data.total === 1 ? "record" : "records"}.
          </p>
        )}
      </form>
      <form
        hidden={source !== "noaa"}
        className="panel-card training-content"
        onSubmit={(event) => {
          event.preventDefault();
          noaaMutation.mutate();
        }}
      >
        <p>
          Import station water temperature for one UTC day. Station measurements
          describe the station location; their measurement depth may be unknown.
        </p>
        <div className="training-form-grid">
          <label>
            NOAA station ID
            <input
              inputMode="numeric"
              pattern="[0-9]{7}"
              maxLength={7}
              required
              placeholder="7-digit station ID"
              value={stationId}
              onChange={(event) => {
                setStationId(event.target.value);
                noaaMutation.reset();
              }}
              disabled={importing}
            />
          </label>
          <label>
            Observation day (UTC)
            <input
              type="date"
              required
              value={day}
              onChange={(event) => {
                setDay(event.target.value);
                noaaMutation.reset();
              }}
              disabled={importing}
            />
          </label>
        </div>
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={offline}
            onChange={(event) => {
              setOffline(event.target.checked);
              noaaMutation.reset();
            }}
            disabled={importing}
          />
          Use cached data only (offline)
        </label>
        {(!/^\d{7}$/.test(stationId) || !day) && (
          <p id={noaaHint} className="secondary-text">
            Enter a seven-digit station ID and a UTC day.
          </p>
        )}
        <button
          type="submit"
          aria-describedby={
            !/^\d{7}$/.test(stationId) || !day ? noaaHint : undefined
          }
          disabled={importing || !/^\d{7}$/.test(stationId) || !day}
        >
          {noaaMutation.isPending ? "Importing NOAA data…" : "Import NOAA data"}
        </button>
        {noaaMutation.error && (
          <ErrorState
            title="NOAA import failed"
            message={noaaMutation.error.message}
          />
        )}
        {noaaMutation.isSuccess && (
          <div role="status" aria-label="NOAA import result">
            <p>
              <StatusBadge
                status={
                  noaaMutation.data.cache_status === "stale_offline"
                    ? "warning"
                    : "ready"
                }
                label={CACHE_LABELS[noaaMutation.data.cache_status]}
              />
            </p>
            <p>
              {noaaMutation.data.items.length} records available. Missing values
              skipped: {noaaMutation.data.skipped_missing}
            </p>
            <p>Fetched: {utcTime(noaaMutation.data.fetched_at)}</p>
            <p>Cache expires: {utcTime(noaaMutation.data.expires_at)}</p>
            {noaaLink && (
              <a href={noaaLink} target="_blank" rel="noreferrer">
                NOAA source
              </a>
            )}
          </div>
        )}
      </form>
    </>
  );
}
