import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Project, ProjectImage } from "../../api/client";
import { Gallery } from "./Gallery";

const project: Project = {
  id: "project-1",
  name: "CPT Coral Study",
  slug: "cpt-coral-study",
  description: null,
  storage_root: "projects/project-1",
  default_annotation_type: "bbox",
  created_at: "2026-07-08T00:00:00Z",
  updated_at: "2026-07-08T00:00:00Z",
  archived_at: null,
  label_classes: [],
};

const image: ProjectImage = {
  id: "image-1",
  project_id: project.id,
  original_filename: "swiftia-01.png",
  managed_path: "projects/project-1/images/originals/image-1.png",
  thumbnail_path: null,
  sha256: "a".repeat(64),
  width_px: 1600,
  height_px: 1200,
  file_size_bytes: 1000,
  media_type: "image/png",
  import_source: "trial/swiftia-01.png",
  capture_timestamp: null,
  group_key: null,
  metadata_json: {},
  annotation_status: "unannotated",
  annotation_revision: 0,
  annotation_count: 0,
  created_at: "2026-07-08T00:00:00Z",
  updated_at: "2026-07-08T00:00:00Z",
};

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderGallery(onOpenAnnotation?: (imageId: string) => void) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <Gallery project={project} onOpenAnnotation={onOpenAnnotation} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Gallery", () => {
  it("edits image grouping and annotation status", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) => {
        const url = String(input);
        if (url.includes(`/projects/${project.id}/images`)) {
          return jsonResponse({
            items: [image],
            total: 1,
            page: 1,
            page_size: 24,
            pages: 1,
          });
        }
        if (url.endsWith(`/images/${image.id}`) && init?.method === "PATCH") {
          return jsonResponse({
            ...image,
            group_key: "whole-image-7",
            annotation_status: "reviewed",
            annotation_revision: 1,
          });
        }
        throw new Error(`Unhandled request ${init?.method ?? "GET"} ${url}`);
      });

    renderGallery();
    expect(await screen.findByText("swiftia-01.png")).toBeInTheDocument();
    await userEvent.type(
      screen.getByPlaceholderText("e.g. source-image-001"),
      "whole-image-7",
    );
    await userEvent.selectOptions(
      screen.getByLabelText("Image status"),
      "reviewed",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Save metadata" }),
    );

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringMatching(/\/images\/image-1$/),
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({
            group_key: "whole-image-7",
            annotation_status: "reviewed",
          }),
        }),
      ),
    );
  });

  it("opens the annotation editor for a selected image", async () => {
    const onOpenAnnotation = vi.fn();
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes(`/projects/${project.id}/images`)) {
        return jsonResponse({
          items: [image],
          total: 1,
          page: 1,
          page_size: 24,
          pages: 1,
        });
      }
      throw new Error(`Unhandled request GET ${url}`);
    });

    renderGallery(onOpenAnnotation);
    await screen.findByText("swiftia-01.png");
    await userEvent.click(
      screen.getByRole("button", { name: "Select all visible" }),
    );
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    expect(screen.getByLabelText("Select image")).toBeChecked();
    await userEvent.type(
      screen.getByPlaceholderText("Search filenames"),
      "swiftia",
    );
    await waitFor(() =>
      expect(globalThis.fetch).toHaveBeenCalledWith(
        expect.stringContaining("filename=swiftia"),
        expect.any(Object),
      ),
    );
    await userEvent.click(screen.getByRole("button", { name: "Annotate" }));

    expect(onOpenAnnotation).toHaveBeenCalledWith("image-1");
  });

  it("uploads selected files and shows the structured import report", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes(`/projects/${project.id}/images`)) {
        return jsonResponse({
          items: [],
          total: 0,
          page: 1,
          page_size: 24,
          pages: 0,
        });
      }
      if (url.endsWith(`/projects/${project.id}/imports/images`)) {
        expect(init?.method).toBe("POST");
        expect(init?.body).toBeInstanceOf(FormData);
        return jsonResponse({
          project_id: project.id,
          successful: [
            {
              filename: "coral.png",
              relative_path: "coral.png",
              status: "successful",
              detail: null,
              image_id: "image-2",
              duplicate_image_id: null,
              thumbnail_job_id: "job-1",
            },
          ],
          duplicates: [],
          unsupported: [],
          failed: [],
        });
      }
      throw new Error(`Unhandled request ${init?.method ?? "GET"} ${url}`);
    });

    renderGallery();
    await screen.findByText("No images yet");
    const file = new File(["image bytes"], "coral.png", { type: "image/png" });
    await userEvent.upload(screen.getByLabelText("Import files"), file);

    expect(await screen.findByText("1 files processed")).toBeInTheDocument();
    expect(screen.getByText("1 imported")).toBeInTheDocument();
  });

  it("jumps directly to a requested page with global newest-first ordering", async () => {
    const requestedPages: number[] = [];
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input) => {
        const url = new URL(String(input), "http://localhost");
        if (url.pathname.includes(`/projects/${project.id}/images`)) {
          requestedPages.push(Number(url.searchParams.get("page") ?? "1"));
          expect(url.searchParams.get("sort_by")).toBe("newest");
          return jsonResponse({
            items: [],
            total: 792,
            page: Number(url.searchParams.get("page") ?? "1"),
            page_size: 24,
            pages: 33,
          });
        }
        throw new Error(`Unhandled request GET ${url}`);
      });

    renderGallery();
    const pageInput = await screen.findByLabelText("Page number");
    expect(pageInput).toHaveValue(1);
    expect(fetchMock).toHaveBeenCalled();

    await userEvent.clear(pageInput);
    await userEvent.type(pageInput, "30");
    await userEvent.tab();

    await waitFor(() => expect(requestedPages).toContain(30));
    expect(pageInput).toHaveValue(30);
  });

  it("splits large image selections into bounded import batches", async () => {
    const batchSizes: number[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes(`/projects/${project.id}/images`)) {
        return jsonResponse({
          items: [],
          total: 0,
          page: 1,
          page_size: 24,
          pages: 0,
        });
      }
      if (url.endsWith(`/projects/${project.id}/imports/images`)) {
        expect(init?.method).toBe("POST");
        const formData = init?.body as FormData;
        const files = formData.getAll("files") as File[];
        batchSizes.push(files.length);
        return jsonResponse({
          project_id: project.id,
          successful: files.map((file, index) => ({
            filename: file.name,
            relative_path: file.name,
            status: "successful",
            detail: null,
            image_id: `image-batch-${batchSizes.length}-${index}`,
            duplicate_image_id: null,
            thumbnail_job_id: `thumbnail-batch-${batchSizes.length}-${index}`,
          })),
          duplicates: [],
          unsupported: [],
          failed: [],
        });
      }
      throw new Error(`Unhandled request ${init?.method ?? "GET"} ${url}`);
    });

    renderGallery();
    await screen.findByText("No images yet");
    const files = Array.from(
      { length: 21 },
      (_, index) =>
        new File(["image bytes"], `coral-${index + 1}.png`, {
          type: "image/png",
        }),
    );

    await userEvent.upload(screen.getByLabelText("Import files"), files);

    expect(await screen.findByText("21 files processed")).toBeInTheDocument();
    expect(batchSizes).toEqual([10, 10, 1]);
  });
  it("keeps trained-model batch deployment visible outside advanced import controls", async () => {
    const model = {
      id: "model-best",
      project_id: project.id,
      purpose: "detector",
      display_name: "Coral best.pt",
      source_filename: "best.pt",
      managed_path: "projects/project-1/models/best.pt",
      sha256: "d".repeat(64),
      file_size_bytes: 1234,
      framework: "ultralytics",
      task: "detect",
      provider_name: "ultralytics",
      provider_version: "8.4.19",
      class_map_json: {},
      input_size_json: null,
      metadata_json: {},
      notes: null,
      created_at: "2026-09-16T00:00:00Z",
      updated_at: "2026-09-16T00:00:00Z",
    };
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      requests.push({ url, init });
      if (url.includes(`/projects/${project.id}/images`)) {
        return jsonResponse({
          items: [image],
          total: 1,
          page: 1,
          page_size: 24,
          pages: 1,
        });
      }
      if (url.includes(`/projects/${project.id}/models?purpose=detector`)) {
        return jsonResponse([model]);
      }
      if (
        url.endsWith(`/projects/${project.id}/inference-jobs`) &&
        init?.method === "POST"
      ) {
        return jsonResponse({
          id: "job-batch",
          project_id: project.id,
          job_type: "inference",
          status: "queued",
          progress_current: 0,
          progress_total: 1,
          result_json: {},
          error_message: null,
        });
      }
      if (url.includes("/jobs/job-batch")) {
        return jsonResponse({
          id: "job-batch",
          project_id: project.id,
          job_type: "inference",
          status: "succeeded",
          progress_current: 1,
          progress_total: 1,
          result_json: {},
          error_message: null,
        });
      }
      throw new Error(`Unhandled request ${init?.method ?? "GET"} ${url}`);
    });

    renderGallery();
    expect(
      await screen.findByRole("heading", { name: "Batch model deployment" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/trained or imported project model/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Run detector" }),
    ).not.toBeInTheDocument();

    await userEvent.click(screen.getByLabelText("Select image"));
    await userEvent.click(
      screen.getByRole("button", { name: "Run model on selected images" }),
    );

    await waitFor(() => {
      const request = requests.find(
        (entry) =>
          entry.url.endsWith(`/projects/${project.id}/inference-jobs`) &&
          entry.init?.method === "POST",
      );
      expect(request).toBeDefined();
      expect(JSON.parse(String(request?.init?.body))).toMatchObject({
        model_id: "model-best",
        image_ids: ["image-1"],
        confidence_threshold: 0.25,
      });
    });
  });
});
