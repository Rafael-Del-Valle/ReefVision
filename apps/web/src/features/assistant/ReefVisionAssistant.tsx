import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { getProjectModelCatalog, type Project } from "../../api/client";
import {
  executeAdvancedProvider,
  listAdvancedProviderImages,
} from "../advanced-providers/advancedProvidersApi";

type ReefVisionView =
  | "gallery"
  | "versions"
  | "models"
  | "training"
  | "classification"
  | "video"
  | "active_learning"
  | "classes"
  | "quality_control"
  | "review_queue"
  | "advanced_providers"
  | "workflows";

interface ReefVisionAssistantProps {
  project: Project;
  activeView: string;
  onNavigate: (view: ReefVisionView) => void;
}

interface AssistantMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  navigateTo?: ReefVisionView;
  navigateLabel?: string;
}

interface Guidance {
  text: string;
  navigateTo?: ReefVisionView;
  navigateLabel?: string;
}

const SMOLVLM_CATALOG_ID = "transformers/smolvlm/256m-instruct";

const VIEW_LABELS: Record<string, string> = {
  gallery: "Images & annotation",
  versions: "Dataset versions",
  models: "Models & AI",
  training: "Training",
  classification: "Classification",
  video: "Video & tracking",
  active_learning: "Active learning",
  classes: "Classes",
  quality_control: "Quality Control",
  review_queue: "Review Queue",
  advanced_providers: "Advanced Providers",
  workflows: "Workflow Builder",
};

function messageId(): string {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function guidanceFor(question: string, activeView: string): Guidance {
  const normalized = question.trim().toLowerCase();

  if (
    /(shortcut|keybind|hotkey|keyboard|undo|redo|previous image|next image)/.test(
      normalized,
    )
  ) {
    return {
      text:
        "Annotation keyboard shortcuts are grounded in ReefVision's canonical editor: " +
        "1–9 assign the selected annotation to the corresponding active class; " +
        "Ctrl/Cmd+Z undoes; Ctrl/Cmd+Shift+Z or Ctrl/Cmd+Y redoes; " +
        "B selects Box, V selects Select, P selects Pan, F fits the image, " +
        "H hides/shows annotations, A moves to the previous image, D moves to " +
        "the next image, J/K move through model proposals, and Delete/Backspace " +
        "deletes the current selection. Shortcuts are ignored while typing in " +
        "text fields so they do not interfere with data entry.",
      navigateTo: "gallery",
      navigateLabel: "Go to Images & annotation",
    };
  }

  if (
    /(calibrat|scale bar|ruler|aruco|charuco|measurement|tle|surface area|density)/.test(
      normalized,
    )
  ) {
    return {
      text:
        "Calibration and scientific measurements live with the image annotation workflow. " +
        "Open the image, switch to the mask workspace, select a mask, then use Scale Assistant " +
        "for ruler, scale-bar, ArUco/ChArUco, or reviewed OCR evidence. ReefVision does not " +
        "apply automatic calibration evidence until you review and accept it.",
      navigateTo: "gallery",
      navigateLabel: "Go to Images & annotation",
    };
  }

  if (
    /(sam ?2|grounding|smolvlm|advanced provider|open vocabulary)/.test(
      normalized,
    )
  ) {
    return {
      text:
        "The Advanced Providers workspace runs SAM 2, Grounding DINO, and SmolVLM through " +
        "Model Hub-managed checkpoints. SAM 2 and Grounding DINO outputs remain pending " +
        "review proposals; they do not become verified annotations automatically.",
      navigateTo: "advanced_providers",
      navigateLabel: "Go to Advanced Providers",
    };
  }

  if (
    /(model hub|install model|download model|verify model|models? & ai)/.test(
      normalized,
    )
  ) {
    return {
      text:
        "Use Models & AI to train from architectures or register compatible local models. " +
        "Advanced Providers reuses those Model Hub checkpoints instead of maintaining a second copy.",
      navigateTo: "models",
      navigateLabel: "Go to Models & AI",
    };
  }

  if (/(train|training|nn.?u.?net|yolo)/.test(normalized)) {
    return {
      text:
        "Training is managed from the Training workspace. Detection and instance-segmentation " +
        "models can use the Ultralytics workflow; semantic segmentation uses the nnU-Net path " +
        "when its optional local provider is available.",
      navigateTo: "training",
      navigateLabel: "Go to Training",
    };
  }

  if (
    /(review queue|review prediction|accept prediction|reject prediction)/.test(
      normalized,
    )
  ) {
    return {
      text:
        "Use Review Queue for prioritized human review. Predictions remain proposals until " +
        "a researcher accepts or rejects them.",
      navigateTo: "review_queue",
      navigateLabel: "Go to Review Queue",
    };
  }

  if (/(quality|qc|quality control)/.test(normalized)) {
    return {
      text:
        "Quality Control summarizes reproducible diagnostic findings and can route you back " +
        "to the affected image or proposal without silently modifying research data.",
      navigateTo: "quality_control",
      navigateLabel: "Go to Quality Control",
    };
  }

  if (/(workflow|node|pipeline|fusion)/.test(normalized)) {
    return {
      text:
        "Workflow Builder connects typed ReefVision nodes into reproducible pipelines. " +
        "Human-review gates remain explicit boundaries where model output requires researcher approval.",
      navigateTo: "workflows",
      navigateLabel: "Go to Workflow Builder",
    };
  }

  if (/(active learning|uncertain|acquisition)/.test(normalized)) {
    return {
      text:
        "Active Learning is where ReefVision prioritizes informative examples for another " +
        "review/training round while preserving dataset and selection provenance.",
      navigateTo: "active_learning",
      navigateLabel: "Go to Active learning",
    };
  }

  if (/(video|track|tracking|fish)/.test(normalized)) {
    return {
      text: "Video & tracking contains import, tracking, review, occupancy, movement, and science-report workflows.",
      navigateTo: "video",
      navigateLabel: "Go to Video & tracking",
    };
  }

  if (/(class|label|taxonomy)/.test(normalized)) {
    return {
      text:
        "Use Classes to manage project labels, scientific names, display colors, activity, " +
        "and reassignment. Historical dataset/model provenance remains preserved.",
      navigateTo: "classes",
      navigateLabel: "Go to Classes",
    };
  }

  if (/(classif|image label)/.test(normalized)) {
    return {
      text:
        "Classification manages image-level labels and classification datasets separately " +
        "from object detection and segmentation annotations.",
      navigateTo: "classification",
      navigateLabel: "Go to Classification",
    };
  }

  if (/(dataset|version|split|export)/.test(normalized)) {
    return {
      text:
        "Dataset Versions creates immutable research snapshots with splits, class maps, " +
        "measurement metadata, comparisons, and export lineage.",
      navigateTo: "versions",
      navigateLabel: "Go to Dataset versions",
    };
  }

  return {
    text:
      `You are currently in ${VIEW_LABELS[activeView] ?? activeView}. ` +
      "I can point you to ReefVision tools and explain the current workflow. " +
      "For image interpretation, select an image below and explicitly enable SmolVLM image analysis.",
  };
}

function loadHistory(projectId: string): AssistantMessage[] {
  try {
    const raw = window.localStorage.getItem(
      `reefvision.assistant.${projectId}`,
    );
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as AssistantMessage[]) : [];
  } catch {
    return [];
  }
}

