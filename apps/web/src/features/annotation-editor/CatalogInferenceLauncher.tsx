import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

import { getApiBaseUrl } from "../../runtime";
import "./catalogInference.css";

const supportedCatalogIds = new Set([
  "transformers/florence2/base",
  "transformers/florence2/large",
  "transformers/grounding_dino/tiny",
  "transformers/grounding_dino/base",
  "transformers/owlv2/base",
  "transformers/owlv2/large",
]);

interface CatalogModel {
  catalog_id: string;
  display_name: string;
  provider_id: string;
  installation_state: string;
  installation_reason: string | null;
  recommended_vram: number | null;
}

interface CatalogResponse {
  models: CatalogModel[];
}

interface AnnotationSessionResponse {
  image: { id: string; project_id: string };
}

interface JobResponse {
  id: string;
  status: string;
  error_message: string | null;
  progress_current: number;
  progress_total: number;
  result_json: Record<string, unknown> | null;
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
  if (!match?.[1] || !container) return null;
  return { imageId: decodeURIComponent(match[1]), container };
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
      const payload = (await response.json()) as {
        detail?: string | { message?: string; reason?: string };
      };
      if (typeof payload.detail === "string") message = payload.detail;
      if (payload.detail && typeof payload.detail === "object") {
        message = payload.detail.message ?? payload.detail.reason ?? message;
      }
    } catch {
      // Retain the HTTP fallback.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

function providerLabel(providerId: string): string {
  if (providerId === "grounding_dino") return "Grounding DINO";
  if (providerId === "florence2") return "Florence-2";
  if (providerId === "owlv2") return "OWLv2";
  return providerId;
}

export function CatalogInferenceLauncher() {
  const queryClient = useQueryClient();
  const [target, setTarget] = useState<EditorTarget | null>(null);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [models, setModels] = useState<CatalogModel[]>([]);
  const [catalogId, setCatalogId] = useState("");
  const [prompt, setPrompt] = useState("coral polyp");
  const [confidence, setConfidence] = useState("0.25");
  const [device, setDevice] = useState("auto");
  const [expanded, setExpanded] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const selectedModel = useMemo(
    () => models.find((model) => model.catalog_id === catalogId) ?? null,
    [catalogId, models],
  );

  useEffect(() => {
    const refreshTarget = () => {
      const next = currentEditorTarget();
      setTarget((current) =>
        current?.imageId === next?.imageId && current?.container === next?.container
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
      setProjectId(null);
      setModels([]);
      setCatalogId("");
      setExpanded(false);
      setJobId(null);
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
        const catalog = await jsonRequest<CatalogResponse>(
          `/projects/${encodeURIComponent(nextProjectId)}/model-catalog?workflow=prompt_assist`,
          { signal: controller.signal },
        );
        const ready = catalog.models.filter(
          (model) =>
            supportedCatalogIds.has(model.catalog_id) &&
            ["Ready", "Available"].includes(model.installation_state),
        );
        setProjectId(nextProjectId);
        setModels(ready);
        setCatalogId((current) =>
          ready.some((model) => model.catalog_id === current)
            ? current
            : (ready[0]?.catalog_id ?? ""),
        );
        setStatus(
          ready.length > 0
            ? null
            : "No verified text-prompt models are ready. Repair or rebuild the desktop model pack.",
        );
      } catch (error) {
        if (!controller.signal.aborted) {
          setStatus(
            error instanceof Error
              ? error.message
              : "Text-prompt models could not be loaded.",
          );
        }
      }
    };
    void load();
    return () => controller.abort();
  }, [target]);

  useEffect(() => {
    if (!jobId || !target) return;
    let stopped = false;
    const poll = async () => {
      try {
        const job = await jsonRequest<JobResponse>(`/jobs/${encodeURIComponent(jobId)}`);
        if (stopped) return;
        if (job.status === "succeeded") {
          const proposalCount = Number(job.result_json?.proposal_count ?? 0);
          setStatus(
            `Detection complete: ${proposalCount} proposal${proposalCount === 1 ? "" : "s"} added for review.`,
          );
          setJobId(null);
          await Promise.all([
            queryClient.invalidateQueries({
              queryKey: ["predictions", target.imageId],
            }),
            queryClient.invalidateQueries({
              queryKey: ["models", projectId, "prediction"],
            }),
          ]);
          return;
        }
        if (["failed", "cancelled"].includes(job.status)) {
          setStatus(job.error_message ?? `Detection job ${job.status}.`);
          setJobId(null);
          return;
        }
        setStatus(
          `Running detection ${job.progress_current}/${Math.max(job.progress_total, 1)}...`,
        );
      } catch (error) {
        if (!stopped) {
          setStatus(error instanceof Error ? error.message : "Could not read detection status.");
          setJobId(null);
        }
      }
    };
    void poll();
    const interval = window.setInterval(() => void poll(), 1000);
    return () => {
      stopped = true;
      window.clearInterval(interval);
    };
  }, [jobId, projectId, queryClient, target]);

  const launch = async () => {
    if (!target || !projectId || !catalogId) return;
    const normalizedPrompt = prompt.trim();
    if (!normalizedPrompt) {
      setStatus("Enter one or more object names before running detection.");
      return;
    }
    setLaunching(true);
    setStatus(null);
    try {
      const job = await jsonRequest<JobResponse>(
        `/projects/${encodeURIComponent(projectId)}/catalog-inference-jobs`,
        {
          method: "POST",
          body: JSON.stringify({
            catalog_id: catalogId,
            image_ids: [target.imageId],
            text_prompt: normalizedPrompt,
            confidence_threshold: Number(confidence),
            device,
          }),
        },
      );
      setJobId(job.id);
      setStatus(`${selectedModel?.display_name ?? "Text-prompt detection"} queued.`);
    } catch (error) {
      setStatus(
        error instanceof Error
          ? error.message
          : "Text-prompt detection could not be queued.",
      );
    } finally {
      setLaunching(false);
    }
  };

  if (!target) return null;

  return createPortal(
    <div className="catalog-inference-launcher">
      <button
        type="button"
        className={expanded ? "active" : "secondary"}
        onClick={() => setExpanded((current) => !current)}
      >
        Text detect
      </button>
      {expanded && (
        <div className="catalog-inference-popover" role="dialog" aria-label="Text-prompt detection">
          <strong>Text-prompt detection</strong>
          <label>
            Model
            <select
              aria-label="Text detection model"
              value={catalogId}
              onChange={(event) => setCatalogId(event.target.value)}
              disabled={models.length === 0 || launching || Boolean(jobId)}
            >
              {models.length > 0 ? (
                models.map((model) => (
                  <option key={model.catalog_id} value={model.catalog_id}>
                    {`${providerLabel(model.provider_id)} · ${model.display_name}`}
                  </option>
                ))
              ) : (
                <option value="">No verified models ready</option>
              )}
            </select>
          </label>
          <label>
            Objects to find
            <textarea
              aria-label="Objects to find"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="coral polyp, fish, branching coral"
              rows={2}
              maxLength={2000}
              disabled={launching || Boolean(jobId)}
            />
          </label>
          <div className="catalog-inference-row">
            <label>
              Confidence
              <input
                aria-label="Text detection confidence"
                type="number"
                min="0"
                max="1"
                step="0.05"
                value={confidence}
                onChange={(event) => setConfidence(event.target.value)}
                disabled={launching || Boolean(jobId)}
              />
            </label>
            <label>
              Device
              <select
                aria-label="Text detection device"
                value={device}
                onChange={(event) => setDevice(event.target.value)}
                disabled={launching || Boolean(jobId)}
              >
                <option value="auto">Auto</option>
                <option value="cuda">CUDA</option>
                <option value="cpu">CPU</option>
              </select>
            </label>
          </div>
          <button
            type="button"
            disabled={!catalogId || !prompt.trim() || launching || Boolean(jobId)}
            onClick={() => void launch()}
          >
            {launching ? "Queueing..." : jobId ? "Detection running..." : "Find objects"}
          </button>
          {selectedModel?.recommended_vram != null && (
            <small>Recommended VRAM: {selectedModel.recommended_vram} GB</small>
          )}
          {status && <span className="annotation-helper">{status}</span>}
        </div>
      )}
    </div>,
    target.container,
  );
}
