import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import { getApiBaseUrl } from "../../runtime";
import "./segmentationInference.css";

interface ModelRegistration {
  id: string;
  display_name: string;
  task: string;
  purpose: string;
}

interface AnnotationSessionResponse {
  image: { id: string; project_id: string };
}

interface EditorTarget {
  imageId: string;
  container: HTMLElement;
}

function currentEditorTarget(): EditorTarget | null {
  const container = document.querySelector<HTMLElement>(
    ".annotation-editor-actions[data-segmentation-image-id]",
  );
  const imageId = container?.dataset.segmentationImageId;
  return container && imageId ? { imageId, container } : null;
}

async function jsonRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let message = `Request failed with HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) message = payload.detail;
    } catch {
      // Retain the HTTP fallback.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

function modelKind(model: ModelRegistration): string {
  return model.task === "semantic_segment" ? "Semantic" : "Instance";
}

export function SegmentationInferenceLauncher() {
  const [target, setTarget] = useState<EditorTarget | null>(null);
  const [loadedFor, setLoadedFor] = useState<{
    imageId: string;
    projectId: string;
  } | null>(null);
  const [models, setModels] = useState<ModelRegistration[]>([]);
  const [modelId, setModelId] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [launching, setLaunching] = useState(false);
  const projectId =
    target && loadedFor?.imageId === target.imageId
      ? loadedFor.projectId
      : null;

  const selectedModel = useMemo(
    () => models.find((model) => model.id === modelId) ?? null,
    [modelId, models],
  );

  useEffect(() => {
    const refreshTarget = () => {
      const next = currentEditorTarget();
      setTarget((current) =>
        current?.imageId === next?.imageId &&
        current?.container === next?.container
          ? current
          : next,
      );
    };
    refreshTarget();
    const observer = new MutationObserver(refreshTarget);
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
    });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!target) {
      setLoadedFor(null);
      setModels([]);
      setModelId("");
      return;
    }
    const controller = new AbortController();
    const load = async () => {
      try {
        const session = await jsonRequest<AnnotationSessionResponse>(
          `/images/${encodeURIComponent(target.imageId)}/annotations`,
          { signal: controller.signal },
        );
        const nextProjectId = session.image.project_id;
        const responseModels = await jsonRequest<ModelRegistration[]>(
          `/projects/${encodeURIComponent(nextProjectId)}/models`,
          { signal: controller.signal },
        );
        const nextModels = responseModels.filter(
          (model) =>
            (model.purpose === "segmenter" && model.task === "segment") ||
            (model.purpose === "semantic_segmenter" &&
              model.task === "semantic_segment"),
        );
        if (controller.signal.aborted) return;
        setLoadedFor({ imageId: target.imageId, projectId: nextProjectId });
        setModels(nextModels);
        setModelId((current) =>
          nextModels.some((model) => model.id === current)
            ? current
            : (nextModels[0]?.id ?? ""),
        );
        setStatus(null);
      } catch (error) {
        if (!controller.signal.aborted) {
          setStatus(
            error instanceof Error
              ? error.message
              : "Segmentation models could not be loaded.",
          );
        }
      }
    };
    void load();
    return () => controller.abort();
  }, [target]);

  const launch = async () => {
    if (!target || !projectId || !modelId) return;
    const stillActive = () =>
      target.container.isConnected &&
      target.container.dataset.segmentationImageId === target.imageId;
    if (!stillActive()) return;
    setLaunching(true);
    setStatus(null);
    try {
      await jsonRequest(
        `/projects/${encodeURIComponent(projectId)}/inference-jobs`,
        {
          method: "POST",
          body: JSON.stringify({
            model_id: modelId,
            image_ids: [target.imageId],
            device: "auto",
          }),
        },
      );
      const kind = selectedModel ? modelKind(selectedModel).toLowerCase() : "";
      if (stillActive()) {
        setStatus(
          `${kind ? `${kind} ` : ""}segmentation queued; mask proposals will appear on this image.`,
        );
      }
    } catch (error) {
      if (stillActive()) {
        setStatus(
          error instanceof Error
            ? error.message
            : "Segmentation inference could not be queued.",
        );
      }
    } finally {
      setLaunching(false);
    }
  };

  if (!target) return null;

  return createPortal(
    <div className="annotation-editor-segmentation-launcher">
      <select
        aria-label="Segmentation model"
        value={modelId}
        onChange={(event) => setModelId(event.target.value)}
        disabled={!projectId || models.length === 0 || launching}
        title="Select a trained instance or semantic segmentation model"
      >
        {models.length > 0 ? (
          models.map((model) => (
            <option key={model.id} value={model.id}>
              {`${modelKind(model)} · ${model.display_name}`}
            </option>
          ))
        ) : (
          <option value="">No segmenters registered</option>
        )}
      </select>
      <button
        type="button"
        className="secondary"
        disabled={!projectId || !modelId || launching}
        onClick={() => void launch()}
        title={status ?? "Run segmentation on the open image"}
      >
        {launching ? "Queueing segment..." : "Run segmentation"}
      </button>
      {status && <span className="annotation-helper">{status}</span>}
    </div>,
    target.container,
  );
}
