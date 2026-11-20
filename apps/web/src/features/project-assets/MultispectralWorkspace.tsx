import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { SpectralImport } from "./SpectralImport";
import {
  computeIndex,
  saveIndexGraph,
  spectralList,
  spectralUrl,
  type Capture,
  type Index,
  type Receipt,
} from "./multispectralApi";

function BandChoice({
  label,
  bands,
  value,
  onChange,
}: {
  label: string;
  bands: Capture["bands"];
  value: number;
  onChange: (index: number) => void;
}) {
  return (
    <label>
      {label}
      <select value={value} onChange={(e) => onChange(Number(e.target.value))}>
        {bands.map((b, i) => (
          <option key={b.image_id} value={i}>
            {b.name} · {b.wavelength_nm} nm
          </option>
        ))}
      </select>
    </label>
  );
}

function SpectralPreview({
  record,
  onIndex,
}: {
  record: Receipt<Capture>;
  onIndex: (value: Receipt<Index>) => void;
}) {
  const [red, setRed] = useState(1),
    [green, setGreen] = useState(0),
    [blue, setBlue] = useState(0);
  const [positive, setPositive] = useState(1),
    [negative, setNegative] = useState(0);
  const calculate = useMutation({
    mutationFn: () =>
      computeIndex(record.project_id, record, positive, negative),
    onSuccess: onIndex,
  });
  const data = record.snapshot;
  const composite = useQuery({
    queryKey: [
      "spectral-composite",
      record.project_id,
      record.id,
      record.content_sha256,
      red,
      green,
      blue,
    ],
    enabled: !!data.alignment,
    queryFn: async ({ signal }) => {
      const response = await fetch(
        spectralUrl(
          record.project_id,
          `/acquisitions/${record.id}/composite?red=${red}&green=${green}&blue=${blue}`,
        ),
        { signal },
      );
      if (!response.ok)
        throw new Error(
          (await response.json()).detail ??
            "The composite could not be rendered.",
        );
      return response.blob();
    },
  });
  const [preview, setPreview] = useState("");
  useEffect(() => {
    if (!composite.data) {
      setPreview("");
      return;
    }
    const url = URL.createObjectURL(composite.data);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [composite.data]);
  return (
    <section className="panel" aria-label="Spectral acquisition">
      <h3>{data.label}</h3>
      <p>
        {data.sensor} · {data.bands.length} bands · {data.bands[0].width} ×{" "}
        {data.bands[0].height} reference pixels
      </p>
      {data.alignment ? (
        <>
          <p>
            Grid {data.alignment.grid}, reviewed by {data.alignment.reviewer}.
            Maximum residual {data.alignment.maximum_residual_px} px.{" "}
            {data.alignment.evidence}
          </p>
          <fieldset>
            <legend>Composite display channels</legend>
            <BandChoice
              label="Red channel"
              bands={data.bands}
              value={red}
              onChange={setRed}
            />
            <BandChoice
              label="Green channel"
              bands={data.bands}
              value={green}
              onChange={setGreen}
            />
            <BandChoice
              label="Blue channel"
              bands={data.bands}
              value={blue}
              onChange={setBlue}
            />
          </fieldset>
          {preview && (
            <img
              className="spectral-composite-preview"
              src={preview}
              alt="Selected bands on the registered source-pixel grid"
            />
          )}
          {composite.error && <p role="alert">{composite.error.message}</p>}
        </>
      ) : (
        <p>
          Record a reviewed common grid to view a composite. Individual
          originals are available in Images &amp; annotation.
        </p>
      )}
      <fieldset>
        <legend>Normalized difference</legend>
        <BandChoice
          label="Positive band"
          bands={data.bands}
          value={positive}
          onChange={setPositive}
        />
        <BandChoice
          label="Negative band"
          bands={data.bands}
          value={negative}
          onChange={setNegative}
        />
        <button
          type="button"
          disabled={positive === negative || calculate.isPending}
          onClick={() => calculate.mutate()}
        >
          Calculate spectral index
        </button>
        {calculate.error && <p role="alert">{calculate.error.message}</p>}
      </fieldset>
    </section>
  );
}

async function download(record: Receipt<Index>, format: "export" | "raster") {
  const response = await fetch(
    spectralUrl(record.project_id, `/indices/${record.id}/${format}`),
    { signal: AbortSignal.timeout(60_000) },
  );
  if (!response.ok)
    throw new Error(
      (await response.json()).detail ?? "The spectral download failed.",
    );
  const blob = await response.blob();
  if (format === "export") {
    const result = JSON.parse(await blob.text()) as Receipt<Index>;
    if (
      result.id !== record.id ||
      result.content_sha256 !== record.content_sha256
    )
      throw new Error("The exported receipt differs from the selected result.");
  }
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = `multispectral-${record.id}.${format === "export" ? "json" : "tif"}`;
    a.click();
  } finally {
    URL.revokeObjectURL(url);
  }
}

