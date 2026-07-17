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

const { polygonKeyHandler, polygonInsertHandler, vertexPointerHandler } =
  vi.hoisted(() => ({
    polygonKeyHandler: vi.fn(),
    polygonInsertHandler: vi.fn(),
    vertexPointerHandler: vi.fn(),
  }));

vi.mock("./AnnotationEditor", () => ({
  AnnotationEditor: ({ initialImageId }: { initialImageId: string }) => (
    <div data-testid="box-workspace">{initialImageId}</div>
  ),
}));

vi.mock("./MaskAnnotationWorkspace", () => ({
  MaskAnnotationWorkspace: ({ imageId }: { imageId: string }) => (
    <div data-testid="mask-workspace">
      <button
        type="button"
        className="active"
        data-testid="activate-mask-select-tool"
      >
        Select vertices
      </button>
      <p className="annotation-helper">
        Add polygon vertices, then press Enter or click the first vertex to close.
      </p>
      <svg
        data-testid="polygon-mask-layer"
        tabIndex={0}
        onKeyDown={polygonKeyHandler}
      >
        <polygon
          data-testid="editable-polygon"
          points="10,10 50,10 50,50"
          onDoubleClick={polygonInsertHandler}
        />
        <circle
          data-testid="mask-vertex-mask-1-0"
          cx="10"
          cy="10"
          r="5"
          onPointerDown={vertexPointerHandler}
        />
        <text>{imageId}</text>
      </svg>
    </div>
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
    polygonKeyHandler.mockClear();
    polygonInsertHandler.mockClear();
    vertexPointerHandler.mockClear();
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

    expect(polygonKeyHandler).not.toHaveBeenCalled();
  });

  it("inserts and deletes individual polygon nodes through visible modes", () => {
    renderEditor();
    fireEvent.change(screen.getByLabelText("Annotation type"), {
      target: { value: "masks" },
    });

    const editor = screen.getByTestId("enhanced-annotation-editor");
    expect(editor).toHaveAttribute("data-vertex-edit-mode", "move");

    fireEvent.click(screen.getByRole("button", { name: "Insert node" }));
    expect(editor).toHaveAttribute("data-vertex-edit-mode", "insert");
    fireEvent.pointerDown(screen.getByTestId("editable-polygon"), {
      clientX: 30,
      clientY: 10,
    });
    expect(polygonInsertHandler).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Delete node" }));
    expect(editor).toHaveAttribute("data-vertex-edit-mode", "delete");
    fireEvent.pointerDown(screen.getByTestId("mask-vertex-mask-1-0"));
    expect(vertexPointerHandler).toHaveBeenCalledTimes(1);
    expect(vertexPointerHandler.mock.calls[0][0].altKey).toBe(true);
  });

  it("keeps whole-polygon deletion explicit", () => {
    renderEditor();
    fireEvent.change(screen.getByLabelText("Annotation type"), {
      target: { value: "masks" },
    });

    fireEvent.keyDown(screen.getByTestId("polygon-mask-layer"), {
      key: "Delete",
    });
    fireEvent.keyDown(screen.getByTestId("polygon-mask-layer"), {
      key: "Backspace",
    });

    expect(polygonKeyHandler).not.toHaveBeenCalled();
  });
});
