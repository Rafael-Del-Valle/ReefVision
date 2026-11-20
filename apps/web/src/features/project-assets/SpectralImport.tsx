import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  importBands,
  saveAcquisition,
  type BandDraft,
  type Capture,
  type Receipt,
} from "./multispectralApi";

export function SpectralImport({
  projectId,
  onSaved,
}: {
  projectId: string;
  onSaved: (value: Receipt<Capture>) => void;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [bands, setBands] = useState<BandDraft[]>([]);
  const [label, setLabel] = useState(""),
    [sensor, setSensor] = useState("");
  const [aligned, setAligned] = useState(false),
    [grid, setGrid] = useState(""),
    [reviewer, setReviewer] = useState("");
  const [evidence, setEvidence] = useState(""),
    [residual, setResidual] = useState("");
  const originals = useMutation({
    mutationFn: () => importBands(projectId, files),
    onSuccess: setBands,
  });
  const save = useMutation({
    mutationFn: () =>
      saveAcquisition(
        projectId,
        label,
        sensor,
        aligned
          ? { grid, reviewer, evidence, maximum_residual_px: Number(residual) }
          : null,
        bands,
      ),
    onSuccess: onSaved,
  });
  function patch(position: number, update: Partial<BandDraft>) {
    setBands((previous) =>
      previous.map((band, i) =>
        i === position ? { ...band, ...update } : band,
      ),
    );
  }
  function register(e: FormEvent) {
    e.preventDefault();
    save.mutate();
  }
  return (
    <section className="panel" aria-label="Import multispectral image">
      <h3>Import multispectral image</h3>
      <label>
        Original band files (2–8 grayscale PNG or TIFF images)
        <input
          type="file"
          multiple
          accept=".png,.tif,.tiff"
          onChange={(e) => {
            setFiles(Array.from(e.target.files ?? []));
            setBands([]);
          }}
        />
      </label>
      <button
        type="button"
        disabled={files.length < 2 || files.length > 8 || originals.isPending}
        onClick={() => originals.mutate()}
      >
        Import band originals
      </button>
      {originals.error && <p role="alert">{originals.error.message}</p>}
      {bands.length > 0 && (
        <form onSubmit={register}>
          <label>
            Acquisition name
            <input
              required
              maxLength={240}
              value={label}
              onChange={(e) => setLabel(e.target.value)}
            />
          </label>
          <label>
            Sensor
            <input
              required
              maxLength={240}
              value={sensor}
              onChange={(e) => setSensor(e.target.value)}
            />
          </label>
          {bands.map((b, i) => (
            <fieldset key={b.image.id + "-" + i}>
              <legend>{b.image.original_filename}</legend>
              <p>
                {b.image.width_px} × {b.image.height_px} source pixels ·{" "}
                <code>{b.image.sha256.slice(0, 12)}</code>
              </p>
              <label>
                Band name
                <input
                  required
                  value={b.name}
                  onChange={(e) => patch(i, { name: e.target.value })}
                />
              </label>
              <label>
                Center wavelength (nm)
                <input
                  required
                  type="number"
                  min="0.001"
                  max="3000"
                  step="any"
                  value={b.wavelength}
                  onChange={(e) => patch(i, { wavelength: e.target.value })}
                />
              </label>
              {i > 0 && (
                <>
                  <label>
                    Column offset (pixels)
                    <input
                      required
                      type="number"
                      step="1"
                      value={b.dx}
                      onChange={(e) => patch(i, { dx: e.target.value })}
                    />
                  </label>
                  <label>
                    Row offset (pixels)
                    <input
                      required
                      type="number"
                      step="1"
                      value={b.dy}
                      onChange={(e) => patch(i, { dy: e.target.value })}
                    />
                  </label>
                </>
              )}
              <label>
                NoData digital number
                <input
                  type="number"
                  min="0"
                  max="65535"
                  step="1"
                  value={b.nodata}
                  onChange={(e) => patch(i, { nodata: e.target.value })}
                />
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={b.calibrated}
                  onChange={(e) => patch(i, { calibrated: e.target.checked })}
                />
                Supply reflectance calibration
              </label>
              {b.calibrated && (
                <>
                  <label>
                    Dark reference (DN)
                    <input
                      required
                      type="number"
                      min="0"
                      max="65535"
                      step="any"
                      value={b.dark}
                      onChange={(e) => patch(i, { dark: e.target.value })}
                    />
                  </label>
                  <label>
                    White reference (DN)
                    <input
                      required
                      type="number"
                      min="0"
                      max="65535"
                      step="any"
                      value={b.white}
                      onChange={(e) => patch(i, { white: e.target.value })}
                    />
                  </label>
                  <label>
                    Panel reflectance (fraction)
                    <input
                      required
                      type="number"
                      min="0.000001"
                      max="1"
                      step="any"
                      value={b.reflectance}
                      onChange={(e) =>
                        patch(i, { reflectance: e.target.value })
                      }
                    />
                  </label>
                  <label>
                    Calibration reference
                    <input
                      required
                      value={b.reference}
                      onChange={(e) => patch(i, { reference: e.target.value })}
                    />
                  </label>
                </>
              )}
            </fieldset>
          ))}
          <label>
            <input
              type="checkbox"
              checked={aligned}
              onChange={(e) => setAligned(e.target.checked)}
            />
            Record reviewed grid alignment
          </label>
          {aligned && (
            <fieldset>
              <legend>Alignment to the first band's pixel grid</legend>
              <label>
                Reference grid
                <input
                  required
                  value={grid}
                  onChange={(e) => setGrid(e.target.value)}
                />
              </label>
              <label>
                Alignment reviewer
                <input
                  required
                  value={reviewer}
                  onChange={(e) => setReviewer(e.target.value)}
                />
              </label>
              <label>
                Alignment evidence
                <input
                  required
                  value={evidence}
                  onChange={(e) => setEvidence(e.target.value)}
                />
              </label>
              <label>
                Maximum residual (pixels)
                <input
                  required
                  type="number"
                  min="0"
                  step="any"
                  value={residual}
                  onChange={(e) => setResidual(e.target.value)}
                />
              </label>
            </fieldset>
          )}
          <button disabled={save.isPending}>Save acquisition</button>
          {save.error && <p role="alert">{save.error.message}</p>}
        </form>
      )}
    </section>
  );
}