function SavedIndex({
  record,
  onOpenWorkflow,
}: {
  record: Receipt<Index>;
  onOpenWorkflow: () => void;
}) {
  const cache = useQueryClient();
  const save = useMutation({
    mutationFn: () => saveIndexGraph(record),
    onSuccess: async () => {
      await cache.invalidateQueries({
        queryKey: ["workflow-graphs", record.project_id],
      });
      onOpenWorkflow();
    },
  });
  const file = useMutation({
    mutationFn: (format: "export" | "raster") => download(record, format),
  });
  const { result, selection, acquisition } = record.snapshot;
  return (
    <section className="panel" aria-label="Saved spectral index">
      <h3>{acquisition.label} · spectral index</h3>
      <p>
        ({acquisition.bands[selection.positive].name} −{" "}
        {acquisition.bands[selection.negative].name}) / (
        {acquisition.bands[selection.positive].name} +{" "}
        {acquisition.bands[selection.negative].name})
      </p>
      {result.status === "withheld" ? (
        <p role="status">Withheld. {result.reasons.join(" ")}</p>
      ) : (
        <>
          <p>
            Mean normalized difference {result.mean?.toPrecision(6)} · range{" "}
            {result.minimum?.toPrecision(5)} to {result.maximum?.toPrecision(5)}{" "}
            (unitless).
          </p>
          <p>
            {result.valid_pixels} of {result.reference_pixels} reference pixels
            contributed. Outside the common grid {result.excluded.outside_grid},
            invalid samples {result.excluded.invalid_band_sample}, zero
            denominator {result.excluded.zero_denominator}.
          </p>
        </>
      )}
      <details>
        <summary>Source bands and calibration</summary>
        {acquisition.bands.map((b) => (
          <p key={b.image_id}>
            {b.name}, {b.wavelength_nm} nm · {b.bits} bits ·{" "}
            {b.calibration
              ? `${b.calibration.reference}, dark ${b.calibration.dark_dn} DN, white ${b.calibration.white_dn} DN at ${b.calibration.white_reflectance} reflectance`
              : "No reflectance calibration"}{" "}
            · <code>{b.original_sha256}</code>
          </p>
        ))}
      </details>
      <button
        type="button"
        disabled={file.isPending}
        onClick={() => file.mutate("export")}
      >
        Download index report
      </button>
      {result.status === "available" && (
        <button
          type="button"
          disabled={file.isPending}
          onClick={() => file.mutate("raster")}
        >
          Download float TIFF
        </button>
      )}
      <button
        type="button"
        disabled={save.isPending}
        onClick={() => save.mutate()}
      >
        Save spectral workflow
      </button>
      {file.error && <p role="alert">{file.error.message}</p>}
      {save.error && <p role="alert">{save.error.message}</p>}
    </section>
  );
}

function Pages({
  offset,
  total,
  change,
}: {
  offset: number;
  total: number;
  change: (value: number) => void;
}) {
  if (total <= 25) return null;
  return (
    <div>
      <button disabled={!offset} onClick={() => change(offset - 25)}>
        Previous
      </button>
      <span>
        {offset + 1}–{Math.min(offset + 25, total)} of {total}
      </span>
      <button
        disabled={offset + 25 >= total}
        onClick={() => change(offset + 25)}
      >
        Next
      </button>
    </div>
  );
}

export function MultispectralWorkspace({
  projectId,
  onOpenWorkflow,
}: {
  projectId: string;
  onOpenWorkflow: () => void;
}) {
  const cache = useQueryClient();
  const [acqOffset, setAcqOffset] = useState(0),
    [indexOffset, setIndexOffset] = useState(0);
  const [acqId, setAcqId] = useState(""),
    [indexId, setIndexId] = useState("");
  const captures = useQuery({
    queryKey: ["spectral-acquisitions", projectId, acqOffset],
    queryFn: ({ signal }) =>
      spectralList<Capture>(projectId, "acquisitions", acqOffset, signal),
  });
  const indices = useQuery({
    queryKey: ["spectral-indices", projectId, indexOffset],
    queryFn: ({ signal }) =>
      spectralList<Index>(projectId, "indices", indexOffset, signal),
  });
  const capture =
    captures.data?.items.find((r) => r.id === acqId) ?? captures.data?.items[0];
  const index =
    indices.data?.items.find((r) => r.id === indexId) ?? indices.data?.items[0];
  return (
    <div className="multispectral-workspace">
      <SpectralImport
        projectId={projectId}
        onSaved={(r) => {
          setAcqOffset(0);
          setAcqId(r.id);
          void cache.invalidateQueries({
            queryKey: ["spectral-acquisitions", projectId],
          });
        }}
      />
      {captures.error && <p role="alert">{captures.error.message}</p>}
      {capture && (
        <>
          <label>
            Saved acquisition
            <select
              value={capture.id}
              onChange={(e) => setAcqId(e.target.value)}
            >
              {captures.data?.items.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.snapshot.label} · {r.content_sha256.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          <Pages
            offset={acqOffset}
            total={captures.data?.total ?? 0}
            change={setAcqOffset}
          />
          <SpectralPreview
            key={capture.id}
            record={capture}
            onIndex={(r) => {
              setIndexOffset(0);
              setIndexId(r.id);
              void cache.invalidateQueries({
                queryKey: ["spectral-indices", projectId],
              });
            }}
          />
        </>
      )}
      {indices.error && <p role="alert">{indices.error.message}</p>}
      {index && (
        <>
          <label>
            Saved spectral result
            <select
              value={index.id}
              onChange={(e) => setIndexId(e.target.value)}
            >
              {indices.data?.items.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.snapshot.acquisition.label} · {r.snapshot.result.status} ·{" "}
                  {r.content_sha256.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          <Pages
            offset={indexOffset}
            total={indices.data?.total ?? 0}
            change={setIndexOffset}
          />
          <SavedIndex
            key={index.id}
            record={index}
            onOpenWorkflow={onOpenWorkflow}
          />
        </>
      )}
    </div>
  );
}
