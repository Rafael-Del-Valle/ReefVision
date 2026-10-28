import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { OpenStreetMapView } from "../video/OpenStreetMapView";
import { getVideos } from "../video/videoApi";
import { getVideoGeoreferencedObservations } from "../video/videoGeoreferencedObservationsApi";
import {
  currentComponentUncertaintyText,
  currentVectors,
  currentVectorsCsv,
  vectorColor,
} from "./currentVectors";
import {
  getCachedDataset,
  getEnvironmentalDatasets,
  importCopernicus,
  type CopernicusRequest,
} from "./environmentalContextApi";
import { utcTime } from "./ScientificRecordCard";

export function OceanCurrentWorkspace({ projectId }: { projectId: string }) {
  const [open, setOpen] = useState(false);
  const [cacheKey, setCacheKey] = useState("");
  const [offset, setOffset] = useState(0);
  const [time, setTime] = useState("");
  const [depth, setDepth] = useState("");
  const [visible, setVisible] = useState(true);
  const [basemap, setBasemap] = useState(false);
  const [showObjects, setShowObjects] = useState(false);
  const [videoId, setVideoId] = useState("");
  const [extent, setExtent] = useState<[[number, number], [number, number]]>();
  const [extentInput, setExtentInput] = useState({
    west: "",
    east: "",
    south: "",
    north: "",
  });
  const [extentError, setExtentError] = useState("");
  const datasets = useQuery({
    queryKey: ["environment-datasets", projectId, offset],
    enabled: open,
    queryFn: ({ signal }) =>
      getEnvironmentalDatasets(projectId, offset, signal),
  });
  const dataset = useQuery({
    queryKey: ["environment-dataset", projectId, cacheKey],
    enabled: open && Boolean(cacheKey),
    queryFn: ({ signal }) => getCachedDataset(projectId, cacheKey, signal),
  });
  const videos = useQuery({
    queryKey: ["ocean-overlay-videos", projectId],
    enabled: open && showObjects,
    queryFn: ({ signal }) => getVideos(projectId, signal),
  });
  const objects = useQuery({
    queryKey: ["ocean-overlay", projectId, videoId],
    enabled: open && showObjects && Boolean(videoId),
    queryFn: ({ signal }) =>
      getVideoGeoreferencedObservations(videoId, {}, signal),
  });
  const times = useMemo(
    () =>
      [
        ...new Set(dataset.data?.items.map((row) => row.observed_at) ?? []),
      ].sort(),
    [dataset.data],
  );
  const depths = useMemo(
    () =>
      [
        ...new Set(
          dataset.data?.items.flatMap((row) =>
            row.depth_m == null ? [] : [row.depth_m],
          ) ?? [],
        ),
      ].sort((a, b) => a - b),
    [dataset.data],
  );
  const selectedTime = time || times[0];
  const selectedDepth = depth === "" ? depths[0] : Number(depth);
  const vectors = useMemo(
    () =>
      currentVectors(
        dataset.data?.items.filter(
          (row) =>
            row.observed_at === selectedTime && row.depth_m === selectedDepth,
        ) ?? [],
      ),
    [dataset.data, selectedTime, selectedDepth],
  );
  const overlay = useMemo(
    () =>
      showObjects
        ? (objects.data?.items ?? []).filter(
            (row) =>
              row.project_id === projectId &&
              row.is_stale === false &&
              row.location.crs === "EPSG:4326",
          )
        : [],
    [objects.data, showObjects, projectId],
  );
  return (
    <section className="management-card" aria-label="Ocean currents">
      <h3>Ocean current vectors</h3>
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? "Close ocean current map" : "Open ocean current map"}
      </button>
      {open && (
        <>
          <p>
            Arrows show direction toward true north from paired
            eastward/northward velocities at model grid cells. Colors show speed
            in m/s. No interpolation or particle simulation is used. Arrow
            length is a display symbol, not travel distance.
          </p>
          <label>
            Cached ocean dataset
            <select
              value={cacheKey}
              onChange={(e) => {
                setCacheKey(e.target.value);
                setTime("");
                setDepth("");
                setExtent(undefined);
              }}
            >
              <option value="">Choose cached dataset</option>
              {datasets.data?.items.map((item) => (
                <option key={item.cache_key} value={item.cache_key}>
                  {item.provider} · {item.record_count} values ·{" "}
                  {utcTime(item.fetched_at)} · {item.cache_key.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          {(datasets.data?.total ?? 0) > 100 && (
            <div>
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - 100))}
              >
                Previous datasets
              </button>
              <button
                type="button"
                disabled={offset + 100 >= (datasets.data?.total ?? 0)}
                onClick={() => setOffset(offset + 100)}
              >
                Next datasets
              </button>
            </div>
          )}
          {(datasets.error || dataset.error) && (
            <p role="alert">{(datasets.error || dataset.error)?.message}</p>
          )}
          {(datasets.isFetching || dataset.isFetching) && (
            <p role="status">Opening local cache…</p>
          )}
          {dataset.data && (
            <>
              <p>
                Available offline · {dataset.data.cache_status} · fetched{" "}
                {utcTime(dataset.data.fetched_at)} · expires{" "}
                {utcTime(dataset.data.expires_at)}.
              </p>
              <label>
                Current time (UTC)
                <select
                  value={selectedTime ?? ""}
                  onChange={(e) => setTime(e.target.value)}
                >
                  {times.map((value) => (
                    <option key={value} value={value}>
                      {utcTime(value)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Current depth (m; source datum shown per vector)
                <select
                  value={selectedDepth ?? ""}
                  onChange={(e) => setDepth(e.target.value)}
                >
                  {depths.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={visible}
                  onChange={(e) => setVisible(e.target.checked)}
                />
                Show current vectors
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={basemap}
                  onChange={(e) => setBasemap(e.target.checked)}
                />
                Online basemap tiles
              </label>
              <p>
                Cached vector geometry remains available without map tiles. Map
                uses Web Mercator; polar samples above 85° latitude remain in
                the table.
              </p>
              <div aria-label="Current speed legend">
                {[
                  [0, "0–0.25"],
                  [0.25, "0.25–0.5"],
                  [0.5, "0.5–1"],
                  [1, "≥1"],
                ].map(([value, label]) => (
                  <span
                    key={label}
                    style={{
                      color: vectorColor(Number(value)),
                      marginRight: "1rem",
                    }}
                  >
                    ● {label} m/s
                  </span>
                ))}
              </div>
              <button
                type="button"
                disabled={vectors.length === 0}
                onClick={() => {
                  if (!dataset.data || vectors.length === 0) return;
                  const csv = currentVectorsCsv(vectors, {
                    cacheKey,
                    cacheStatus: dataset.data.cache_status,
                    fetchedAt: dataset.data.fetched_at,
                    expiresAt: dataset.data.expires_at,
                  });
                  const url = URL.createObjectURL(
                    new Blob([csv], { type: "text/csv;charset=utf-8" }),
                  );
                  const link = document.createElement("a");
                  link.href = url;
                  link.download = "reefvision-current-vectors.csv";
                  document.body.append(link);
                  link.click();
                  link.remove();
                  window.setTimeout(() => URL.revokeObjectURL(url), 0);
                }}
              >
                Export current vector summary CSV
              </button>
              <p>
                Summary export includes the selected time/depth, component
                record IDs, depth reference, per-component QC, units, cache
                provenance and known component uncertainties. Derived speed/bearing uncertainty is not
                estimated. Original scientific records remain the authoritative
                source.
              </p>
              {vectors.length === 0 && (
                <p role="status">
                  Current vectors unavailable: this time/depth has no unique
                  compatible east/north pair passing QC.
                </p>
              )}
              <OpenStreetMapView
                observations={overlay}
                currentVectors={visible ? vectors : []}
                showBasemap={basemap}
                mapExtent={extent}
                showTrackLines={showObjects}
              />
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  const { west, east, south, north } = Object.fromEntries(
                    Object.entries(extentInput).map(([key, value]) => [
                      key,
                      Number(value),
                    ]),
                  );
                  if (west >= east || south >= north) {
                    setExtentError("Map bounds must be ordered.");
                    return;
                  }
                  setExtentError("");
                  setExtent([
                    [south, west],
                    [north, east],
                  ]);
                }}
              >
                {(["west", "east", "south", "north"] as const).map((key) => (
                  <label key={key}>
                    Map {key}
                    <input
                      required
                      type="number"
                      step="any"
                      min={key === "west" || key === "east" ? -180 : -85}
                      max={key === "west" || key === "east" ? 180 : 85}
                      value={extentInput[key]}
                      onChange={(e) =>
                        setExtentInput({
                          ...extentInput,
                          [key]: e.target.value,
                        })
                      }
                    />
                  </label>
                ))}
                <button type="submit">Set geographic extent</button>
                <button type="button" onClick={() => setExtent(undefined)}>
                  Fit data extent
                </button>
                {extentError && <p role="alert">{extentError}</p>}
              </form>
              <label>
                <input
                  type="checkbox"
                  checked={showObjects}
                  onChange={(e) => setShowObjects(e.target.checked)}
                />
                Overlay georeferenced organisms
              </label>
              {showObjects && (
                <>
                  <p>
                    Spatial comparison only: track UTC alignment is not
                    established. Only current WGS84 georeferencing is shown;
                    stale positions are excluded.
                  </p>
                  <label>
                    Overlay video
                    <select
                      value={videoId}
                      onChange={(e) => setVideoId(e.target.value)}
                    >
                      <option value="">Choose video</option>
                      {videos.data?.map((video) => (
                        <option key={video.id} value={video.id}>
                          {video.original_filename}
                        </option>
                      ))}
                    </select>
                  </label>
                  {(objects.error || videos.error) && (
                    <p role="alert">
                      {(objects.error || videos.error)?.message}
                    </p>
                  )}
                  <p>{overlay.length} compatible geographic detections.</p>
                </>
              )}
              <ul aria-label="Current measurements">
                {vectors.map((vector) => (
                  <li key={vector.id}>
                    <strong>{vector.speed.toFixed(3)} m/s</strong> ·{" "}
                    {vector.bearing === null
                      ? "Stationary"
                      : `${vector.bearing.toFixed(1)}° toward true north`}{" "}
                    · {vector.latitude}, {vector.longitude} · {vector.depthM} m ({vector.depthReference})
                    <br />
                    {vector.sourceKind === "modeled"
                      ? "Modeled"
                      : vector.sourceKind}{" "}
                    · {vector.dataset} · version{" "}
                    {vector.modelVersion ?? "unknown"} · {vector.source}
                    <br />
                    Component QC: east {vector.eastQc}; north {vector.northQc}.
                    <br />
                    Vector speed/direction and position uncertainty: not
                    estimated.
                    <br />
                    {currentComponentUncertaintyText(
                      "East",
                      vector.eastUncertainty,
                    )}{" "}
                    ·{" "}
                    {currentComponentUncertaintyText(
                      "North",
                      vector.northUncertainty,
                    )}
                    <br />
                    Source record IDs: {vector.recordIds.join(", ")}
                  </li>
                ))}
              </ul>
            </>
          )}
          <CopernicusImportForm projectId={projectId} />
        </>
      )}
    </section>
  );
}
function CopernicusImportForm({ projectId }: { projectId: string }) {
  const client = useQueryClient();
  const [values, setValues] = useState({
    dataset_id: "",
    dataset_version: "",
    minimum_longitude: "",
    maximum_longitude: "",
    minimum_latitude: "",
    maximum_latitude: "",
    minimum_depth: "0",
    maximum_depth: "10",
    start_datetime: "",
    end_datetime: "",
  });
  const [variables, setVariables] = useState<CopernicusRequest["variables"]>([
    "uo",
    "vo",
  ]);
  const [offline, setOffline] = useState(true);
  const [refresh, setRefresh] = useState(false);
  const mutation = useMutation({
    mutationFn: () =>
      importCopernicus(projectId, {
        dataset_id: values.dataset_id,
        dataset_version: values.dataset_version,
        variables,
        minimum_longitude: Number(values.minimum_longitude),
        maximum_longitude: Number(values.maximum_longitude),
        minimum_latitude: Number(values.minimum_latitude),
        maximum_latitude: Number(values.maximum_latitude),
        minimum_depth: Number(values.minimum_depth),
        maximum_depth: Number(values.maximum_depth),
        start_datetime: new Date(values.start_datetime + "Z").toISOString(),
        end_datetime: new Date(values.end_datetime + "Z").toISOString(),
        offline,
        refresh: !offline && refresh,
      }),
    onSuccess: async () => {
      await client.invalidateQueries({
        queryKey: ["environment-datasets", projectId],
      });
      await client.invalidateQueries({
        queryKey: ["environment-dataset", projectId],
      });
      await client.invalidateQueries({
        queryKey: ["scientific-records", projectId],
      });
    },
  });
  return (
    <details>
      <summary>Acquire Copernicus modeled data</summary>
      <p>
        Requires a configured optional Copernicus Toolbox runtime and backend
        credentials. Credentials stay outside project records and exports.
        Maximum request: 5° × 5°, 7 days, 5,000 values, 90 seconds. Select a
        pinned model dataset/version. Ambiguous salinity scales are rejected;
        thetao remains potential temperature.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate();
        }}
      >
        {Object.entries(values).map(([key, value]) => (
          <label key={key}>
            {key.replaceAll("_", " ")}
            {key.endsWith("datetime") ? " (UTC)" : ""}
            <input
              required
              type={
                key.endsWith("datetime")
                  ? "datetime-local"
                  : key.startsWith("minimum") || key.startsWith("maximum")
                    ? "number"
                    : "text"
              }
              step="any"
              value={value}
              onChange={(e) => setValues({ ...values, [key]: e.target.value })}
            />
          </label>
        ))}
        {(["uo", "vo", "thetao", "so"] as const).map((variable) => (
          <label key={variable}>
            <input
              type="checkbox"
              checked={variables.includes(variable)}
              onChange={(e) =>
                setVariables(
                  e.target.checked
                    ? [...variables, variable]
                    : variables.filter((value) => value !== variable),
                )
              }
            />
            {
              {
                uo: "Eastward current",
                vo: "Northward current",
                thetao: "Potential temperature",
                so: "Practical salinity",
              }[variable]
            }
          </label>
        ))}
        <label>
          <input
            type="checkbox"
            checked={offline}
            onChange={(e) => setOffline(e.target.checked)}
          />
          Copernicus cached data only
        </label>
        <label>
          <input
            type="checkbox"
            disabled={offline}
            checked={refresh}
            onChange={(e) => setRefresh(e.target.checked)}
          />
          Refresh Copernicus data now
        </label>
        <button
          type="submit"
          disabled={mutation.isPending || variables.length === 0}
        >
          Acquire Copernicus subset
        </button>
        {mutation.error && <p role="alert">{mutation.error.message}</p>}
        {mutation.data && (
          <p role="status">
            {mutation.data.items.length} modeled values ·{" "}
            {mutation.data.cache_status} · {mutation.data.skipped_missing}{" "}
            missing values skipped.
          </p>
        )}
      </form>
    </details>
  );
}
