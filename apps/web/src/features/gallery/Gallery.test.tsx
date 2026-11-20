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
import {
  Gallery,
  galleryPendingThumbnailPollingDecision,
  galleryPendingThumbnailRefetchMs,
} from "./Gallery";

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
  return {
    ...render(
      <QueryClientProvider client={queryClient}>
        <Gallery
          project={project}
          onOpenAnnotation={onOpenAnnotation}
          onInferenceSelectionChange={onInferenceSelectionChange}
          onFocusedImageChange={onFocusedImageChange}
        />
      </QueryClientProvider>,
    ),
    queryClient,
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("Gallery pending thumbnail refresh", () => {
  it("limits background metadata checks to the currently pending thumbnails", () => {
    const pending = { items: [{ thumbnail_path: null }] };
    const complete = { items: [{ thumbnail_path: "thumbnails/ready.jpg" }] };
    expect(galleryPendingThumbnailRefetchMs(undefined, 0)).toBe(false);
    expect(galleryPendingThumbnailRefetchMs(pending, 1)).toBe(5000);
    expect(galleryPendingThumbnailRefetchMs(pending, 12)).toBe(5000);
    expect(galleryPendingThumbnailRefetchMs(pending, 13)).toBe(false);
    expect(galleryPendingThumbnailRefetchMs(complete, 1)).toBe(false);
    expect(galleryPendingThumbnailRefetchMs({ items: [] }, 1)).toBe(false);
  });

  it("restarts bounded thumbnail polling for later camera imports and new views", () => {
    const first = { items: [{ id: "camera-1", thumbnail_path: null }] };
    const second = { items: [{ id: "camera-2", thumbnail_path: null }] };
    const complete = {
      items: [{ id: "camera-2", thumbnail_path: "thumbs/camera-2.jpg" }],
    };

    const initial = galleryPendingThumbnailPollingDecision(
      first,
      15,
      null,
      "project-a:page-1",
    );
    expect(initial.interval).toBe(5000);
    expect(
      galleryPendingThumbnailPollingDecision(
        first,
        26,
        initial.state,
        "project-a:page-1",
      ).interval,
    ).toBe(5000);
    expect(
      galleryPendingThumbnailPollingDecision(
        first,
        27,
        initial.state,
        "project-a:page-1",
      ).interval,
    ).toBe(false);

    // A new import after 12 previous checks must not inherit exhaustion.
    const imported = galleryPendingThumbnailPollingDecision(
      second,
      28,
      initial.state,
      "project-a:page-1",
    );
    expect(imported.interval).toBe(5000);
    // A query-key change must independently rearm pending-thumbnail checks.
    expect(
      galleryPendingThumbnailPollingDecision(
        second,
        50,
        imported.state,
        "project-a:filtered",
      ).interval,
    ).toBe(5000);
    expect(
      galleryPendingThumbnailPollingDecision(
        complete,
        51,
        imported.state,
        "project-a:page-1",
      ),
    ).toEqual({ interval: false, state: null });
  });

  it("does not restart thumbnail polling when the same pending images reorder", () => {
    const pending = {
      items: [
        { id: "camera-2", thumbnail_path: null },
        { id: "camera-1", thumbnail_path: null },
      ],
    };
    const reordered = { items: [...pending.items].reverse() };
    const initial = galleryPendingThumbnailPollingDecision(
      pending,
      5,
      null,
      "project-a:page-1",
    );
    expect(initial.interval).toBe(5000);

    // A metadata refresh can reorder the same camera observations.
    // After 12 checks, it must not silently grant another polling window.
    expect(
      galleryPendingThumbnailPollingDecision(
        reordered,
        17,
        initial.state,
        "project-a:page-1",
      ),
    ).toEqual({ interval: false, state: initial.state });
    // Signature canonicalization must never mutate the server's order.
    expect(pending.items.map((item) => item.id)).toEqual([
      "camera-2",
      "camera-1",
    ]);
  });

  it("stops failed background image-page polling without losing explicit retry", () => {
    const pending = { items: [{ id: "camera-1", thumbnail_path: null }] };
    const initial = galleryPendingThumbnailPollingDecision(
      pending,
      7,
      null,
      "project-a:page-1",
    );
    expect(initial.interval).toBe(5000);

    // React Query retains the last successful page after a background error;
    // dataUpdateCount stops advancing, so polling it alone could run forever.
    expect(
      galleryPendingThumbnailPollingDecision(
        pending,
        7,
        initial.state,
        "project-a:page-1",
        true,
      ),
    ).toEqual({ interval: false, state: initial.state });

    expect(
      galleryPendingThumbnailPollingDecision(
        undefined,
        0,
        null,
        "project-a:page-1",
        true,
      ),
    ).toEqual({ interval: false, state: null });

    // The explicit Retry/Refresh can recover after the server returns,
    // continuing the existing scientific image's bounded polling budget.
    const recovered = galleryPendingThumbnailPollingDecision(
      pending,
      8,
      initial.state,
      "project-a:page-1",
    );
    expect(recovered.interval).toBe(5000);
    expect(recovered.state).toEqual(initial.state);
    expect(
      galleryPendingThumbnailPollingDecision(
        pending,
        19,
        recovered.state,
        "project-a:page-1",
      ).interval,
    ).toBe(false);
  });

  it("recovers a failed thumbnail when the backend regenerates a new version", async () => {
    let requests = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (!url.includes(`/projects/${project.id}/images`)) {
        throw new Error(`Unexpected request ${url}`);
      }
      requests += 1;
      return jsonResponse({
        items: [
          {
            ...image,
            thumbnail_path:
              requests <= 2
                ? "thumbnails/broken.jpg"
                : "thumbnails/regenerated.jpg",
          },
        ],
        total: 1,
        page: 1,
        page_size: 24,
        pages: 1,
      });
    });

    const { queryClient } = renderGallery();
    const thumbnail = await screen.findByAltText("Thumbnail of swiftia-01.png");
    expect(thumbnail.getAttribute("src")).toContain("broken.jpg");
    fireEvent.error(thumbnail);
    expect(screen.queryByAltText("Thumbnail of swiftia-01.png")).toBeNull();
    expect(screen.getByText("Thumbnail unavailable")).toBeInTheDocument();

    // Refetching the same failed asset must not restart its broken request.
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ["images", project.id] });
    });
    expect(requests).toBe(2);
    expect(screen.queryByAltText("Thumbnail of swiftia-01.png")).toBeNull();
    expect(screen.getByText("Thumbnail unavailable")).toBeInTheDocument();

    // A genuinely regenerated path should retry, without reimporting the image.
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ["images", project.id] });
    });
    expect(requests).toBe(3);

    const recovered = await screen.findByAltText("Thumbnail of swiftia-01.png");
    expect(recovered.getAttribute("src")).toContain("regenerated.jpg");
    expect(recovered.getAttribute("src")).not.toContain("broken.jpg");
    fireEvent.error(recovered);
    expect(screen.queryByAltText("Thumbnail of swiftia-01.png")).toBeNull();
  });

  it("retries a failed camera thumbnail even when its managed path is unchanged", async () => {
    let metadataReads = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (!url.includes(`/projects/${project.id}/images`)) {
        throw new Error(`Unexpected request ${url}`);
      }
      metadataReads += 1;
      return jsonResponse({
        items: [{ ...image, thumbnail_path: "thumbnails/stable-camera.jpg" }],
        total: 1,
        page: 1,
        page_size: 24,
        pages: 1,
      });
    });

    const { queryClient } = renderGallery();
    const first = await screen.findByAltText("Thumbnail of swiftia-01.png");
    const originalUrl = first.getAttribute("src");
    expect(originalUrl).toContain("stable-camera.jpg");
    fireEvent.error(first);
    expect(screen.queryByAltText("Thumbnail of swiftia-01.png")).toBeNull();
    expect(screen.getByText("Thumbnail unavailable")).toBeInTheDocument();

    // Refreshing metadata does not change the failed URL and must not
    // automatically retry forever. A user can explicitly retry the same
    // regenerated-on-disk path without reimporting scientific originals.
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ["images", project.id] });
    });
    expect(metadataReads).toBe(2);
    expect(screen.queryByAltText("Thumbnail of swiftia-01.png")).toBeNull();

    await userEvent.click(
      screen.getByRole("button", { name: "Retry thumbnail" }),
    );
    const retryOne = await screen.findByAltText("Thumbnail of swiftia-01.png");
    expect(retryOne.getAttribute("src")).not.toBe(originalUrl);
    expect(retryOne.getAttribute("src")).toContain("rv_retry=1");
    fireEvent.error(retryOne);
    await userEvent.click(
      screen.getByRole("button", { name: "Retry thumbnail" }),
    );
    const retryTwo = await screen.findByAltText("Thumbnail of swiftia-01.png");
    expect(retryTwo.getAttribute("src")).toContain("rv_retry=2");
    expect(metadataReads).toBe(2);
  });

  it("automatically reloads metadata after thumbnail job completion", async () => {
    let reads = 0;
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input) => {
        const url = String(input);
        if (!url.includes(`/projects/${project.id}/images`)) {
          throw new Error(`Unexpected request ${url}`);
        }
        reads += 1;
        return jsonResponse({
          items: [
            {
              ...image,
              thumbnail_path: reads === 1 ? null : "thumbnails/completed.jpg",
            },
          ],
          total: 1,
          page: 1,
          page_size: 24,
          pages: 1,
        });
      });

    renderGallery();
    await screen.findByRole("article", { name: /swiftia-01\.png/ });
    expect(screen.queryByAltText("Thumbnail of swiftia-01.png")).toBeNull();
    expect(
      await screen.findByAltText(
        "Thumbnail of swiftia-01.png",
        {},
        { timeout: 8500 },
      ),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  }, 10_000);

  it("can refresh a pending image thumbnail without reimporting the original", async () => {
    let polls = 0;
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input) => {
        const url = String(input);
        if (!url.includes(`/projects/${project.id}/images`))
          throw new Error(`Unexpected request ${url}`);
        polls += 1;
        return jsonResponse({
          items: [
            {
              ...image,
              thumbnail_path: polls === 1 ? null : "thumbnails/ready.jpg",
            },
          ],
          total: 1,
          page: 1,
          page_size: 24,
          pages: 1,
        });
      });

    renderGallery();
    await screen.findByRole("article", { name: /swiftia-01\.png/ });
    expect(screen.queryByAltText("Thumbnail of swiftia-01.png")).toBeNull();
    await userEvent.click(
      screen.getByRole("button", { name: "Refresh pending thumbnails" }),
    );
    expect(
      await screen.findByAltText("Thumbnail of swiftia-01.png"),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(
      screen.queryByRole("button", { name: "Refresh pending thumbnails" }),
    ).toBeNull();
  });
});