export function ReefVisionAssistant({
  project,
  activeView,
  onNavigate,
}: ReefVisionAssistantProps) {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [selectedImageId, setSelectedImageId] = useState("");
  const [useImageModel, setUseImageModel] = useState(false);
  const [messages, setMessages] = useState<AssistantMessage[]>(() =>
    loadHistory(project.id),
  );

  useEffect(() => {
    setMessages(loadHistory(project.id));
    setSelectedImageId("");
    setUseImageModel(false);
  }, [project.id]);

  useEffect(() => {
    // Assistant chat history is an optional UI preference. WebView2 may deny
    // localStorage access entirely; never let that prevent opening a project.
    try {
      window.localStorage.setItem(
        `reefvision.assistant.${project.id}`,
        JSON.stringify(messages.slice(-40)),
      );
    } catch {
      // Keep the current in-memory conversation without persisted history.
    }
  }, [messages, project.id]);

  const imagesQuery = useQuery({
    queryKey: ["reefvision-assistant-images", project.id],
    queryFn: ({ signal }) => listAdvancedProviderImages(project.id, signal),
    enabled: open,
  });

  const modelCatalogQuery = useQuery({
    queryKey: ["reefvision-assistant-model-catalog", project.id],
    queryFn: ({ signal }) =>
      getProjectModelCatalog(
        project.id,
        { workflow: "model_hub", includeUnavailable: true },
        signal,
      ),
    enabled: open,
    staleTime: 30_000,
  });

  const smolvlm = useMemo(
    () =>
      modelCatalogQuery.data?.models.find(
        (model) => model.catalog_id === SMOLVLM_CATALOG_ID,
      ),
    [modelCatalogQuery.data?.models],
  );
  const smolvlmReady = smolvlm?.installation_state === "Ready";

  useEffect(() => {
    if (!selectedImageId && imagesQuery.data?.[0]) {
      setSelectedImageId(imagesQuery.data[0].id);
    }
  }, [imagesQuery.data, selectedImageId]);

  const imageMutation = useMutation({
    mutationFn: async (userQuestion: string) => {
      if (!selectedImageId) {
        throw new Error(
          "Choose an image before asking SmolVLM about image content.",
        );
      }
      const contextPrompt = [
        "You are the ReefVision research assistant.",
        `Current project: ${project.name}.`,
        `Current ReefVision workspace: ${VIEW_LABELS[activeView] ?? activeView}.`,
        "Answer only as advisory guidance.",
        "Do not claim that a model observation is a verified scientific annotation, measurement, or conclusion.",
        "Do not instruct ReefVision to silently edit labels, annotations, calibration, or measurements.",
        `Researcher question: ${userQuestion}`,
      ].join("\n");
      return executeAdvancedProvider(project.id, "smolvlm", {
        task: "visual_question",
        device: "auto",
        allow_model_download: false,
        prompt_fields: {
          image_id: selectedImageId,
          prompt: contextPrompt,
          max_new_tokens: 192,
        },
      });
    },
  });

  async function submitQuestion() {
    const trimmed = question.trim();
    if (!trimmed) return;

    setMessages((current) => [
      ...current,
      { id: messageId(), role: "user", text: trimmed },
    ]);
    setQuestion("");

    if (useImageModel) {
      try {
        const response = await imageMutation.mutateAsync(trimmed);
        const text =
          typeof response.result.text === "string"
            ? response.result.text
            : "SmolVLM returned no readable text.";
        setMessages((current) => [
          ...current,
          {
            id: messageId(),
            role: "assistant",
            text: `${text}\n\nAdvisory only: image-model output is not a verified ReefVision annotation or scientific conclusion.`,
          },
        ]);
      } catch (error) {
        setMessages((current) => [
          ...current,
          {
            id: messageId(),
            role: "assistant",
            text:
              error instanceof Error
                ? error.message
                : "SmolVLM image analysis failed.",
          },
        ]);
      }
      return;
    }

    const guidance = guidanceFor(trimmed, activeView);
    setMessages((current) => [
      ...current,
      {
        id: messageId(),
        role: "assistant",
        text: guidance.text,
        navigateTo: guidance.navigateTo,
        navigateLabel: guidance.navigateLabel,
      },
    ]);
  }

  return (
    <div
      data-testid="reefvision-assistant"
      data-open={open ? "true" : "false"}
      className={`rv-research-assistant ${open ? "open" : "closed"}`}
    >
      {!open ? (
        <button type="button" onClick={() => setOpen(true)}>
          Ask ReefVision
        </button>
      ) : (
        <section
          className="panel-card rv-research-assistant-panel"
          aria-label="ReefVision Assistant"
        >
          <div className="section-heading">
            <div>
              <p className="eyebrow">Research assistant</p>
              <h3>Ask ReefVision</h3>
              <p className="annotation-helper">
                {project.name} · {VIEW_LABELS[activeView] ?? activeView}
              </p>
            </div>
            <button
              type="button"
              className="secondary"
              onClick={() => setOpen(false)}
            >
              Close
            </button>
          </div>

          <p className="annotation-helper">
            Navigation, workflow, and keyboard help are grounded in ReefVision's
            canonical controls. The base SmolVLM model provides optional local
            image interpretation and remains advisory; it never changes research
            data.
          </p>

          <div
            aria-live="polite"
            style={{
              display: "grid",
              gap: 8,
              maxHeight: 300,
              overflow: "auto",
              marginBottom: 12,
            }}
          >
            {messages.length === 0 && (
              <p className="muted-copy">
                Ask where a tool lives, how a workflow works, or optionally ask
                SmolVLM about a selected project image.
              </p>
            )}
            {messages.map((message) => (
              <div
                key={message.id}
                className="annotation-selection-row"
                style={{ display: "block" }}
              >
                <strong>
                  {message.role === "user" ? "You" : "ReefVision"}
                </strong>
                <p style={{ whiteSpace: "pre-wrap" }}>{message.text}</p>
                {message.navigateTo && message.navigateLabel && (
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => {
                      onNavigate(message.navigateTo as ReefVisionView);
                      setOpen(false);
                    }}
                  >
                    {message.navigateLabel}
                  </button>
                )}
              </div>
            ))}
          </div>

          <label>
            Question
            <textarea
              rows={3}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="How do I calibrate an image?"
            />
          </label>

          <details>
            <summary>Optional image interpretation</summary>
            <label>
              Image
              <select
                value={selectedImageId}
                onChange={(event) => setSelectedImageId(event.target.value)}
              >
                <option value="">Choose an image</option>
                {imagesQuery.data?.map((image) => (
                  <option key={image.id} value={image.id}>
                    {image.original_filename}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <input
                type="checkbox"
                checked={useImageModel}
                disabled={!smolvlmReady || !selectedImageId}
                onChange={(event) => setUseImageModel(event.target.checked)}
              />{" "}
              Ask SmolVLM about this image
            </label>
            <p className="annotation-helper">
              SmolVLM status:{" "}
              {modelCatalogQuery.isPending
                ? "Checking…"
                : (smolvlm?.installation_state ?? "Model Required")}
            </p>
            {!smolvlmReady && !modelCatalogQuery.isPending && (
              <p className="form-error">
                Model required — register a compatible SmolVLM model to use
                image interpretation.
              </p>
            )}
          </details>

          <div className="button-row">
            <button
              type="button"
              onClick={() => void submitQuestion()}
              disabled={
                !question.trim() ||
                imageMutation.isPending ||
                (useImageModel && (!selectedImageId || !smolvlmReady))
              }
            >
              {imageMutation.isPending ? "Thinking…" : "Ask"}
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => setMessages([])}
              disabled={messages.length === 0}
            >
              Clear
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
