import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CatalogInferenceLauncher } from "./CatalogInferenceLauncher";

vi.mock("../../runtime", () => ({
  getApiBaseUrl: () => "http://reefvision.test/api/v1",
}));

function response(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function mountEditorTarget() {
  const actions = document.createElement("div");
  actions.className = "annotation-editor-actions";
  const topbar = document.createElement("div");
  topbar.className = "annotation-editor-topbar";
  topbar.append(actions);
  document.body.append(topbar);

  const canvas = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  canvas.classList.add("annotation-canvas");
  const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
  const image = document.createElementNS("http://www.w3.org/2000/svg", "image");
  image.setAttribute(
    "href",
    "http://reefvision.test/api/v1/images/image-1/content",
  );
  group.append(image);
  canvas.append(group);
  document.body.append(canvas);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("CatalogInferenceLauncher", () => {
  it("loads a Ready model and queues a text-prompt detection job", async () => {
    mountEditorTarget();
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        requests.push({ url, init });
        if (url.endsWith("/images/image-1/annotations")) {
          return response({
            image: { id: "image-1", project_id: "project-1" },
          });
        }
        if (url.includes("/projects/project-1/model-catalog")) {
          return response({
            models: [
              {
                catalog_id: "transformers/grounding_dino/tiny",
                display_name: "Grounding DINO Tiny",
                provider_id: "grounding_dino",
                installation_state: "Ready",
                installation_reason: null,
                recommended_vram: 4,
              },
            ],
          });
        }
        if (url.endsWith("/projects/project-1/catalog-inference-jobs")) {
          return response({
            id: "job-1",
            status: "queued",
            error_message: null,
            progress_current: 0,
            progress_total: 1,
            result_json: null,
          });
        }
        if (url.endsWith("/jobs/job-1")) {
          return response({
            id: "job-1",
            status: "succeeded",
            error_message: null,
            progress_current: 1,
            progress_total: 1,
            result_json: { proposal_count: 2 },
          });
        }
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <CatalogInferenceLauncher />
      </QueryClientProvider>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Text detect" }));
    expect(
      await screen.findByRole("option", { name: /Grounding DINO Tiny/ }),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Objects to find"), {
      target: { value: "coral polyp, fish" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Find objects" }));

    await screen.findByText(
      "Detection complete: 2 proposals added for review.",
    );
    const createRequest = requests.find((item) =>
      item.url.endsWith("/projects/project-1/catalog-inference-jobs"),
    );
    expect(createRequest?.init?.method).toBe("POST");
    expect(JSON.parse(String(createRequest?.init?.body))).toMatchObject({
      catalog_id: "transformers/grounding_dino/tiny",
      image_ids: ["image-1"],
      text_prompt: "coral polyp, fish",
      device: "auto",
    });
    await waitFor(() => {
      expect(requests.some((item) => item.url.endsWith("/jobs/job-1"))).toBe(
        true,
      );
    });
  });
});
