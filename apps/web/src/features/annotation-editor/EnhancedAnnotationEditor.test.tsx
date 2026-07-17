import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Project } from "../../api/client";

const { polygonEnterHandler } = vi.hoisted(() => ({
  polygonEnterHandler: vi.fn(),
}));

vi.mock("./AnnotationEditor", () => ({
  AnnotationEditor: ({ initialImageId }: { initialImageId: string }) => (
    <div data-testid="box-workspace">{initialImageId}</div>
  ),
}));

vi.mock("./MaskAnnotationWorkspace", () => ({
  MaskAnnotationWorkspace: ({ imageId }: { imageId: string }) => (
    <svg
      data-testid="polygon-mask-layer"
      tabIndex={0}
      onKeyDown={polygonEnterHandler}
    >
      <text>{imageId}</text>
    </svg>
  ),
}));

vi.mock("./RasterMaskWorkspace", () => ({
  RasterMaskWorkspace: ({ imageId }: { imageId: string }) => (
    <div data-testid="raster-workspace">{imageId}</div>
  ),
}));

import { EnhancedAnnotationEditor } from "./EnhancedAnnotationEditor";

function renderEditor() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const project = { id: "project-1" } as Project;

  render(
    <QueryClientProvider client={queryClient}>
      <EnhancedAnnotationEditor
        project={project}
        initialImageId="image-1"
        onClose={vi.fn()}
      />
    </QueryClientProvider>,
  );

  return { queryClient, project };
}

describe("EnhancedAnnotationEditor", () => {
  beforeEach(() => {
    polygonEnterHandler.mockClear();
  });

  it("toggles annotation types on the most recently loaded image", async () => {
    const { queryClient, project } = renderEditor();

    expect(screen.getByTestId("box-workspace")).toHaveTextContent("image-1");
    expect(
      screen.queryByRole("button", { name: "Polygon tool" }),
    ).not.toBeInTheDocument();

    const annotationType = screen.getByLabelText("Annotation type");
    expect(annotationType).toHaveValue("boxes");

    act(() => {
      queryClient.setQueryData(["annotation-session", "image-2"], {
        image: { id: "image-2", project_id: project.id },
      });
    });

    await waitFor(() => {
      expect(screen.getByTestId("box-workspace")).toHaveTextContent("image-2");
    });

    fireEvent.change(annotationType, { target: { value: "masks" } });
    expect(screen.getByTestId("polygon-mask-layer")).toHaveTextContent(
      "image-2",
    );

    fireEvent.change(screen.getByLabelText("Annotation type"), {
      target: { value: "raster" },
    });
    expect(screen.getByTestId("raster-workspace")).toHaveTextContent("image-2");
  });

  it("hides each annotation geometry independently", () => {
    renderEditor();
    const editor = screen.getByTestId("enhanced-annotation-editor");

    expect(editor).toHaveAttribute("data-boxes-visible", "true");
    expect(editor).toHaveAttribute("data-polygons-visible", "true");
    expect(editor).toHaveAttribute("data-raster-visible", "true");

    fireEvent.click(screen.getByLabelText("Boxes"));
    fireEvent.click(screen.getByLabelText("Polygons"));
    fireEvent.click(screen.getByLabelText("Raster masks"));

    expect(editor).toHaveAttribute("data-boxes-visible", "false");
    expect(editor).toHaveAttribute("data-polygons-visible", "false");
    expect(editor).toHaveAttribute("data-raster-visible", "false");
  });

  it("requires clicking the first polygon node instead of pressing Enter", () => {
    renderEditor();
    fireEvent.change(screen.getByLabelText("Annotation type"), {
      target: { value: "masks" },
    });

    fireEvent.keyDown(screen.getByTestId("polygon-mask-layer"), {
      key: "Enter",
    });

    expect(polygonEnterHandler).not.toHaveBeenCalled();
  });
});
