import { OceanCurrentWorkspace } from "./OceanCurrentWorkspace";
import { LunarContextPanel } from "./LunarContextPanel";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import type { Project } from "../../api/client";
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "../../components/ui/AsyncState";
import {
  ScientificRecordCard,
  SOURCE_LABELS,
  utcTime,
  sourceUrl,
} from "./ScientificRecordCard";
import { EnvironmentalSubjectInspector } from "./EnvironmentalSubjectInspector";
import {
  getScientificRecords,
  importNOAARecords,
  importScientificRecords,
  type ScientificRecordCreate,
  type ScientificSourceKind,
} from "./environmentalContextApi";

const PAGE_SIZE = 100;
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

export function EnvironmentalContextPanel({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const [offset, setOffset] = useState(0);
  const [variableInput, setVariableInput] = useState("");
  const [sourceInput, setSourceInput] = useState<ScientificSourceKind | "">("");
  const [filters, setFilters] = useState<{
    variable: string;
    sourceKind: ScientificSourceKind | "";
  }>({ variable: "", sourceKind: "" });
  const [file, setFile] = useState<File | null>(null);
  const [stationId, setStationId] = useState("");
  const [day, setDay] = useState("");
  const [offline, setOffline] = useState(false);
  const recordsQuery = useQuery({
    queryKey: [
      "scientific-records",
      project.id,
      { limit: PAGE_SIZE, offset, ...filters },
    ],
    queryFn: ({ signal }) =>
      getScientificRecords(
        project.id,
        { limit: PAGE_SIZE, offset, ...filters },
        signal,
      ),
  });
  const refreshRecords = async () => {
    setOffset(0);
    await queryClient.invalidateQueries({
      queryKey: ["scientific-records", project.id],
    });
  };
  const sensorMutation = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("Choose a sensor JSON file first.");
      return importScientificRecords(project.id, await readSensorFile(file));
    },
    onSuccess: refreshRecords,
  });
  const noaaMutation = useMutation({
    mutationFn: () =>
      importNOAARecords(project.id, { station_id: stationId, day, offline }),
    onSuccess: refreshRecords,
  });
  const records = recordsQuery.data;
  const importing = sensorMutation.isPending || noaaMutation.isPending;
  const noaaLink = sourceUrl(noaaMutation.data?.source_url);

  return (
    <section
      className="feature-workspace"
      aria-label="Environmental Context workspace"
    >
      <div className="section-heading">
        <div>
          <p className="eyebrow">Project scientific records</p>
          <h2>Environmental Context</h2>
          <p>
            Inspect sensor measurements and environmental observations with
            their original units, normalized quantities, quality flags, and
            source provenance.
          </p>
        </div>
      </div>
      <div className="training-card-grid">
        <form
          className="panel-card training-content"
          onSubmit={(event) => {
            event.preventDefault();
            sensorMutation.mutate();
          }}
        >
          <h3>Local sensor JSON</h3>
          <p>
            Choose a JSON object containing a <code>records</code> array. Each
            record needs a variable, value, unit, observation timestamp with UTC
            offset, source kind, and provenance with source and acquisition
            time.
          </p>
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
          <button type="submit" disabled={!file || importing}>
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
          className="panel-card training-content"
          onSubmit={(event) => {
            event.preventDefault();
            noaaMutation.mutate();
          }}
        >
          <h3>NOAA station data</h3>
          <p>
            Import station water temperature for one UTC day. Station
            measurements describe the station location; their measurement depth
            may be unknown.
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
          <button
            type="submit"
            disabled={importing || !/^\d{7}$/.test(stationId) || !day}
          >
            {noaaMutation.isPending
              ? "Importing NOAA data…"
              : "Import NOAA data"}
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
                {noaaMutation.data.items.length} records available. Missing
                values skipped: {noaaMutation.data.skipped_missing}
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
      </div>
      <section className="training-content" aria-label="Scientific records">
        <h3>Saved scientific records</h3>
        <form
          className="training-form-grid"
          onSubmit={(event) => {
            event.preventDefault();
            setOffset(0);
            setFilters({
              variable: variableInput.trim(),
              sourceKind: sourceInput,
            });
          }}
        >
          <label>
            Variable filter
            <input
              value={variableInput}
              placeholder="All variables"
              onChange={(event) => setVariableInput(event.target.value)}
            />
          </label>
          <label>
            Source kind filter
            <select
              value={sourceInput}
              onChange={(event) =>
                setSourceInput(event.target.value as ScientificSourceKind | "")
              }
            >
              <option value="">All source kinds</option>
              {Object.entries(SOURCE_LABELS).map(([kind, label]) => (
                <option key={kind} value={kind}>
                  {label} sources
                </option>
              ))}
            </select>
          </label>
          <button type="submit">Apply filters</button>
        </form>
        {recordsQuery.isPending && (
          <LoadingState
            title="Loading scientific records"
            description="Reading saved records for this project."
          />
        )}
        {recordsQuery.error && (
          <ErrorState
            title="Scientific records could not be loaded"
            message={recordsQuery.error.message}
            onRetry={() => {
              void recordsQuery.refetch();
            }}
          />
        )}
        {recordsQuery.isSuccess && records && (
          <>
            {records.items.length === 0 ? (
              <EmptyState
                title={
                  filters.variable || filters.sourceKind
                    ? "No records match these filters"
                    : "No scientific records yet"
                }
                description="Import local sensor JSON or NOAA station data to add environmental context."
              />
            ) : (
              records.items.map((record) => (
                <div key={record.id}>
                  <ScientificRecordCard record={record} />
                  {record.variable === "geographic_position" &&
                    record.subject && (
                      <EnvironmentalSubjectInspector
                        projectId={project.id}
                        subject={record.subject}
                      />
                    )}
                </div>
              ))
            )}
            <nav className="pagination" aria-label="Scientific record pages">
              <button
                type="button"
                disabled={offset === 0 || recordsQuery.isFetching}
                onClick={() =>
                  setOffset((current) => Math.max(0, current - PAGE_SIZE))
                }
              >
                Previous page
              </button>
              <span role="status">
                Records {records.items.length ? offset + 1 : 0}–
                {offset + records.items.length} of {records.total}
              </span>
              <button
                type="button"
                disabled={
                  offset + PAGE_SIZE >= records.total || recordsQuery.isFetching
                }
                onClick={() => setOffset((current) => current + PAGE_SIZE)}
              >
                Next page
              </button>
            </nav>
          </>
        )}
      </section>
      <OceanCurrentWorkspace key={project.id} projectId={project.id} />
      <LunarContextPanel key={project.id} projectId={project.id} />
    </section>
  );
}
