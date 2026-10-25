import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
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
  georeference_height_offset_m: 0,
  georeference_height_evidence: null,
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

function renderGallery(
  onOpenAnnotation?: (imageId: string) => void,
  onInferenceSelectionChange?: (imageIds: string[]) => void,
  onFocusedImageChange?: (imageId: string | null) => void,
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <Gallery
        project={project}
        onOpenAnnotation={onOpenAnnotation}
        onInferenceSelectionChange={onInferenceSelectionChange}
        onFocusedImageChange={onFocusedImageChange}
      />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
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
    expect(
      await screen.findByRole("article", { name: /swiftia-01\.png/ }),
    ).toBeInTheDocument();
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
    await screen.findByRole("article", { name: /swiftia-01\.png/ });
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

  it("uploads selected files and allows retrying the same camera JPEG", async () => {
    const importCalls = vi.fn();
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
        importCalls();
        expect(init?.method).toBe("POST");
        expect(init?.body).toBeInstanceOf(FormData);
        return jsonResponse({
          project_id: project.id,
          successful: [
            {
              filename: "coral.JPEG",
              relative_path: "coral.JPEG",
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
    const file = new File(["image bytes"], "coral.JPEG", {
      type: "image/jpeg",
    });
    const fileInput = screen.getByLabelText("Import files") as HTMLInputElement;
    await userEvent.upload(fileInput, file);

    expect(await screen.findByText("1 files processed")).toBeInTheDocument();
    expect(screen.getByText("1 imported")).toBeInTheDocument();
    expect(fileInput.value).toBe("");
    await userEvent.upload(fileInput, file);
    await waitFor(() => expect(importCalls).toHaveBeenCalledTimes(2));
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
  it("publishes the selected image batch to workbench inference controls", async () => {
    const onInferenceSelectionChange = vi.fn();

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

    renderGallery(undefined, onInferenceSelectionChange);

    await screen.findByRole("article", { name: /swiftia-01\.png/ });

    expect(
      screen.queryByRole("heading", { name: "Batch model deployment" }),
    ).not.toBeInTheDocument();

    await userEvent.click(screen.getByLabelText("Select image"));

    await waitFor(() =>
      expect(onInferenceSelectionChange).toHaveBeenLastCalledWith(["image-1"]),
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Clear selection" }),
    );

    await waitFor(() =>
      expect(onInferenceSelectionChange).toHaveBeenLastCalledWith([]),
    );
  });

  it("publishes the focused image for morphometrics context", async () => {
    const onFocusedImageChange = vi.fn();

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

    renderGallery(undefined, undefined, onFocusedImageChange);

    await screen.findByRole("article", { name: /swiftia-01\.png/ });

    await waitFor(() =>
      expect(onFocusedImageChange).toHaveBeenLastCalledWith("image-1"),
    );
  });

  it("restores the project's recent image and navigates with viewer keys", async () => {
    const secondImage: ProjectImage = {
      ...image,
      id: "image-2",
      original_filename: "swiftia-02.png",
    };
    window.localStorage.setItem(
      `reefvision.gallery.${project.id}.v1`,
      JSON.stringify({ imageId: secondImage.id, page: 1, wrap: false }),
    );
    const onFocusedImageChange = vi.fn();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        items: [image, secondImage],
        total: 2,
        page: 1,
        page_size: 24,
        pages: 1,
      }),
    );

    renderGallery(undefined, undefined, onFocusedImageChange);

    const viewer = await screen.findByRole("region", {
      name: "Image workbench",
    });
    await waitFor(() =>
      expect(onFocusedImageChange).toHaveBeenLastCalledWith("image-2"),
    );
    viewer.focus();
    await userEvent.keyboard("{ArrowLeft}");
    await waitFor(() =>
      expect(onFocusedImageChange).toHaveBeenLastCalledWith("image-1"),
    );
    await userEvent.keyboard("{End}");
    await waitFor(() =>
      expect(onFocusedImageChange).toHaveBeenLastCalledWith("image-2"),
    );
  });

  it("loads only the adjacent page when keyboard navigation crosses a boundary", async () => {
    const requestedPages: number[] = [];
    const secondPageImage: ProjectImage = {
      ...image,
      id: "image-25",
      original_filename: "swiftia-25.png",
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = new URL(String(input), "http://localhost");
      const requestedPage = Number(url.searchParams.get("page") ?? "1");
      requestedPages.push(requestedPage);
      return jsonResponse({
        items: requestedPage === 1 ? [image] : [secondPageImage],
        total: 25,
        page: requestedPage,
        page_size: 24,
        pages: 2,
      });
    });

    renderGallery();
    const viewer = await screen.findByRole("region", {
      name: "Image workbench",
    });
    viewer.focus();
    await userEvent.keyboard("{ArrowRight}");

    await screen.findByRole("heading", { name: "swiftia-25.png", level: 3 });
    expect(requestedPages).toContain(2);
  });

  it("does not navigate from editor controls and persists optional wrapping", async () => {
    const secondImage: ProjectImage = {
      ...image,
      id: "image-2",
      original_filename: "swiftia-02.png",
    };
    const onFocusedImageChange = vi.fn();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        items: [image, secondImage],
        total: 2,
        page: 1,
        page_size: 24,
        pages: 1,
      }),
    );

    renderGallery(vi.fn(), undefined, onFocusedImageChange);
    const editorButton = await screen.findByRole("button", {
      name: "Open annotation editor",
    });
    editorButton.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(onFocusedImageChange).toHaveBeenLastCalledWith("image-1");

    await userEvent.click(screen.getByLabelText("Wrap image navigation"));
    const viewer = screen.getByRole("region", { name: "Image workbench" });
    viewer.focus();
    await userEvent.keyboard("{ArrowLeft}");
    await waitFor(() =>
      expect(onFocusedImageChange).toHaveBeenLastCalledWith("image-2"),
    );
    expect(
      JSON.parse(
        window.localStorage.getItem(`reefvision.gallery.${project.id}.v1`) ??
          "{}",
      ),
    ).toMatchObject({ imageId: "image-2", wrap: true });
  });

  it("shows a recoverable error when the focused image cannot load", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        items: [image],
        total: 1,
        page: 1,
        page_size: 24,
        pages: 1,
      }),
    );

    renderGallery();
    const focusedImage = await screen.findByAltText(
      "Focused project image: swiftia-01.png",
    );
    const originalUrl = focusedImage.getAttribute("src");
    fireEvent.error(focusedImage);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Image could not be displayed",
    );
    await userEvent.click(screen.getByRole("button", { name: "Retry image" }));
    const retryImage = await screen.findByAltText(
      "Focused project image: swiftia-01.png",
    );
    expect(retryImage).toBeInTheDocument();
    expect(retryImage.getAttribute("src")).not.toBe(originalUrl);
    expect(retryImage.getAttribute("src")).toContain("rv_retry=1");
  });

  it("allows an immediate retry while the first image is still loading", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        items: [image],
        total: 1,
        page: 1,
        page_size: 24,
        pages: 1,
      }),
    );

    renderGallery();
    const original = await screen.findByAltText(
      "Focused project image: swiftia-01.png",
    );
    const originalUrl = original.getAttribute("src");
    expect(
      screen.getByText("Loading full-resolution image..."),
    ).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Retry loading image" }),
    );
    const retried = screen.getByAltText(
      "Focused project image: swiftia-01.png",
    );
    expect(retried.getAttribute("src")).not.toBe(originalUrl);
    expect(retried.getAttribute("src")).toContain("rv_retry=1");
    expect(
      screen.getByText("Loading full-resolution image..."),
    ).toBeInTheDocument();

    fireEvent.load(retried);
    expect(
      screen.queryByRole("button", { name: "Retry loading image" }),
    ).not.toBeInTheDocument();
  });

  it("reveals an already decoded first image when WebView2 misses load", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        items: [image],
        total: 1,
        page: 1,
        page_size: 24,
        pages: 1,
      }),
    );
    vi.spyOn(HTMLImageElement.prototype, "complete", "get").mockImplementation(
      function (this: HTMLImageElement) {
        return this.alt.startsWith("Focused project image:");
      },
    );
    vi.spyOn(HTMLImageElement.prototype, "naturalWidth", "get").mockReturnValue(
      1600,
    );
    vi.spyOn(
      HTMLImageElement.prototype,
      "naturalHeight",
      "get",
    ).mockReturnValue(1200);

    renderGallery();
    expect(
      await screen.findByAltText("Focused project image: swiftia-01.png"),
    ).toBeInTheDocument();
    // No load event is dispatched: cached pixels must still become visible.
    await waitFor(() =>
      expect(
        screen.queryByText("Loading full-resolution image..."),
      ).not.toBeInTheDocument(),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("reveals the first image even if WebView2 decode never resolves", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        items: [image],
        total: 1,
        page: 1,
        page_size: 24,
        pages: 1,
      }),
    );

    renderGallery();
    const focused = await screen.findByAltText(
      "Focused project image: swiftia-01.png",
    );
    Object.defineProperty(focused, "decode", {
      configurable: true,
      value: vi.fn(() => new Promise<void>(() => {})),
    });

    fireEvent.load(focused);

    expect(
      screen.queryByText("Loading full-resolution image..."),
    ).not.toBeInTheDocument();
  });

  it("resets the first-image loading state during navigation", async () => {
    const secondImage: ProjectImage = {
      ...image,
      id: "image-2",
      original_filename: "swiftia-02.png",
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        items: [image, secondImage],
        total: 2,
        page: 1,
        page_size: 24,
        pages: 1,
      }),
    );
    renderGallery();
    const first = await screen.findByAltText(
      "Focused project image: swiftia-01.png",
    );
    expect(
      screen.getByText("Loading full-resolution image..."),
    ).toBeInTheDocument();
    fireEvent.load(first);
    expect(
      screen.queryByText("Loading full-resolution image..."),
    ).not.toBeInTheDocument();

    const viewer = screen.getByRole("region", { name: "Image workbench" });
    viewer.focus();
    await userEvent.keyboard("{ArrowRight}");
    const next = await screen.findByAltText(
      "Focused project image: swiftia-02.png",
    );
    expect(
      screen.getByText("Loading full-resolution image..."),
    ).toBeInTheDocument();
    fireEvent.load(next);
    expect(
      screen.queryByText("Loading full-resolution image..."),
    ).not.toBeInTheDocument();
  });

  it("recovers a stalled image with its thumbnail", async () => {
    const nativeSetTimeout = window.setTimeout.bind(window);
    vi.spyOn(window, "setTimeout").mockImplementation(
      (handler, timeout, ...args) =>
        nativeSetTimeout(handler, timeout === 30_000 ? 250 : timeout, ...args),
    );
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        items: [{ ...image, thumbnail_path: "managed/thumbnail.png" }],
        total: 1,
        page: 1,
        page_size: 24,
        pages: 1,
      }),
    );

    renderGallery();
    const original = await screen.findByAltText(
      "Focused project image: swiftia-01.png",
    );
    expect(original.getAttribute("src")).toMatch(/display/);
    // Wait for the watchdog to replace the still-pending original request.
    await waitFor(
      () =>
        expect(
          screen
            .getByAltText("Focused project image: swiftia-01.png")
            .getAttribute("src"),
        ).toMatch(/thumbnail/),
      { timeout: 1000 },
    );
    const fallback = screen.getByAltText(
      "Focused project image: swiftia-01.png",
    );
    fireEvent.load(fallback);
    expect(
      screen.getByText(/Full-resolution image unavailable/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("offers retry when an image stalls without a thumbnail", async () => {
    const nativeSetTimeout = window.setTimeout.bind(window);
    vi.spyOn(window, "setTimeout").mockImplementation(
      (handler, timeout, ...args) =>
        nativeSetTimeout(handler, timeout === 30_000 ? 250 : timeout, ...args),
    );
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        items: [image],
        total: 1,
        page: 1,
        page_size: 24,
        pages: 1,
      }),
    );

    renderGallery();
    await screen.findByAltText("Focused project image: swiftia-01.png");
    expect(
      await screen.findByRole("alert", {}, { timeout: 1000 }),
    ).toHaveTextContent("Image could not be displayed");
    await userEvent.click(screen.getByRole("button", { name: "Retry image" }));
    expect(
      screen
        .getByAltText("Focused project image: swiftia-01.png")
        .getAttribute("src"),
    ).toContain("rv_retry=1");
  });

  it("labels the thumbnail when the full-resolution source fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        items: [{ ...image, thumbnail_path: "managed/thumbnail.png" }],
        total: 1,
        page: 1,
        page_size: 24,
        pages: 1,
      }),
    );
    renderGallery();
    const original = await screen.findByAltText(
      "Focused project image: swiftia-01.png",
    );
    fireEvent.error(original);
    expect(
      screen.getByText("Loading thumbnail preview..."),
    ).toBeInTheDocument();
    const fallback = screen.getByAltText(
      "Focused project image: swiftia-01.png",
    );
    expect(fallback.getAttribute("src")).toMatch(/thumbnail/);
    fireEvent.load(fallback);
    expect(
      screen.getByText(/Full-resolution image unavailable/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("bypasses a failed thumbnail cache when retrying the focused image", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        items: [{ ...image, thumbnail_path: "managed/thumbnail.png" }],
        total: 1,
        page: 1,
        page_size: 24,
        pages: 1,
      }),
    );
    renderGallery();
    const original = await screen.findByAltText(
      "Focused project image: swiftia-01.png",
    );
    fireEvent.error(original);
    const fallback = screen.getByAltText(
      "Focused project image: swiftia-01.png",
    );
    expect(fallback.getAttribute("src")).toMatch(/renderer=2/);
    fireEvent.error(fallback);
    await userEvent.click(screen.getByRole("button", { name: "Retry image" }));
    const retried = await screen.findByAltText(
      "Focused project image: swiftia-01.png",
    );
    expect(retried.getAttribute("src")).toContain("rv_retry=1");
    fireEvent.error(retried);
    const nextFallback = screen.getByAltText(
      "Focused project image: swiftia-01.png",
    );
    expect(nextFallback.getAttribute("src")).toMatch(/renderer=2&rv_retry=1/);
  });

  it("recovers a focused image when a background thumbnail is published", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const response = (thumbnailPath: string | null) => ({
      items: [{ ...image, thumbnail_path: thumbnailPath }],
      total: 1,
      page: 1,
      page_size: 24,
      pages: 1,
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(response(null)),
    );
    render(
      <QueryClientProvider client={queryClient}>
        <Gallery project={project} />
      </QueryClientProvider>,
    );

    const original = await screen.findByAltText(
      "Focused project image: swiftia-01.png",
    );
    fireEvent.error(original);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Image could not be displayed",
    );

    await act(async () => {
      queryClient.setQueriesData(
        { queryKey: ["images", project.id] },
        response("projects/project-1/images/thumbnails/first.jpg"),
      );
    });
    const firstFallback = await screen.findByAltText(
      "Focused project image: swiftia-01.png",
    );
    const firstUrl = firstFallback.getAttribute("src");
    expect(firstUrl).toContain("rv_thumb=");
    fireEvent.error(firstFallback);
    expect(screen.getByRole("alert")).toBeInTheDocument();

    // A refresh with the same failed path must not cause an endless retry.
    await act(async () => {
      queryClient.setQueriesData(
        { queryKey: ["images", project.id] },
        response("projects/project-1/images/thumbnails/first.jpg"),
      );
    });
    expect(screen.getByRole("alert")).toBeInTheDocument();

    await act(async () => {
      queryClient.setQueriesData(
        { queryKey: ["images", project.id] },
        response("projects/project-1/images/thumbnails/second.jpg"),
      );
    });
    const recovered = await screen.findByAltText(
      "Focused project image: swiftia-01.png",
    );
    expect(recovered.getAttribute("src")).not.toBe(firstUrl);
    expect(recovered.getAttribute("src")).toContain("rv_thumb=");
    fireEvent.load(recovered);
    expect(
      screen.getByText(/Full-resolution image unavailable/),
    ).toBeInTheDocument();
  });

  it("falls back to the first eligible image when the recent image was deleted", async () => {
    window.localStorage.setItem(
      `reefvision.gallery.${project.id}.v1`,
      JSON.stringify({ imageId: "deleted-image", page: 1, wrap: false }),
    );
    const onFocusedImageChange = vi.fn();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        items: [image],
        total: 1,
        page: 1,
        page_size: 24,
        pages: 1,
      }),
    );

    renderGallery(undefined, undefined, onFocusedImageChange);

    await waitFor(() =>
      expect(onFocusedImageChange).toHaveBeenLastCalledWith("image-1"),
    );
  });

  it("does not let a slower previous-project request replace the active project", async () => {
    const nextProject: Project = {
      ...project,
      id: "project-2",
      name: "Second study",
      slug: "second-study",
    };
    const nextImage: ProjectImage = {
      ...image,
      id: "next-image",
      project_id: nextProject.id,
      original_filename: "active-project.png",
    };
    let resolvePrevious: ((response: Response) => void) | undefined;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes(`/projects/${project.id}/images`)) {
        return await new Promise<Response>((resolve) => {
          resolvePrevious = resolve;
        });
      }
      if (url.includes(`/projects/${nextProject.id}/images`)) {
        return jsonResponse({
          items: [nextImage],
          total: 1,
          page: 1,
          page_size: 24,
          pages: 1,
        });
      }
      throw new Error(`Unhandled request GET ${url}`);
    });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const view = render(
      <QueryClientProvider client={queryClient}>
        <Gallery key={project.id} project={project} />
      </QueryClientProvider>,
    );

    view.rerender(
      <QueryClientProvider client={queryClient}>
        <Gallery key={nextProject.id} project={nextProject} />
      </QueryClientProvider>,
    );
    expect(
      await screen.findByRole("heading", {
        name: "active-project.png",
        level: 3,
      }),
    ).toBeInTheDocument();

    await act(async () => {
      resolvePrevious?.(
        jsonResponse({
          items: [image],
          total: 1,
          page: 1,
          page_size: 24,
          pages: 1,
        }),
      );
    });
    expect(screen.queryByText("swiftia-01.png")).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "active-project.png", level: 3 }),
    ).toBeInTheDocument();
  });

  it("recovers a failed thumbnail when its background job publishes a new path", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const response = (thumbnailPath: string) => ({
      items: [{ ...image, thumbnail_path: thumbnailPath }],
      total: 1,
      page: 1,
      page_size: 24,
      pages: 1,
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(response("projects/project-1/images/thumbnails/old.jpg")),
    );

    render(
      <QueryClientProvider client={queryClient}>
        <Gallery project={project} />
      </QueryClientProvider>,
    );
    const failed = await screen.findByAltText("Thumbnail of swiftia-01.png");
    const failedUrl = failed.getAttribute("src");
    fireEvent.error(failed);
    expect(
      screen.queryByAltText("Thumbnail of swiftia-01.png"),
    ).not.toBeInTheDocument();

    const updated = response("projects/project-1/images/thumbnails/new.jpg");
    await act(async () => {
      queryClient.setQueriesData({ queryKey: ["images", project.id] }, updated);
    });
    const recovered = await screen.findByAltText("Thumbnail of swiftia-01.png");
    expect(recovered.getAttribute("src")).not.toBe(failedUrl);
    expect(recovered.getAttribute("src")).toContain("rv_thumb=");

    // A normal query refresh with the same path must not retry indefinitely.
    fireEvent.error(recovered);
    await act(async () => {
      queryClient.setQueriesData(
        { queryKey: ["images", project.id] },
        response(updated.items[0].thumbnail_path),
      );
    });
    expect(
      screen.queryByAltText("Thumbnail of swiftia-01.png"),
    ).not.toBeInTheDocument();
  });

  it("contains wheel input when thumbnails fit without scrolling the page", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        items: [image],
        total: 1,
        page: 1,
        page_size: 24,
        pages: 1,
      }),
    );
    renderGallery();

    const filmstrip = await screen.findByRole("list", {
      name: "Nearby images",
    });
    // jsdom has no layout, so the filmstrip has no horizontal overflow.
    const wheel = new WheelEvent("wheel", {
      deltaY: 120,
      bubbles: true,
      cancelable: true,
    });
    fireEvent(filmstrip, wheel);
    expect(wheel.defaultPrevented).toBe(true);
    expect(filmstrip.scrollLeft).toBe(0);

    // Browser zoom remains available with the standard modifier.
    const zoom = new WheelEvent("wheel", {
      deltaY: 120,
      ctrlKey: true,
      bubbles: true,
      cancelable: true,
    });
    fireEvent(filmstrip, zoom);
    expect(zoom.defaultPrevented).toBe(false);
  });

  it("bounds horizontal filmstrip wheel scrolling at both ends", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        items: [image],
        total: 1,
        page: 1,
        page_size: 24,
        pages: 1,
      }),
    );
    renderGallery();

    const filmstrip = await screen.findByRole("list", {
      name: "Nearby images",
    });
    Object.defineProperty(filmstrip, "scrollWidth", {
      configurable: true,
      value: 500,
    });
    Object.defineProperty(filmstrip, "clientWidth", {
      configurable: true,
      value: 200,
    });
    const forward = new WheelEvent("wheel", {
      deltaY: 1000,
      bubbles: true,
      cancelable: true,
    });
    fireEvent(filmstrip, forward);
    expect(forward.defaultPrevented).toBe(true);
    expect(filmstrip.scrollLeft).toBe(300);

    const backward = new WheelEvent("wheel", {
      deltaY: -1000,
      bubbles: true,
      cancelable: true,
    });
    fireEvent(filmstrip, backward);
    expect(backward.defaultPrevented).toBe(true);
    expect(filmstrip.scrollLeft).toBe(0);
  });

  it("keeps focus navigation inside the horizontal filmstrip", async () => {
    const secondImage: ProjectImage = {
      ...image,
      id: "image-2",
      original_filename: "swiftia-02.png",
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        items: [image, secondImage],
        total: 2,
        page: 1,
        page_size: 24,
        pages: 1,
      }),
    );
    renderGallery();

    const filmstrip = await screen.findByRole("list", {
      name: "Nearby images",
    });
    const first = screen.getByRole("listitem", {
      name: "Focus swiftia-01.png",
    });
    const second = screen.getByRole("listitem", {
      name: "Focus swiftia-02.png",
    });
    vi.spyOn(filmstrip, "getBoundingClientRect").mockReturnValue({
      left: 100,
      right: 400,
    } as DOMRect);
    vi.spyOn(second, "getBoundingClientRect").mockReturnValue({
      left: 450,
      right: 550,
    } as DOMRect);
    vi.spyOn(first, "getBoundingClientRect").mockReturnValue({
      left: 50,
      right: 150,
    } as DOMRect);
    const scrollIntoView = vi.fn();
    Object.defineProperty(second, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });

    await userEvent.click(second);
    await waitFor(() => expect(filmstrip.scrollLeft).toBe(150));
    expect(scrollIntoView).not.toHaveBeenCalled();

    await userEvent.click(first);
    await waitFor(() => expect(filmstrip.scrollLeft).toBe(100));
  });
});