describe("Gallery", () => {
  it("recovers an out-of-range saved page and first image", async () => {
    const preferenceKey = "reefvision.gallery.project-1.v1";
    window.localStorage.setItem(
      preferenceKey,
      JSON.stringify({ imageId: "deleted-image", page: 50, wrap: true }),
    );
    const requestedPages: number[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = new URL(String(input));
      if (!url.pathname.endsWith(`/projects/${project.id}/images`)) {
        throw new Error(`Unexpected request ${url}`);
      }
      const requestedPage = Number(url.searchParams.get("page"));
      requestedPages.push(requestedPage);
      return jsonResponse({
        items: requestedPage === 1 ? [image] : [],
        total: 1,
        page: requestedPage,
        page_size: 24,
        pages: 1,
      });
    });

    renderGallery();
    expect(
      await screen.findByAltText("Focused project image: swiftia-01.png"),
    ).toBeInTheDocument();
    expect(requestedPages).toEqual([50, 1]);
    await waitFor(() => {
      expect(
        JSON.parse(window.localStorage.getItem(preferenceKey) ?? "null"),
      ).toEqual({
        imageId: "image-1",
        page: 1,
        wrap: true,
      });
    });
  });

  it("displays the first image when WebView2 blocks localStorage access", async () => {
    const descriptor = Object.getOwnPropertyDescriptor(window, "localStorage");
    if (!descriptor)
      throw new Error("Expected a localStorage property descriptor");
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() {
        throw new DOMException("Storage access denied", "SecurityError");
      },
    });

    try {
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
      expect(
        await screen.findByAltText("Focused project image: swiftia-01.png"),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("region", { name: "Image workbench" }),
      ).toBeInTheDocument();
    } finally {
      Object.defineProperty(window, "localStorage", descriptor);
    }
  });

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

  it("preserves unsaved image metadata when a background thumbnail becomes available", async () => {
    let reads = 0;
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input) => {
        const url = String(input);
        if (!url.includes(`/projects/${project.id}/images`)) {
          throw new Error(`Unexpected request ${url}`);
        }
        reads += 1;
        return jsonResponse({
          items: [
            {
              ...image,
              thumbnail_path: reads === 1 ? null : "thumbnails/ready.jpg",
            },
          ],
          total: 1,
          page: 1,
          page_size: 24,
          pages: 1,
        });
      });

    renderGallery();
    await screen.findByRole("article", { name: /swiftia-01\.png/ });
    const groupKey = screen.getByPlaceholderText("e.g. source-image-001");
    const status = screen.getByLabelText("Image status");
    await userEvent.type(groupKey, "unsaved-parent-fragment");
    await userEvent.selectOptions(status, "reviewed");

    // Background thumbnail completion changes the image object but not the
    // persisted editable metadata. It must not overwrite the researcher's
    // in-progress draft or submit it without an explicit save.
    await userEvent.click(
      screen.getByRole("button", { name: "Refresh pending thumbnails" }),
    );
    await screen.findByAltText("Thumbnail of swiftia-01.png");
    expect(groupKey).toHaveValue("unsaved-parent-fragment");
    expect(status).toHaveValue("reviewed");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("preserves unsaved group and status edits when persisted metadata changes", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const response = (
      groupKey: string | null,
      status: ProjectImage["annotation_status"],
    ) => ({
      items: [{ ...image, group_key: groupKey, annotation_status: status }],
      total: 1,
      page: 1,
      page_size: 24,
      pages: 1,
    });
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(jsonResponse(response(null, "unannotated")));
    render(
      <QueryClientProvider client={queryClient}>
        <Gallery project={project} />
      </QueryClientProvider>,
    );

    await screen.findByRole("article", { name: /swiftia-01\.png/ });
    const groupKey = screen.getByPlaceholderText("e.g. source-image-001");
    const status = screen.getByLabelText("Image status");
    await userEvent.type(groupKey, "unsaved-parent-fragment");

    // Another editor updates both persisted fields. The local group draft
    // remains unsaved, but the untouched status should follow the server.
    await act(async () => {
      queryClient.setQueriesData(
        { queryKey: ["images", project.id] },
        response("server-group", "reviewed"),
      );
    });
    await waitFor(() => expect(status).toHaveValue("reviewed"));
    expect(groupKey).toHaveValue("unsaved-parent-fragment");

    // A second refresh must also preserve an unsaved status edit rather than
    // silently reclassifying the researcher's in-progress observation.
    await userEvent.selectOptions(status, "annotated");
    await act(async () => {
      queryClient.setQueriesData(
        { queryKey: ["images", project.id] },
        response("server-group-2", "excluded"),
      );
    });
    expect(groupKey).toHaveValue("unsaved-parent-fragment");
    expect(status).toHaveValue("annotated");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(
      fetchMock.mock.calls.some(([, options]) => options?.method === "PATCH"),
    ).toBe(false);
  });

  it("isolates card keyboard shortcuts from metadata and selection controls", async () => {
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
    const card = await screen.findByRole("article", {
      name: /swiftia-01\.png/,
    });
    const groupKey = screen.getByPlaceholderText("e.g. source-image-001");
    const checkbox = screen.getByLabelText("Select image");

    // Typing spaces and Enter in a scientific grouping field must not
    // toggle inference selection or unexpectedly open annotation.
    await userEvent.type(groupKey, "parent fragment 7");
    await userEvent.keyboard("{Enter}");
    expect(groupKey).toHaveValue("parent fragment 7");
    expect(checkbox).not.toBeChecked();
    expect(onOpenAnnotation).not.toHaveBeenCalled();

    // Double-clicking to select field text must not open the editor either.
    await userEvent.dblClick(groupKey);
    expect(onOpenAnnotation).not.toHaveBeenCalled();

    // The checkbox's native Space action must toggle exactly once, while
    // focusing the card itself must retain the documented shortcuts.
    checkbox.focus();
    await userEvent.keyboard(" ");
    expect(checkbox).toBeChecked();
    await userEvent.keyboard(" ");
    expect(checkbox).not.toBeChecked();

    card.focus();
    await userEvent.keyboard(" ");
    expect(checkbox).toBeChecked();
    await userEvent.keyboard("{Enter}");
    expect(onOpenAnnotation).toHaveBeenCalledTimes(1);
    expect(onOpenAnnotation).toHaveBeenCalledWith("image-1");
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

    const { queryClient } = renderGallery();
    await screen.findByText("No images yet");
    // Simulate a previous session exhausting its bounded thumbnail refreshes.
    // A new import must restart that budget on the same project/page query.
    const galleryQuery = queryClient.getQueryCache().findAll({
      queryKey: ["images", project.id],
    })[0];
    if (!galleryQuery) throw new Error("Expected a cached gallery query");
    await act(async () => {
      for (let index = 0; index < 13; index += 1) {
        queryClient.setQueryData(galleryQuery.queryKey, {
          items: [],
          total: 0,
          page: 1,
          page_size: 24,
          pages: 0,
        });
      }
    });
    expect(galleryQuery.state.dataUpdateCount).toBeGreaterThan(12);
    const file = new File(["image bytes"], "coral.JPEG", {
      type: "image/jpeg",
    });
    const fileInput = screen.getByLabelText("Import files") as HTMLInputElement;
    await userEvent.upload(fileInput, file);

    expect(await screen.findByText("1 files processed")).toBeInTheDocument();
    expect(screen.getByText("1 imported")).toBeInTheDocument();
    await waitFor(() =>
      expect(galleryQuery.state.dataUpdateCount).toBeLessThan(12),
    );
    expect(fileInput.value).toBe("");
    await userEvent.upload(fileInput, file);
    await waitFor(() => expect(importCalls).toHaveBeenCalledTimes(2));
  });

  it("reveals newly imported camera JPEGs hidden by an old filename filter", async () => {
    const cameraImage: ProjectImage = {
      ...image,
      id: "camera-2",
      original_filename: "DSC_0001.JPEG",
      managed_path: "projects/project-1/images/originals/camera-2.jpg",
      sha256: "b".repeat(64),
    };
    const persisted: ProjectImage[] = [image];
    const requestedFilters: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = new URL(String(input), "http://localhost");
      if (url.pathname.endsWith(`/projects/${project.id}/imports/images`)) {
        expect(init?.method).toBe("POST");
        persisted.push(cameraImage);
        return jsonResponse({
          project_id: project.id,
          successful: [
            {
              filename: cameraImage.original_filename,
              relative_path: cameraImage.original_filename,
              status: "successful",
              detail: null,
              image_id: cameraImage.id,
              duplicate_image_id: null,
              thumbnail_job_id: null,
            },
          ],
          duplicates: [],
          unsupported: [],
          failed: [],
        });
      }
      if (url.pathname.endsWith(`/projects/${project.id}/images`)) {
        const filename = url.searchParams.get("filename") ?? "";
        requestedFilters.push(filename);
        const items = persisted
          .filter((item) =>
            item.original_filename
              .toLowerCase()
              .includes(filename.toLowerCase()),
          )
          .reverse(); // Match the gallery API's newest-first default.
        return jsonResponse({
          items,
          total: items.length,
          page: 1,
          page_size: 24,
          pages: items.length ? 1 : 0,
        });
      }
      throw new Error(`Unhandled request ${init?.method ?? "GET"} ${url}`);
    });

    renderGallery();
    await screen.findByRole("article", { name: /swiftia-01\.png/ });
    await userEvent.type(
      screen.getByPlaceholderText("Search filenames"),
      "swiftia",
    );
    await waitFor(() => expect(requestedFilters).toContain("swiftia"));
    expect(
      screen.queryByRole("article", { name: /DSC_0001\.JPEG/ }),
    ).toBeNull();

    await userEvent.upload(
      screen.getByLabelText("Import files"),
      new File(["camera bytes"], "DSC_0001.JPEG", { type: "image/jpeg" }),
    );

    expect(
      await screen.findByRole("article", { name: /DSC_0001\.JPEG/ }),
    ).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Search filenames")).toHaveValue("");
    expect(requestedFilters.at(-1)).toBe("");
    expect(screen.getByText("1 imported")).toBeInTheDocument();
    // The older study image remains on page one; focus the confirmed import.
    expect(
      screen.getByRole("article", { name: /swiftia-01\.png/ }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getByAltText("Focused project image: DSC_0001.JPEG"),
      ).toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(
        JSON.parse(
          window.localStorage.getItem(`reefvision.gallery.${project.id}.v1`) ??
            "{}",
        ),
      ).toMatchObject({ imageId: "camera-2", page: 1 }),
    );
  });

  it.each(["duplicate", "rejected", "uncertain"] as const)(
    "preserves the focused camera observation after a %s-only import",
    async (outcome) => {
      const camera: ProjectImage = {
        ...image,
        id: "camera-2",
        original_filename: "DSC_0002.JPG",
        managed_path: "projects/project-1/images/originals/camera-2.jpg",
        sha256: "b".repeat(64),
      };
      let imageReads = 0;
      const requestedFilters: string[] = [];
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
        const url = new URL(String(input), "http://localhost");
        if (url.pathname.endsWith(`/projects/${project.id}/imports/images`)) {
          expect(init?.method).toBe("POST");
          if (outcome === "uncertain") {
            return jsonResponse({ detail: "Temporary import outage" }, 503);
          }
          return jsonResponse({
            project_id: project.id,
            successful: [],
            duplicates:
              outcome === "duplicate"
                ? [
                    {
                      filename: camera.original_filename,
                      relative_path: camera.original_filename,
                      status: "duplicate",
                      detail: "Exact file already exists in this project",
                      image_id: null,
                      duplicate_image_id: camera.id,
                      thumbnail_job_id: null,
                    },
                  ]
                : [],
            unsupported: [],
            failed:
              outcome === "rejected"
                ? [
                    {
                      filename: camera.original_filename,
                      relative_path: camera.original_filename,
                      status: "failed",
                      detail: "Corrupt camera payload",
                      image_id: null,
                      duplicate_image_id: null,
                      thumbnail_job_id: null,
                    },
                  ]
                : [],
          });
        }
        if (url.pathname.endsWith(`/projects/${project.id}/images`)) {
          imageReads += 1;
          requestedFilters.push(url.searchParams.get("filename") ?? "");
          return jsonResponse({
            items: [image, camera],
            total: 2,
            page: 1,
            page_size: 24,
            pages: 1,
          });
        }
        throw new Error(`Unhandled request ${init?.method ?? "GET"} ${url}`);
      });

      renderGallery();
      await screen.findByRole("article", { name: /DSC_0002\.JPG/ });
      await userEvent.click(
        screen.getByRole("listitem", { name: "Focus DSC_0002.JPG" }),
      );
      expect(
        screen.getByAltText("Focused project image: DSC_0002.JPG"),
      ).toBeInTheDocument();

      // The filename filter is part of the scientist's review location.
      // Failed or duplicate-only imports must not clear it.
      await userEvent.type(
        screen.getByPlaceholderText("Search filenames"),
        "DSC_0002",
      );
      await waitFor(() => expect(requestedFilters.at(-1)).toBe("DSC_0002"));

      const fileInput = screen.getByLabelText(
        "Import files",
      ) as HTMLInputElement;
      await userEvent.upload(
        fileInput,
        new File(["camera bytes"], "DSC_0002.JPG", { type: "image/jpeg" }),
      );
      if (outcome !== "uncertain") {
        await screen.findByText("1 files processed");
      } else {
        await screen.findByText("Images could not be imported");
      }
      await waitFor(() => expect(imageReads).toBeGreaterThan(1));
      await waitFor(() => expect(fileInput).not.toBeDisabled());

      // Imports with no confirmed new observations must not silently
      // switch the active scientific image or persisted review location.
      expect(screen.getByPlaceholderText("Search filenames")).toHaveValue(
        "DSC_0002",
      );
      expect(requestedFilters.at(-1)).toBe("DSC_0002");
      expect(
        screen.getByAltText("Focused project image: DSC_0002.JPG"),
      ).toBeInTheDocument();
      expect(
        JSON.parse(
          window.localStorage.getItem(`reefvision.gallery.${project.id}.v1`) ??
            "{}",
        ),
      ).toMatchObject({ imageId: camera.id, page: 1 });
    },
  );

  it("serializes camera imports across file and folder pickers", async () => {
    let resolveFirstImport!: (response: Response) => void;
    const firstImport = new Promise<Response>((resolve) => {
      resolveFirstImport = resolve;
    });
    const importedFilenames: string[] = [];
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
        const files = (init?.body as FormData).getAll("files") as File[];
        importedFilenames.push(...files.map((file) => file.name));
        if (importedFilenames.length === 1) return firstImport;
        return jsonResponse({
          project_id: project.id,
          successful: [],
          duplicates: [],
          unsupported: [],
          failed: [],
        });
      }
      throw new Error(`Unhandled request ${init?.method ?? "GET"} ${url}`);
    });

    renderGallery();
    await screen.findByText("No images yet");
    const fileInput = screen.getByLabelText("Import files") as HTMLInputElement;
    const folderInput = screen.getByLabelText(
      "Import folder",
    ) as HTMLInputElement;
    await userEvent.upload(
      fileInput,
      new File(["first"], "first.JPEG", { type: "image/jpeg" }),
    );
    await waitFor(() => expect(importedFilenames).toEqual(["first.JPEG"]));
    expect(fileInput).toBeDisabled();
    expect(folderInput).toBeDisabled();

    // Even a synthetic change event before a pending-state rerender must not
    // launch another mutation or overwrite the first import's progress.
    fireEvent.change(folderInput, {
      target: {
        files: [new File(["second"], "second.jpg", { type: "image/jpeg" })],
      },
    });
    expect(importedFilenames).toEqual(["first.JPEG"]);

    await act(async () => {
      resolveFirstImport(
        jsonResponse({
          project_id: project.id,
          successful: [],
          duplicates: [],
          unsupported: [],
          failed: [],
        }),
      );
    });
    await waitFor(() => expect(fileInput).not.toBeDisabled());
    expect(folderInput).not.toBeDisabled();
    await userEvent.upload(
      fileInput,
      new File(["second"], "second.jpg", { type: "image/jpeg" }),
    );
    await waitFor(() =>
      expect(importedFilenames).toEqual(["first.JPEG", "second.jpg"]),
    );
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
  it("keeps successfully imported camera batches visible when a later batch fails", async () => {
    const persisted: ProjectImage[] = [];
    let importRequests = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith(`/projects/${project.id}/imports/images`)) {
        importRequests += 1;
        const files = (init?.body as FormData).getAll("files") as File[];
        if (importRequests === 2) {
          return jsonResponse({ detail: "Temporary import failure" }, 503);
        }
        for (const file of files) {
          persisted.push({
            ...image,
            id: `imported-${persisted.length + 1}`,
            original_filename: file.name,
          });
        }
        return jsonResponse({
          project_id: project.id,
          successful: persisted.map((item) => ({
            filename: item.original_filename,
            relative_path: item.original_filename,
            status: "successful",
            detail: null,
            image_id: item.id,
            duplicate_image_id: null,
            thumbnail_job_id: null,
          })),
          duplicates: [],
          unsupported: [],
          failed: [],
        });
      }
      if (url.includes(`/projects/${project.id}/images`)) {
        return jsonResponse({
          items: [...persisted],
          total: persisted.length,
          page: 1,
          page_size: 24,
          pages: persisted.length ? 1 : 0,
        });
      }
      throw new Error(`Unhandled request ${init?.method ?? "GET"} ${url}`);
    });

    renderGallery();
    await screen.findByText("No images yet");
    const files = Array.from(
      { length: 11 },
      (_, index) =>
        new File(
          ["camera bytes"],
          `coral-${String(index + 1).padStart(2, "0")}.${index % 2 ? "JPEG" : "JPG"}`,
          { type: "image/jpeg" },
        ),
    );
    await userEvent.upload(screen.getByLabelText("Import files"), files);

    expect(await screen.findByText("10 files processed")).toBeInTheDocument();
    expect(
      await screen.findByText("Images could not be imported"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getAllByRole("article")).toHaveLength(10),
    );
    const importUncertainty = await screen.findByText(
      /10 of 11 files confirmed in completed batches; 1 file has an unconfirmed import outcome\./,
    );
    expect(importUncertainty).toHaveTextContent(
      "The failed batch may have reached the server.",
    );
    expect(importUncertainty).toHaveTextContent(
      "Review the gallery before retrying",
    );
    expect(importRequests).toBe(2);
    expect(
      screen.getByRole("article", { name: /coral-01\.JPG/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: /coral-11\.JPG/ })).toBeNull();
    // A failed second batch must focus the most recently confirmed JPEG,
    // not invent a successful import for the eleventh, uncertain file.
    await waitFor(() =>
      expect(
        screen.getByAltText("Focused project image: coral-10.JPEG"),
      ).toBeInTheDocument(),
    );
  });

  it("does not claim camera files were imported when the first batch has no response", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith(`/projects/${project.id}/imports/images`)) {
        return jsonResponse({ detail: "Connection interrupted" }, 503);
      }
      if (url.includes(`/projects/${project.id}/images`)) {
        return jsonResponse({
          items: [],
          total: 0,
          page: 1,
          page_size: 24,
          pages: 0,
        });
      }
      throw new Error(`Unhandled request GET ${url}`);
    });

    renderGallery();
    await screen.findByText("No images yet");
    await userEvent.upload(
      screen.getByLabelText("Import files"),
      new File(["camera bytes"], "DSC_0001.JPEG", { type: "image/jpeg" }),
    );

    expect(
      await screen.findByText("Images could not be imported"),
    ).toBeInTheDocument();
    const importUncertainty = await screen.findByText(
      /0 of 1 files confirmed in completed batches; 1 file has an unconfirmed import outcome\./,
    );
    expect(importUncertainty).toHaveTextContent(
      "The failed batch may have reached the server.",
    );
    expect(importUncertainty).toHaveTextContent(
      "Review the gallery before retrying",
    );
    expect(screen.queryByText("1 files processed")).toBeNull();
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

  it("removes stale inference selections after an image disappears on refresh", async () => {
    const onInferenceSelectionChange = vi.fn();
    const remainingImage: ProjectImage = {
      ...image,
      id: "image-2",
      original_filename: "swiftia-02.JPG",
      managed_path: "projects/project-1/images/originals/image-2.jpg",
      sha256: "b".repeat(64),
    };
    let currentItems: ProjectImage[] = [image, remainingImage];

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes(`/projects/${project.id}/images`)) {
        return jsonResponse({
          items: currentItems,
          total: currentItems.length,
          page: 1,
          page_size: 24,
          pages: 1,
        });
      }
      throw new Error(`Unhandled request GET ${url}`);
    });

    const { queryClient } = renderGallery(
      undefined,
      onInferenceSelectionChange,
    );
    await screen.findByRole("article", { name: /swiftia-01\.png/ });
    await userEvent.click(screen.getAllByLabelText("Select image")[0]);
    await waitFor(() =>
      expect(onInferenceSelectionChange).toHaveBeenLastCalledWith(["image-1"]),
    );
    expect(screen.getByText("1 selected")).toBeInTheDocument();

    // Another process can remove an image while this project stays open.
    // The gallery must not send its old ID to the model deployment controls.
    currentItems = [remainingImage];
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ["images", project.id] });
    });

    await waitFor(() => {
      expect(screen.getByText("0 selected")).toBeInTheDocument();
      expect(onInferenceSelectionChange).toHaveBeenLastCalledWith([]);
    });
    expect(
      screen.queryByRole("article", { name: /swiftia-01\.png/ }),
    ).toBeNull();
    expect(
      screen.getByRole("article", { name: /swiftia-02\.JPG/ }),
    ).toBeInTheDocument();
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

  it("restores project-specific page, focus and wrapping when switching projects", async () => {
    const otherProject: Project = {
      ...project,
      id: "project-2",
      name: "Other coral survey",
    };
    const otherImage: ProjectImage = {
      ...image,
      id: "image-other-25",
      project_id: otherProject.id,
      original_filename: "other-camera-25.JPEG",
    };
    window.localStorage.setItem(
      `reefvision.gallery.${otherProject.id}.v1`,
      JSON.stringify({ imageId: otherImage.id, page: 2, wrap: true }),
    );
    const requested: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = new URL(String(input), "http://localhost");
      const other = url.pathname.includes(
        `/projects/${otherProject.id}/images`,
      );
      const first = url.pathname.includes(`/projects/${project.id}/images`);
      if (!other && !first) throw new Error(`Unexpected request ${url}`);
      requested.push(
        `${other ? otherProject.id : project.id}:${url.searchParams.get("page")}`,
      );
      return jsonResponse({
        items: other ? [otherImage] : [image],
        total: other ? 25 : 1,
        page: other ? 2 : 1,
        page_size: 24,
        pages: other ? 2 : 1,
      });
    });
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const onFocusedImageChange = vi.fn();
    const renderFor = (selectedProject: Project) => (
      <QueryClientProvider client={queryClient}>
        <Gallery
          project={selectedProject}
          onFocusedImageChange={onFocusedImageChange}
        />
      </QueryClientProvider>
    );
    const view = render(renderFor(project));
    await screen.findByAltText("Focused project image: swiftia-01.png");
    await waitFor(() =>
      expect(onFocusedImageChange).toHaveBeenLastCalledWith("image-1"),
    );

    view.rerender(renderFor(otherProject));
    await screen.findByAltText("Focused project image: other-camera-25.JPEG");
    await waitFor(() =>
      expect(onFocusedImageChange).toHaveBeenLastCalledWith(otherImage.id),
    );
    expect(screen.getByLabelText("Wrap image navigation")).toBeChecked();
    expect(requested).toContain("project-2:2");
    expect(screen.getByLabelText("Page number")).toHaveValue(2);

    view.rerender(renderFor(project));
    await screen.findByAltText("Focused project image: swiftia-01.png");
    await waitFor(() =>
      expect(onFocusedImageChange).toHaveBeenLastCalledWith("image-1"),
    );
    expect(screen.getByLabelText("Wrap image navigation")).not.toBeChecked();
    expect(requested).toContain("project-1:1");
    expect(
      JSON.parse(
        window.localStorage.getItem(
          `reefvision.gallery.${otherProject.id}.v1`,
        ) ?? "{}",
      ),
    ).toMatchObject({ imageId: otherImage.id, page: 2, wrap: true });
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

  it("preserves modified WebView2 shortcuts and IME composition without changing the focused image", async () => {
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

    renderGallery(undefined, undefined, onFocusedImageChange);
    const viewer = await screen.findByRole("region", {
      name: "Image workbench",
    });
    await waitFor(() =>
      expect(onFocusedImageChange).toHaveBeenLastCalledWith("image-1"),
    );
    viewer.focus();

    for (const input of [
      { key: "ArrowRight", ctrlKey: true },
      { key: "ArrowRight", metaKey: true },
      { key: "ArrowRight", altKey: true },
      { key: "ArrowRight", shiftKey: true },
      { key: "Home", ctrlKey: true },
      { key: "End", metaKey: true },
      { key: "ArrowRight", isComposing: true },
      { key: "Process" },
    ]) {
      const event = new KeyboardEvent("keydown", {
        ...input,
        bubbles: true,
        cancelable: true,
      });
      fireEvent(viewer, event);
      expect(event.defaultPrevented).toBe(false);
      expect(
        screen.getByAltText("Focused project image: swiftia-01.png"),
      ).toBeInTheDocument();
    }
    expect(onFocusedImageChange).not.toHaveBeenCalledWith("image-2");

    // Ordinary, unmodified gallery navigation is still available.
    await userEvent.keyboard("{ArrowRight}");
    expect(
      await screen.findByAltText("Focused project image: swiftia-02.png"),
    ).toBeInTheDocument();
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

  it("focuses the last destination image without flashing the first on wrapped page navigation", async () => {
    const firstPage = Array.from({ length: 24 }, (_, index) => ({
      ...image,
      id: `image-${index + 1}`,
      original_filename: `swiftia-${String(index + 1).padStart(2, "0")}.png`,
    }));
    const secondPage = [25, 26].map((index) => ({
      ...image,
      id: `image-${index}`,
      original_filename: `swiftia-${index}.png`,
    }));
    const onFocusedImageChange = vi.fn();
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = new URL(String(input), "http://localhost");
      const requestedPage = Number(url.searchParams.get("page") ?? "1");
      return jsonResponse({
        items: requestedPage === 1 ? firstPage : secondPage,
        total: 26,
        page: requestedPage,
        page_size: 24,
        pages: 2,
      });
    });

    renderGallery(undefined, undefined, onFocusedImageChange);
    await screen.findByAltText("Focused project image: swiftia-01.png");
    await userEvent.click(screen.getByLabelText("Wrap image navigation"));
    const viewer = screen.getByRole("region", { name: "Image workbench" });
    viewer.focus();
    await userEvent.keyboard("{ArrowLeft}");

    expect(
      await screen.findByAltText("Focused project image: swiftia-26.png"),
    ).toBeInTheDocument();
    expect(
      screen.queryByAltText("Focused project image: swiftia-25.png"),
    ).toBeNull();
    expect(onFocusedImageChange).not.toHaveBeenCalledWith("image-25");
    await waitFor(() =>
      expect(
        JSON.parse(
          window.localStorage.getItem(`reefvision.gallery.${project.id}.v1`) ??
            "{}",
        ),
      ).toMatchObject({ imageId: "image-26", page: 2, wrap: true }),
    );
  });

  it("discards pending wrap navigation when a researcher changes gallery filters", async () => {
    const firstPage = Array.from({ length: 24 }, (_, index) => ({
      ...image,
      id: `image-${index + 1}`,
      original_filename: `swiftia-${String(index + 1).padStart(2, "0")}.png`,
    }));
    const secondPage = [25, 26].map((index) => ({
      ...image,
      id: `image-${index}`,
      original_filename: `swiftia-${index}.png`,
    }));
    let resolveSecondPage!: (response: Response) => void;
    const pendingSecondPage = new Promise<Response>((resolve) => {
      resolveSecondPage = resolve;
    });
    const onFocusedImageChange = vi.fn();
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input) => {
        const url = new URL(String(input), "http://localhost");
        if (!url.pathname.includes(`/projects/${project.id}/images`)) {
          throw new Error(`Unexpected request ${url}`);
        }
        const requestedPage = Number(url.searchParams.get("page") ?? "1");
        const filtered = Boolean(url.searchParams.get("filename"));
        if (requestedPage === 2 && !filtered) return pendingSecondPage;
        return jsonResponse({
          items: filtered ? firstPage.slice(0, 2) : firstPage,
          total: filtered ? 2 : 26,
          page: 1,
          page_size: 24,
          pages: filtered ? 1 : 2,
        });
      });

    renderGallery(undefined, undefined, onFocusedImageChange);
    await screen.findByAltText("Focused project image: swiftia-01.png");
    await userEvent.click(screen.getByLabelText("Wrap image navigation"));
    const viewer = screen.getByRole("region", { name: "Image workbench" });
    viewer.focus();
    await userEvent.keyboard("{ArrowLeft}");
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("page=2"),
        expect.any(Object),
      ),
    );
    await waitFor(() =>
      expect(
        screen.queryByAltText("Focused project image: swiftia-01.png"),
      ).toBeNull(),
    );

    // The old page-two request is still in flight. A new filter must take
    // precedence over the stale "focus last image" keyboard intent.
    fireEvent.change(screen.getByPlaceholderText("Search filenames"), {
      target: { value: "swiftia" },
    });
    expect(
      await screen.findByAltText("Focused project image: swiftia-01.png"),
    ).toBeInTheDocument();
    expect(
      screen.queryByAltText("Focused project image: swiftia-02.png"),
    ).toBeNull();
    expect(onFocusedImageChange).not.toHaveBeenCalledWith("image-2");
    resolveSecondPage(
      jsonResponse({
        items: secondPage,
        total: 26,
        page: 2,
        page_size: 24,
        pages: 2,
      }),
    );
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

  it("does not hide a successfully loaded first image on a late error event", async () => {
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
    fireEvent.load(focused);
    expect(
      screen.queryByText("Loading full-resolution image..."),
    ).not.toBeInTheDocument();

    // A late failure from a superseded WebView2 request must not replace
    // already rendered scientific pixels with an error placeholder.
    fireEvent.error(focused);
    expect(focused).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Loading full-resolution image..."),
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

  it("retries full-resolution pixels after a thumbnail fallback without changing annotations", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
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
    const thumbnail = screen.getByAltText(
      "Focused project image: swiftia-01.png",
    );
    fireEvent.load(thumbnail);
    expect(
      screen.getByText(/Full-resolution image unavailable/),
    ).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Retry full-resolution image" }),
    );
    const retried = screen.getByAltText(
      "Focused project image: swiftia-01.png",
    );
    expect(retried.getAttribute("src")).toMatch(/display/);
    expect(retried.getAttribute("src")).toContain("rv_retry=1");
    expect(
      screen.queryByText(/Full-resolution image unavailable/),
    ).not.toBeInTheDocument();

    // A second transient failure returns to the existing thumbnail rather
    // than losing the preview or creating a new image/annotation record.
    fireEvent.error(retried);
    const fallbackAgain = screen.getByAltText(
      "Focused project image: swiftia-01.png",
    );
    expect(fallbackAgain.getAttribute("src")).toMatch(/thumbnail/);
    fireEvent.load(fallbackAgain);
    await userEvent.click(
      screen.getByRole("button", { name: "Retry full-resolution image" }),
    );
    const recovered = screen.getByAltText(
      "Focused project image: swiftia-01.png",
    );
    expect(recovered.getAttribute("src")).toMatch(/display/);
    expect(recovered.getAttribute("src")).toContain("rv_retry=2");
    fireEvent.load(recovered);
    expect(
      screen.queryByText(/Full-resolution image unavailable/),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Retry full-resolution image" }),
    ).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
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

  it("reloads a replaced thumbnail and ignores its detached predecessor", async () => {
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
      jsonResponse(response("thumbnails/first.jpg")),
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
    const firstThumbnail = screen.getByAltText(
      "Focused project image: swiftia-01.png",
    );
    fireEvent.load(firstThumbnail);
    expect(
      screen.getByText(/Full-resolution image unavailable/),
    ).toBeInTheDocument();

    await act(async () => {
      queryClient.setQueriesData(
        { queryKey: ["images", project.id] },
        response("thumbnails/second.jpg"),
      );
    });

    // TanStack Query batches cache notifications. Wait for React to apply
    // the refreshed image metadata before asserting DOM node replacement.
    await waitFor(() => {
      expect(
        screen.getByAltText("Focused project image: swiftia-01.png"),
      ).not.toBe(firstThumbnail);
    });
    const secondThumbnail = screen.getByAltText(
      "Focused project image: swiftia-01.png",
    );
    expect(firstThumbnail.isConnected).toBe(false);
    expect(secondThumbnail.getAttribute("src")).toContain(
      "thumbnails%2Fsecond.jpg",
    );
    expect(
      screen.getByText("Loading thumbnail preview..."),
    ).toBeInTheDocument();

    // An old request must never hide or mark the replacement as loaded.
    fireEvent.error(firstThumbnail);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(
      screen.getByText("Loading thumbnail preview..."),
    ).toBeInTheDocument();

    fireEvent.load(secondThumbnail);
    expect(
      screen.queryByText("Loading thumbnail preview..."),
    ).not.toBeInTheDocument();
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

  it("refreshes the filmstrip thumbnail when its persisted rendition changes", async () => {
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
    const oldPath = "projects/project-1/images/thumbnails/old.jpg";
    const newPath = "projects/project-1/images/thumbnails/new.jpg";
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(response(oldPath)),
    );
    render(
      <QueryClientProvider client={queryClient}>
        <Gallery project={project} />
      </QueryClientProvider>,
    );

    const filmstrip = await screen.findByRole("list", {
      name: "Nearby images",
    });
    const thumbnail = () => filmstrip.querySelector("img");
    await waitFor(() => expect(thumbnail()).not.toBeNull());
    const first = thumbnail();
    expect(first?.getAttribute("src")).toContain(encodeURIComponent(oldPath));

    // A normal query refresh with the same path must not re-request the image.
    await act(async () => {
      queryClient.setQueriesData(
        { queryKey: ["images", project.id] },
        response(oldPath),
      );
    });
    expect(thumbnail()).toBe(first);

    // A background thumbnail replacement must bypass WebView2's cached 404
    // and detach the old image request, without changing the focused image.
    await act(async () => {
      queryClient.setQueriesData(
        { queryKey: ["images", project.id] },
        response(newPath),
      );
    });
    await waitFor(() =>
      expect(thumbnail()?.getAttribute("src")).toContain(
        encodeURIComponent(newPath),
      ),
    );
    expect(thumbnail()).not.toBe(first);
    expect(first?.isConnected).toBe(false);
    expect(
      screen.getByRole("listitem", { name: "Focus swiftia-01.png" }),
    ).toHaveAttribute("aria-current", "true");
  });

  it("keeps the first gallery image fixed under wheel input while preserving browser zoom", async () => {
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
    // Wheel events on the preview must not scroll the page while the first
    // WebView2 media request is still pending or after its load event.
    for (const loaded of [false, true]) {
      if (loaded) fireEvent.load(focused);
      const wheel = new WheelEvent("wheel", {
        deltaY: 120,
        bubbles: true,
        cancelable: true,
      });
      fireEvent(focused, wheel);
      expect(wheel.defaultPrevented).toBe(true);
    }

    for (const modifier of [{ ctrlKey: true }, { metaKey: true }]) {
      const zoom = new WheelEvent("wheel", {
        deltaY: 120,
        ...modifier,
        bubbles: true,
        cancelable: true,
      });
      fireEvent(focused, zoom);
      expect(zoom.defaultPrevented).toBe(false);
    }
  });

  it("contains malformed WebView2 wheel axes without moving the first image or filmstrip", async () => {
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
    const filmstrip = screen.getByRole("list", { name: "Nearby images" });

    // A WebView2 precision wheel may report one invalid axis, or both.
    // Neither case may escape into document scrolling or poison the strip.
    for (const target of [focused, filmstrip]) {
      for (const [deltaX, deltaY] of [
        [Number.NaN, 0],
        [Number.NaN, Number.POSITIVE_INFINITY],
      ]) {
        const malformed = new WheelEvent("wheel", {
          deltaX: 0,
          deltaY: 0,
          bubbles: true,
          cancelable: true,
        });
        Object.defineProperty(malformed, "deltaX", { value: deltaX });
        Object.defineProperty(malformed, "deltaY", { value: deltaY });
        fireEvent(target, malformed);
        expect(malformed.defaultPrevented).toBe(true);
      }

      // Genuine zero-motion wheel input remains a no-op.
      const stationary = new WheelEvent("wheel", {
        deltaX: 0,
        deltaY: 0,
        bubbles: true,
        cancelable: true,
      });
      fireEvent(target, stationary);
      expect(stationary.defaultPrevented).toBe(false);
    }
    expect(filmstrip.scrollLeft).toBe(0);
    expect(
      screen.getByRole("listitem", { name: "Focus swiftia-01.png" }),
    ).toHaveAttribute("aria-current", "true");
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

  it("contains precision-trackpad wheel gestures with a malformed companion axis", async () => {
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
      value: 1000,
    });
    Object.defineProperty(filmstrip, "clientWidth", {
      configurable: true,
      value: 200,
    });

    // Horizontal precision motion is still usable if the vertical axis is
    // non-finite. Previously the NaN comparison discarded the entire wheel
    // event and let WebView2 scroll the page instead.
    const horizontal = new WheelEvent("wheel", {
      deltaX: 75,
      bubbles: true,
      cancelable: true,
    });
    Object.defineProperty(horizontal, "deltaY", { value: Number.NaN });
    fireEvent(filmstrip, horizontal);
    expect(horizontal.defaultPrevented).toBe(true);
    expect(filmstrip.scrollLeft).toBe(75);

    const vertical = new WheelEvent("wheel", {
      deltaY: -25,
      bubbles: true,
      cancelable: true,
    });
    Object.defineProperty(vertical, "deltaX", {
      value: Number.POSITIVE_INFINITY,
    });
    fireEvent(filmstrip, vertical);
    expect(vertical.defaultPrevented).toBe(true);
    expect(filmstrip.scrollLeft).toBe(50);

    // Valid diagonal gestures still prefer their dominant axis.
    const diagonal = new WheelEvent("wheel", {
      deltaX: 30,
      deltaY: 7,
      bubbles: true,
      cancelable: true,
    });
    fireEvent(filmstrip, diagonal);
    expect(diagonal.defaultPrevented).toBe(true);
    expect(filmstrip.scrollLeft).toBe(80);

    // Do not interfere with native Ctrl+wheel zoom, even with bad input.
    const zoom = new WheelEvent("wheel", {
      deltaX: 100,
      ctrlKey: true,
      bubbles: true,
      cancelable: true,
    });
    Object.defineProperty(zoom, "deltaY", { value: Number.NaN });
    fireEvent(filmstrip, zoom);
    expect(zoom.defaultPrevented).toBe(false);
    expect(filmstrip.scrollLeft).toBe(80);
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

  it("normalizes Windows line and page wheel units without moving the document", async () => {
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
      value: 1000,
    });
    Object.defineProperty(filmstrip, "clientWidth", {
      configurable: true,
      value: 200,
    });

    const lineWheel = new WheelEvent("wheel", {
      deltaY: 3,
      deltaMode: 1,
      bubbles: true,
      cancelable: true,
    });
    fireEvent(filmstrip, lineWheel);
    expect(lineWheel.defaultPrevented).toBe(true);
    expect(filmstrip.scrollLeft).toBe(48);

    const pageWheel = new WheelEvent("wheel", {
      deltaY: 1,
      deltaMode: 2,
      bubbles: true,
      cancelable: true,
    });
    fireEvent(filmstrip, pageWheel);
    expect(pageWheel.defaultPrevented).toBe(true);
    expect(filmstrip.scrollLeft).toBe(248);
  });

  it("contains filmstrip wheels through collapsed and invalid WebView2 layout", async () => {
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
    Object.defineProperty(filmstrip, "clientWidth", {
      configurable: true,
      value: 200,
    });
    Object.defineProperty(filmstrip, "scrollWidth", {
      configurable: true,
      value: Number.NaN,
    });
    filmstrip.scrollLeft = 37;
    const collapsed = new WheelEvent("wheel", {
      deltaY: 75,
      bubbles: true,
      cancelable: true,
    });
    fireEvent(filmstrip, collapsed);
    expect(collapsed.defaultPrevented).toBe(true);
    expect(filmstrip.scrollLeft).toBe(37);

    // When WebView2 restores valid measurements, scrolling resumes. A stale
    // nonfinite scroll offset must not be propagated into the next gesture.
    Object.defineProperty(filmstrip, "scrollWidth", {
      configurable: true,
      value: 1000,
    });
    filmstrip.scrollLeft = Number.NaN;
    const recovered = new WheelEvent("wheel", {
      deltaY: 25,
      bubbles: true,
      cancelable: true,
    });
    fireEvent(filmstrip, recovered);
    expect(recovered.defaultPrevented).toBe(true);
    expect(filmstrip.scrollLeft).toBe(25);

    // An overflowing wheel product also resolves to a finite scroll edge.
    const huge = new WheelEvent("wheel", {
      deltaY: Number.MAX_VALUE,
      deltaMode: 1,
      bubbles: true,
      cancelable: true,
    });
    fireEvent(filmstrip, huge);
    expect(huge.defaultPrevented).toBe(true);
    expect(filmstrip.scrollLeft).toBe(800);
  });

  it.each([
    "constructor",
    "observe-strip",
    "observe-thumbnail",
    "disconnect",
  ] as const)(
    "keeps filmstrip focus and scrolling usable when WebView2 observer %s throws",
    async (failure) => {
      class BrokenResizeObserver {
        constructor(_callback: ResizeObserverCallback) {
          if (failure === "constructor") {
            throw new Error("Observer constructor unavailable");
          }
        }

        observe(target: Element) {
          if (
            (failure === "observe-strip" &&
              target.classList.contains("rv-media-filmstrip")) ||
            (failure === "observe-thumbnail" &&
              target.matches('button[aria-current="true"]'))
          ) {
            throw new Error("Observer registration unavailable");
          }
        }

        disconnect() {
          if (failure === "disconnect") {
            throw new Error("Observer cleanup unavailable");
          }
        }
      }

      vi.stubGlobal("ResizeObserver", BrokenResizeObserver);
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

      try {
        const { unmount } = renderGallery();
        const filmstrip = await screen.findByRole("list", {
          name: "Nearby images",
        });
        const second = screen.getByRole("listitem", {
          name: "Focus swiftia-02.png",
        });
        const stripRect = { left: Number.NaN, right: 400 };
        vi.spyOn(filmstrip, "getBoundingClientRect").mockImplementation(
          () => stripRect as DOMRect,
        );
        vi.spyOn(second, "getBoundingClientRect").mockReturnValue({
          left: 450,
          right: 550,
        } as DOMRect);

        await userEvent.click(second);
        expect(second).toHaveAttribute("aria-current", "true");
        stripRect.left = 100;
        fireEvent.resize(window);
        await waitFor(() => expect(filmstrip.scrollLeft).toBe(150));
        expect(
          screen.getByAltText("Focused project image: swiftia-02.png"),
        ).toBeInTheDocument();
        expect(() => unmount()).not.toThrow();
      } finally {
        vi.unstubAllGlobals();
      }
    },
  );

  it("re-aligns the focused thumbnail after a server-side reorder without changing scientific focus", async () => {
    const secondImage: ProjectImage = {
      ...image,
      id: "image-2",
      original_filename: "swiftia-02.png",
    };
    const response = (items: ProjectImage[]) => ({
      items,
      total: 2,
      page: 1,
      page_size: 24,
      pages: 1,
    });
    const onFocusedImageChange = vi.fn();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(response([image, secondImage])),
    );
    const { queryClient } = renderGallery(
      undefined,
      undefined,
      onFocusedImageChange,
    );
    const filmstrip = await screen.findByRole("list", {
      name: "Nearby images",
    });
    const second = screen.getByRole("listitem", {
      name: "Focus swiftia-02.png",
    });
    vi.spyOn(filmstrip, "getBoundingClientRect").mockReturnValue({
      left: 100,
      right: 400,
    } as DOMRect);
    let thumbnailLeft = 200;
    vi.spyOn(second, "getBoundingClientRect").mockImplementation(
      () =>
        ({
          left: thumbnailLeft,
          right: thumbnailLeft + 70,
        }) as DOMRect,
    );

    await userEvent.click(second);
    expect(filmstrip.scrollLeft).toBe(0);
    expect(second).toHaveAttribute("aria-current", "true");

    // Sorting or a concurrent annotation update can reorder thumbnails while
    // the selected scientific image stays unchanged. No resize event occurs.
    thumbnailLeft = 425;
    await act(async () => {
      queryClient.setQueriesData(
        { queryKey: ["images", project.id] },
        response([secondImage, image]),
      );
    });
    await waitFor(() => expect(filmstrip.scrollLeft).toBe(95));
    expect(second).toHaveAttribute("aria-current", "true");
    expect(
      screen.getByAltText("Focused project image: swiftia-02.png"),
    ).toBeInTheDocument();
    expect(onFocusedImageChange).toHaveBeenLastCalledWith("image-2");
  });

  it("defers active-image alignment until collapsed pane geometry recovers", async () => {
    const nextImage: ProjectImage = {
      ...image,
      id: "image-2",
      original_filename: "swiftia-02.png",
    };
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        items: [image, nextImage],
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
    const second = screen.getByRole("listitem", {
      name: "Focus swiftia-02.png",
    });
    const stripRect = { left: Number.NaN, right: 400 };
    vi.spyOn(filmstrip, "getBoundingClientRect").mockImplementation(
      () => stripRect as DOMRect,
    );
    vi.spyOn(second, "getBoundingClientRect").mockReturnValue({
      left: 450,
      right: 550,
    } as DOMRect);

    await userEvent.click(second);
    expect(filmstrip.scrollLeft).toBe(0);
    expect(second).toHaveAttribute("aria-current", "true");

    stripRect.left = 100;
    window.dispatchEvent(new Event("resize"));
    await waitFor(() => expect(filmstrip.scrollLeft).toBe(150));
    expect(
      screen.getByAltText("Focused project image: swiftia-02.png"),
    ).toBeInTheDocument();
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
