import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { request } from "../../api/client";
import {
  adjustmentFileUrl,
  listAdjustments,
  originalPhotoParameters,
  previewAdjustment,
  reopenAdjustment,
  saveAdjustment,
  type AdjustmentParameters,
  type AdjustmentView,
  type ImageAdjustmentRecord,
} from "./imageAdjustmentApi";
import "./imageAdjustments.css";

const controls = [
  { id: "red_gain_percent", label: "Red gain (%)", min: 50, max: 200 },
  { id: "green_gain_percent", label: "Green gain (%)", min: 50, max: 200 },
  { id: "blue_gain_percent", label: "Blue gain (%)", min: 50, max: 200 },
  { id: "brightness_offset", label: "Brightness offset", min: -64, max: 64 },
  { id: "contrast_percent", label: "Contrast (%)", min: 50, max: 200 },
] as const;

export function ImageAdjustments({
  imageId,
  view,
  onChange,
}: {
  imageId: string;
  view: AdjustmentView | null;
  onChange: (view: AdjustmentView | null) => void;
}) {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [parameters, setParameters] = useState<AdjustmentParameters>(
    view?.recipe?.receipt.parameters ?? originalPhotoParameters,
  );
  const source = useQuery({
    queryKey: ["image-adjustment-source", imageId],
    queryFn: ({ signal }) =>
      request<{ sha256: string; width_px: number; height_px: number }>(
        `/images/${imageId}`,
        { signal },
      ),
    enabled: open,
  });
  const saved = useQuery({
    queryKey: ["image-adjustments", imageId, page],
    queryFn: ({ signal }) => listAdjustments(imageId, page, signal),
    enabled: open,
  });
  const apply = (recipe: ImageAdjustmentRecord, blob: Blob) => {
    setParameters(recipe.receipt.parameters);
    onChange({
      imageId,
      recipe,
      url: URL.createObjectURL(blob),
      visible: true,
    });
  };
  const preview = useMutation({
    mutationFn: () =>
      previewAdjustment(imageId, source.data!.sha256, parameters),
    onSuccess: (blob) =>
      onChange({ imageId, url: URL.createObjectURL(blob), visible: true }),
  });
  const save = useMutation({
    mutationFn: async () => {
      const recipe = await saveAdjustment(
        imageId,
        source.data!.sha256,
        parameters,
      );
      return { recipe, blob: await reopenAdjustment(recipe) };
    },
    onSuccess: ({ recipe, blob }) => {
      apply(recipe, blob);
      setPage(1);
      void client.invalidateQueries({
        queryKey: ["image-adjustments", imageId],
      });
    },
  });
  const reopen = useMutation({
    mutationFn: reopenAdjustment,
    onSuccess: (blob, recipe) => apply(recipe, blob),
  });
  const busy = preview.isPending || save.isPending || reopen.isPending;
  const valid = controls.every(
    ({ id, min, max }) =>
      Number.isInteger(parameters[id]) &&
      parameters[id] >= min &&
      parameters[id] <= max,
  );
  const issue =
    preview.error ?? save.error ?? reopen.error ?? source.error ?? saved.error;

  return (
    <details
      className="annotation-sidebar-section"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>Image adjustments</summary>
      {open && (
        <div
          className="image-adjustment-fields"
          role="group"
          aria-label="Image adjustments"
        >
          <p className="annotation-helper">
            Adjust RGB brightness and color on the original pixel grid. These
            settings describe an appearance change.
          </p>
          {controls.map(({ id, label, min, max }) => (
            <label key={id}>
              {label}
              <input
                type="number"
                min={min}
                max={max}
                step={1}
                disabled={busy}
                value={Number.isNaN(parameters[id]) ? "" : parameters[id]}
                onChange={(event) => {
                  const value = event.target.valueAsNumber;
                  setParameters((before) => ({ ...before, [id]: value }));
                  onChange(null);
                }}
              />
            </label>
          ))}
          <button
            type="button"
            className="secondary"
            disabled={busy || !source.data || !valid}
            onClick={() => {
              save.reset();
              reopen.reset();
              preview.mutate();
            }}
          >
            Preview adjustment
          </button>
          <button
            type="button"
            disabled={busy || !source.data || !valid}
            onClick={() => {
              preview.reset();
              reopen.reset();
              save.mutate();
            }}
          >
            Save adjustment recipe
          </button>
          {view && (
            <button
              type="button"
              className="secondary"
              onClick={() => onChange({ ...view, visible: !view.visible })}
            >
              {view.visible ? "Show original pixels" : "Show adjusted pixels"}
            </button>
          )}
          <p className="annotation-helper" role="status">
            {view?.visible
              ? "Showing adjusted pixels"
              : "Showing original pixels"}
          </p>
          {issue && (
            <p className="form-error" role="alert">
              {issue.message}
            </p>
          )}
          {saved.data && saved.data.total > 0 && (
            <>
              <label>
                Saved adjustment recipes
                <select
                  value={view?.recipe?.id ?? ""}
                  disabled={busy}
                  onChange={(event) => {
                    const latest = saved.data.items.find(
                      (recipe) => recipe.id === event.target.value,
                    );
                    preview.reset();
                    save.reset();
                    if (latest) reopen.mutate(latest);
                    else onChange(null);
                  }}
                >
                  <option value="">Choose a saved recipe</option>
                  {view?.recipe &&
                    !saved.data.items.some(
                      ({ id }) => id === view.recipe?.id,
                    ) && (
                      <option value={view.recipe.id}>
                        {view.recipe.content_sha256.slice(0, 12)}
                      </option>
                    )}
                  {saved.data.items.map((recipe) => (
                    <option key={recipe.id} value={recipe.id}>
                      {recipe.content_sha256.slice(0, 12)}
                    </option>
                  ))}
                </select>
              </label>
              {saved.data.total > saved.data.page_size && (
                <div className="image-adjustment-links">
                  <button
                    type="button"
                    className="secondary"
                    disabled={page === 1}
                    onClick={() => setPage(page - 1)}
                  >
                    Previous recipes
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    disabled={page * saved.data.page_size >= saved.data.total}
                    onClick={() => setPage(page + 1)}
                  >
                    More recipes
                  </button>
                </div>
              )}
            </>
          )}
          {view?.recipe && (
            <>
              <dl className="image-adjustment-digests">
                <div>
                  <dt>Recipe SHA-256</dt>
                  <dd>{view.recipe.content_sha256}</dd>
                </div>
                <div>
                  <dt>Original SHA-256</dt>
                  <dd>{view.recipe.receipt.original_sha256}</dd>
                </div>
                <div>
                  <dt>Adjusted PNG SHA-256</dt>
                  <dd>{view.recipe.receipt.rendition_sha256}</dd>
                </div>
              </dl>
              <div className="image-adjustment-links">
                <a href={adjustmentFileUrl(imageId, view.recipe.id, "export")}>
                  Download recipe JSON
                </a>
                <a
                  href={adjustmentFileUrl(imageId, view.recipe.id, "download")}
                >
                  Download adjusted PNG
                </a>
              </div>
            </>
          )}
        </div>
      )}
    </details>
  );
}
