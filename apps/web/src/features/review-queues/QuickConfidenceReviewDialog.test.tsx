import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ComponentProps } from "react";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  acceptPrediction,
  getAnnotationSession,
  getPredictions,
  rejectPrediction,
  type PredictionProposal,
  type ReviewQueueItem,
} from "../../api/client";
import { QuickConfidenceReviewDialog } from "./QuickConfidenceReviewDialog";

vi.mock("../../api/client", () => ({
  acceptPrediction: vi.fn(),
  rejectPrediction: vi.fn(),
  getAnnotationSession: vi.fn(),
  getPredictions: vi.fn(),
  imageDisplayUrl: (id: string) => `/api/v1/images/${id}/display`,
  imageThumbnailUrl: (id: string) => `/api/v1/images/${id}/thumbnail`,
}));

const item = {
  id: "queue-item-1",
  image_id: "image-1",
  project_id: "project-1",
  review_queue_id: "queue-1",
  review_state: "pending",
} as ReviewQueueItem;

function proposal(id: string, confidence: number): PredictionProposal {
  return {
    id,
    project_id: "project-1",
    image_id: "image-1",
    model_id: "model-1",
    model_display_name: "Coral best.pt",
    inference_job_id: "job-1",
    model_checksum: "a".repeat(64),
    label_class_id: "class-1",
    predicted_label: "Swiftia exserta",
    predicted_index: 0,
    confidence,
    x_min: 5,
    y_min: 10,
    x_max: 55,
    y_max: 45,
    review_status: "pending",
    was_edited: false,
    reviewer_action_at: null,
    accepted_annotation_id: null,
    inference_settings_json: {},
    provenance_json: null,
    created_at: "2026-10-10T00:00:00Z",
  };
}

function renderDialog(
  options: Partial<ComponentProps<typeof QuickConfidenceReviewDialog>> = {},
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const callbacks = {
    onClose: vi.fn(),
    onPreviousImage: vi.fn(),
    onNextImage: vi.fn(),
    onOpenFullEditor: vi.fn(),
    onMarkComplete: vi.fn(),
  };
  const result = render(
    <QueryClientProvider client={client}>
      <QuickConfidenceReviewDialog
        item={item}
        reviewBelowConfidence={0.5}
        position={1}
        total={2}
        markingComplete={false}
        {...callbacks}
        {...options}
      />
    </QueryClientProvider>,
  );
  return { ...result, ...callbacks };
}

describe("QuickConfidenceReviewDialog", () => {
  beforeEach(() => {
    vi.mocked(getAnnotationSession).mockResolvedValue({
      image: {
        id: "image-1",
        original_filename: "swiftia.png",
        width_px: 80,
        height_px: 60,
      },
      label_classes: [
        { id: "class-1", name: "Swiftia exserta", is_active: true },
      ],
      annotations: [],
      counts_by_class: [],
      previous_image_id: null,
      next_image_id: null,
    } as unknown as Awaited<ReturnType<typeof getAnnotationSession>>);
    vi.mocked(getPredictions).mockResolvedValue({
      items: [
        proposal("low", 0.4),
        proposal("equal", 0.5),
        proposal("high", 0.9),
      ],
      counts: { pending: 3 },
    });
    vi.mocked(acceptPrediction).mockResolvedValue(
      {} as Awaited<ReturnType<typeof acceptPrediction>>,
    );
    vi.mocked(rejectPrediction).mockResolvedValue(
      {} as Awaited<ReturnType<typeof rejectPrediction>>,
    );
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("shows only predictions below the configured review threshold", async () => {
    renderDialog();
    const dialog = await screen.findByRole("dialog", {
      name: "Confidence-based review",
    });
    expect(await within(dialog).findByText("40.0%")).toBeTruthy();
    expect(within(dialog).queryByText("90.0%")).toBeNull();
    expect(within(dialog).getByText(/review at or below 50%/)).toBeTruthy();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Next prediction" }),
    );
    expect(await within(dialog).findByText("50.0%")).toBeTruthy();
  });

  it("explicit acceptance preserves the selected project class", async () => {
    renderDialog();
    await screen.findByText("40.0%");
    fireEvent.click(screen.getByRole("button", { name: "Accept prediction" }));
    await waitFor(() => {
      expect(acceptPrediction).toHaveBeenCalledWith("low", {
        label_class_id: "class-1",
      });
    });
    expect(acceptPrediction).not.toHaveBeenCalledWith(
      "high",
      expect.anything(),
    );
  });

  it("allows a researcher to accept and create an unmapped .pt class", async () => {
    vi.mocked(getPredictions).mockResolvedValue({
      items: [
        {
          ...proposal("unmapped", 0.3),
          label_class_id: null,
          predicted_label: "New coral",
        },
      ],
      counts: { pending: 1 },
    });
    renderDialog();
    await screen.findByRole("button", { name: "Accept and create class" });
    fireEvent.click(
      screen.getByRole("button", { name: "Accept and create class" }),
    );
    await waitFor(() => {
      expect(acceptPrediction).toHaveBeenCalledWith("unmapped", {});
    });
  });

  it("navigates the editor images without inventing a ranked queue position", async () => {
    const { onPreviousImage, onNextImage } = renderDialog({
      showRankedPosition: false,
      hasPreviousImage: true,
      hasNextImage: false,
      position: 1,
      total: 1,
    });
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Current image/)).toBeTruthy();
    const previous = within(dialog).getByRole("button", {
      name: "Previous image",
    });
    const next = within(dialog).getByRole("button", { name: "Next image" });
    expect(previous).toBeEnabled();
    expect(next).toBeDisabled();
    fireEvent.click(previous);
    expect(onPreviousImage).toHaveBeenCalledTimes(1);
    expect(onNextImage).not.toHaveBeenCalled();
  });

  it("shows a retryable error instead of an invisible failed preview", async () => {
    renderDialog();
    const image = await screen.findByRole("img", { name: "swiftia.png" });
    fireEvent.error(image);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Image preview failed to load",
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry image preview" }));
    const retried = await screen.findByRole("img", { name: "swiftia.png" });
    expect(retried).toHaveAttribute(
      "src",
      "/api/v1/images/image-1/display?review_retry=1",
    );
  });

  it("falls back to a thumbnail before offering retry", async () => {
    vi.mocked(getAnnotationSession).mockResolvedValue({
      image: {
        id: "image-1",
        original_filename: "swiftia.png",
        width_px: 80,
        height_px: 60,
        thumbnail_path: "thumbs/swiftia.png",
      },
      label_classes: [],
      annotations: [],
      counts_by_class: [],
      previous_image_id: null,
      next_image_id: null,
    } as unknown as Awaited<ReturnType<typeof getAnnotationSession>>);
    renderDialog();
    fireEvent.error(await screen.findByRole("img", { name: "swiftia.png" }));
    expect(screen.getByRole("img", { name: "swiftia.png" })).toHaveAttribute(
      "src",
      "/api/v1/images/image-1/thumbnail",
    );
    fireEvent.error(screen.getByRole("img", { name: "swiftia.png" }));
    expect(screen.getByRole("button", { name: "Retry image preview" })).toBeEnabled();
  });

  it("has navigation and a close action without leaving the page", async () => {
    const { onClose, onNextImage } = renderDialog();
    await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: "Next image" }));
    expect(onNextImage).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Close quick review" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
