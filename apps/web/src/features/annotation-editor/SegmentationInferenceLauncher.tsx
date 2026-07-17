import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { getApiBaseUrl } from "../../runtime";

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
  const canvas = document.querySelector<SVGSVGElement>("svg.annotation-canvas");
  const sourceImage = canvas?.querySelector<SVGImageElement>(":scope > g > image");
  const href =
    sourceImage?.getAttribute("href") ??
    sourceImage?.getAttribute("xlink:href") ??
    "";
  const match = href.match(/\/images\/([^/]+)\/(?:content|thumbnail)(?:\?|$)/);
  const container = document.querySelector<HTMLElement>(
    ".annotation-editor-topbar .annotation-editor-actions",
  );
  if (!match?.[1] || !container) {
    return null;
  }
  return { imageId: decodeURIComponent(match[1]), container };
}

async function jsonRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
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

export function SegmentationInferenceLauncher() {
  const [target, setTarget] = useState<EditorTarget | null>(null);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [models, setModels] = useState<ModelRegistration[]>([]);
  const [modelId, setModelId] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [launching, setLaunching] = useState(false);

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
    observer.observe(document.body, { childList: true, subtree: true, attributes: true });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!target) {
      setProjectId(null);
      setModels([]);
      setModelId("");
      return;
    }
    const controller = new AbortController();
    const load = async () => {
      try {
        const session = await jsonRequest<AnnotationSessionResponse>(
          `/images/${encodeURIComponent(target.imageId)}/annotation-session`,
          { signal: controller.signal },
        );
        const nextProjectId = session.image.project_id;
        const nextModels = await jsonRequest<ModelRegistration[]>(
          `/projects/${encodeURIComponent(nextProjectId)}/models?purpose=segmenter`,
          { signal: controller.signal },
        );
        setProjectId(nextProjectId);
        setModels(
          nextModels.filter(
            (model) => model.purpose === "segmenter" && model.task === "segment",
          ),
        );
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
      setStatus("Segmentation queued; mask proposals will appear on this image.");
    } catch (error) {
      setStatus(
        error instanceof Error
          ? error.message
          : "Segmentation inference could not be queued.",
      );
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
        disabled={models.length === 0 || launching}
        title="Select a trained segmentation model"
      >
        {models.length > 0 ? (
          models.map((model) => (
            <option key={model.id} value={model.id}>
              {model.display_name}
            </option>
          ))
        ) : (
          <option value="">No segmenters registered</option>
        )}
      </select>
      <button
        type="button"
        className="secondary"
        disabled={!modelId || launching}
        onClick={() => void launch()}
        title={status ?? "Run instance segmentation on the open image"}
      >
        {launching ? "Queueing segment..." : "Run segmentation"}
      </button>
      {status && <span className="annotation-helper">{status}</span>}
    </div>,
    target.container,
  );
}
