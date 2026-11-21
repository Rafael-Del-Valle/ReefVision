import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";

import { getImages } from "../../api/client";
import {
  completePluginMeasurementPins,
  listPlugins,
  pluginAvailability,
  pluginCatalogKey,
  pluginLabel,
  pluginPageSize,
  readPluginSourceImage,
  type PluginMeasurementInput,
} from "./pluginApi";

interface Props {
  projectId: string;
  pins: Partial<PluginMeasurementInput>;
  onChange: (value: Partial<PluginMeasurementInput>) => void;
  actions?: (input: PluginMeasurementInput | null) => ReactNode;
}

export function PluginMeasurementControls({
  projectId,
  pins,
  onChange,
  actions,
}: Props) {
  const [pluginOffset, setPluginOffset] = useState(0);
  const [search, setSearch] = useState("");
  const [imagePage, setImagePage] = useState(1);
  const [selectedImageForPinning, setSelectedImageForPinning] = useState("");
  const pluginId = pins.plugin_record_id ?? "";
  const imageId = pins.image_id ?? "";

  const catalog = useQuery({
    queryKey: [...pluginCatalogKey, pluginOffset],
    queryFn: ({ signal }) => listPlugins(pluginOffset, signal),
  });
  const images = useQuery({
    queryKey: ["plugin-source-images", projectId, search, imagePage],
    queryFn: ({ signal }) =>
      getImages(
        projectId,
        { filename: search.trim(), page: imagePage, pageSize: pluginPageSize },
        signal,
      ),
  });
  const image = useQuery({
    queryKey: ["plugin-source-image", projectId, imageId],
    queryFn: ({ signal }) => readPluginSourceImage(imageId, signal),
    enabled: Boolean(imageId),
  });

  const plugins = catalog.data?.items ?? [];
  const listedImages = images.data?.items ?? [];
  const selected = plugins.find((item) => item.id === pluginId);
  const projectImage =
    image.data?.project_id === projectId && image.data.id === imageId
      ? image.data
      : undefined;

  useEffect(() => {
    if (
      projectImage &&
      selectedImageForPinning === projectImage.id &&
      !pins.image_sha256
    ) {
      onChange({ ...pins, image_sha256: projectImage.sha256 });
      setSelectedImageForPinning("");
    }
  }, [onChange, pins, projectImage, selectedImageForPinning]);

  const ready =
    selected?.enabled &&
    selected.available &&
    selected.package_sha256 === pins.package_sha256 &&
    projectImage?.sha256 === pins.image_sha256 &&
    !image.error &&
    !catalog.error &&
    completePluginMeasurementPins(pins)
      ? pins
      : null;

  return (
    <fieldset>
      <legend>Image measurement inputs</legend>
      <label>
        Plugin version
        <select
          value={pluginId}
          onChange={(event) => {
            const chosen = plugins.find(
              (item) => item.id === event.target.value,
            );
            onChange({
              ...pins,
              plugin_record_id: chosen?.id ?? "",
              package_sha256: chosen?.package_sha256 ?? "",
            });
          }}
        >
          <option value="">Choose a plugin version</option>
          {pluginId && !selected && (
            <option value={pluginId}>
              Pinned plugin ·{" "}
              {pins.package_sha256?.slice(0, 12) || "digest unavailable"}
            </option>
          )}
          {plugins.map((item) => (
            <option
              key={item.id}
              value={item.id}
              disabled={!item.enabled || !item.available}
            >
              {pluginLabel(item)} · {pluginAvailability(item)}
            </option>
          ))}
        </select>
      </label>
      {catalog.isPending && <p role="status">Loading plugin versions…</p>}
      {catalog.error && <p role="alert">{catalog.error.message}</p>}
      {Boolean(catalog.data && catalog.data.total > pluginPageSize) && (
        <div className="button-row" aria-label="Measurement plugin pages">
          <button
            type="button"
            className="secondary"
            disabled={pluginOffset === 0}
            onClick={() => setPluginOffset(pluginOffset - pluginPageSize)}
          >
            Previous plugin versions
          </button>
          <button
            type="button"
            className="secondary"
            disabled={
              pluginOffset + pluginPageSize >= (catalog.data?.total ?? 0)
            }
            onClick={() => setPluginOffset(pluginOffset + pluginPageSize)}
          >
            Next plugin versions
          </button>
        </div>
      )}
      {pins.package_sha256 && (
        <p>
          Plugin package SHA-256 <code>{pins.package_sha256}</code>
        </p>
      )}
      {selected && selected.package_sha256 !== pins.package_sha256 && (
        <p role="alert">
          The selected plugin version changed. Select the intended package
          again.
        </p>
      )}
      {selected && (!selected.enabled || !selected.available) && (
        <p role="status">
          {selected.reason ||
            "Enable this plugin version in Plugins and providers before running it."}
        </p>
      )}

      <label>
        Find source images
        <input
          type="search"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setImagePage(1);
          }}
        />
      </label>
      <label>
        Source image
        <select
          value={imageId}
          onChange={(event) => {
            setSelectedImageForPinning(event.target.value);
            onChange({
              ...pins,
              image_id: event.target.value,
              image_sha256: "",
            });
          }}
        >
          <option value="">Choose an original image</option>
          {imageId && !listedImages.some((item) => item.id === imageId) && (
            <option value={imageId}>
              {projectImage?.original_filename ?? "Pinned source image"}
            </option>
          )}
          {listedImages.map((item) => (
            <option key={item.id} value={item.id}>
              {item.original_filename}
            </option>
          ))}
        </select>
      </label>
      {images.isPending && <p role="status">Loading project images…</p>}
      {images.error && <p role="alert">{images.error.message}</p>}
      {Boolean(images.data && images.data.pages > 1) && (
        <div className="button-row" aria-label="Source image pages">
          <button
            type="button"
            className="secondary"
            disabled={imagePage === 1}
            onClick={() => setImagePage(imagePage - 1)}
          >
            Previous images
          </button>
          <button
            type="button"
            className="secondary"
            disabled={imagePage >= (images.data?.pages ?? 0)}
            onClick={() => setImagePage(imagePage + 1)}
          >
            Next images
          </button>
        </div>
      )}
      {imageId && image.isPending && (
        <p role="status">Checking the original image digest…</p>
      )}
      {imageId && image.error && (
        <p role="alert">
          Could not verify the original image. Choose an image from this
          project.
        </p>
      )}
      {image.data && !projectImage && (
        <p role="alert">The selected image does not belong to this project.</p>
      )}
      {pins.image_sha256 && (
        <p>
          Original image SHA-256 <code>{pins.image_sha256}</code>
        </p>
      )}
      {projectImage &&
        pins.image_sha256 &&
        projectImage.sha256 !== pins.image_sha256 && (
          <p role="alert">
            The original image digest differs from the pinned value. Select the
            intended image again.
          </p>
        )}
      {actions?.(ready)}
    </fieldset>
  );
}
