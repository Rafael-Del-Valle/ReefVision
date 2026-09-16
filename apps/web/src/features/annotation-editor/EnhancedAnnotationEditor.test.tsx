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
    <div data-testid="box-workspace">
      <aside className="annotation-tool-rail" aria-label="Annotation tools" />
      {initialImageId}
    </div>
  ),
}));

vi.mock("./MaskAnnotationWorkspace", () => ({
  MaskAnnotationWorkspace: ({
    imageId,
    initialTool,
    onOpenBrush,
    onReturnToBoxes,
  }: {
    imageId: string;
    initialTool?: string;
    onOpenBrush: () => void;
    onReturnToBoxes: () => void;
  }) => (
    <div data-testid="mask-workspace">
      <aside className="annotation-tool-rail" aria-label="Annotation tools" />
      <span data-testid="mask-initial-tool">{initialTool ?? "none"}</span>
      <button
        data-testid="activate-mask-brush-tool"
        data-mask-workspace-destination="raster"
        onClick={onOpenBrush}
      >
        Brush
      </button>
      <button data-testid="activate-polygon-tool">Polygon</button>
      <button data-testid="activate-polygon-fill-tool">Fill object</button>
      <button data-testid="activate-smart-close-tool">Smart Close</button>
      <button data-mask-workspace-destination="boxes" onClick={onReturnToBoxes}>
        Boxes
      </button>
      <button
        type="button"
        className="active"
        data-testid="activate-mask-select-tool"
      >
        Select vertices
      </button>
      <p className="annotation-helper">
        Add polygon vertices, then press Enter or click the first vertex to
        close.
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
        <image data-testid="polygon-raster-overlay" data-mask-id="raster-1" />
        <text>{imageId}</text>
      </svg>
    </div>
  ),
}));

vi.mock("./RasterMaskWorkspace", () => ({
  RasterMaskWorkspace: ({ imageId }: { imageId: string }) => (
    <div data-testid="raster-workspace">
      <aside className="annotation-tool-rail" aria-label="Annotation tools" />
      {imageId}
    </div>
  ),
}));

import { EnhancedAnnotationEditor } from "./EnhancedAnnotationEditor";

it("does not intercept Fill clicks when a previous node insertion mode is remembered", () => {
  renderEditor();
  fireEvent.click(screen.getByTestId("open-polygon-tool"));
  fireEvent.click(screen.getByTestId("insert-polygon-node"));
  screen.getByTestId("activate-mask-select-tool").classList.remove("active");
  fireEvent.pointerDown(screen.getByTestId("editable-polygon"), {
    clientX: 20,
    clientY: 20,
  });
  expect(polygonInsertHandler).not.toHaveBeenCalled();
});

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

  it("opens rotated boxes as a dedicated annotation tool", async () => {
    renderEditor();

    fireEvent.click(screen.getByTestId("open-rotated-box-tool"));

    expect(await screen.findByTestId("mask-initial-tool")).toHaveTextContent(
      "rotated_box",
    );
    expect(screen.getByTestId("open-rotated-box-tool")).toHaveClass("active");
  });

  it("opens Fill object directly and keeps Fill visibly active", () => {
    renderEditor();

    fireEvent.click(screen.getByTestId("open-fill-object-tool"));

    expect(screen.getByTestId("mask-workspace")).toBeInTheDocument();
    expect(screen.getByTestId("mask-initial-tool")).toHaveTextContent("fill");
    expect(screen.getByTestId("enhanced-annotation-editor")).toHaveAttribute(
      "data-active-annotation-type",
      "masks",
    );
    expect(screen.getByTestId("open-fill-object-tool")).toHaveClass("active");
    expect(screen.getByTestId("open-polygon-tool")).not.toHaveClass("active");
  });

  it("opens Smart Close as a separate active mask tool", () => {
    renderEditor();

    fireEvent.click(screen.getByTestId("open-smart-close-tool"));

    expect(screen.getByTestId("mask-workspace")).toBeInTheDocument();
    expect(screen.getByTestId("mask-initial-tool")).toHaveTextContent(
      "smart_close",
    );
    expect(screen.getByTestId("open-smart-close-tool")).toHaveClass("active");
    expect(screen.getByTestId("open-fill-object-tool")).not.toHaveClass(
      "active",
    );
    expect(screen.getByTestId("open-polygon-tool")).not.toHaveClass("active");
  });

  it("uses the left tool rail to switch annotation workspaces", async () => {
    const { queryClient, project } = renderEditor();
    const editor = screen.getByTestId("enhanced-annotation-editor");

    expect(screen.getByTestId("box-workspace")).toHaveTextContent("image-1");
    expect(editor).toHaveAttribute("data-active-annotation-type", "boxes");
    expect(editor).toHaveAttribute("data-boxes-visible", "true");
    expect(editor).toHaveAttribute("data-polygons-visible", "false");
    expect(editor).toHaveAttribute("data-raster-visible", "false");
    expect(screen.getByTestId("open-polygon-tool")).toBeInTheDocument();
    expect(screen.getByTestId("open-fill-object-tool")).toBeInTheDocument();
    expect(screen.getByTestId("open-smart-close-tool")).toBeInTheDocument();
    expect(screen.getByTestId("open-brush-tool")).toBeInTheDocument();
    expect(screen.getByTestId("mask-tool-group")).toBeInTheDocument();

    act(() => {
      queryClient.setQueryData(["annotation-session", "image-2"], {
        image: { id: "image-2", project_id: project.id },
      });
    });

    await waitFor(() => {
      expect(screen.getByTestId("box-workspace")).toHaveTextContent("image-2");
    });

    fireEvent.click(screen.getByTestId("open-polygon-tool"));
    expect(screen.getByTestId("polygon-mask-layer")).toHaveTextContent(
      "image-2",
    );
    expect(editor).toHaveAttribute("data-active-annotation-type", "masks");
    expect(editor).toHaveAttribute("data-boxes-visible", "false");
    expect(editor).toHaveAttribute("data-polygons-visible", "true");
    expect(editor).toHaveAttribute("data-raster-visible", "false");
    expect(screen.getByTestId("return-main-tools")).toBeInTheDocument();
    expect(screen.getByTestId("polygon-edit-tool-group")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("open-brush-tool"));
    expect(screen.getByTestId("raster-workspace")).toHaveTextContent("image-2");
    expect(editor).toHaveAttribute("data-active-annotation-type", "raster");
    expect(editor).toHaveAttribute("data-boxes-visible", "false");
    expect(editor).toHaveAttribute("data-polygons-visible", "false");
    expect(editor).toHaveAttribute("data-raster-visible", "true");

    fireEvent.click(screen.getByTestId("return-main-tools"));
    expect(screen.getByTestId("box-workspace")).toHaveTextContent("image-2");
    expect(editor).toHaveAttribute("data-active-annotation-type", "boxes");
  });

  it("requires clicking the first polygon node instead of pressing Enter", () => {
    renderEditor();
    fireEvent.click(screen.getByTestId("open-polygon-tool"));

    fireEvent.keyDown(screen.getByTestId("polygon-mask-layer"), {
      key: "Enter",
    });

    expect(polygonKeyHandler).not.toHaveBeenCalled();
  });

  it("inserts and deletes individual polygon nodes through visible modes", () => {
    renderEditor();
    fireEvent.click(screen.getByTestId("open-polygon-tool"));

    const editor = screen.getByTestId("enhanced-annotation-editor");
    expect(editor).toHaveAttribute("data-vertex-edit-mode", "move");

    fireEvent.click(screen.getByTestId("insert-polygon-node"));
    expect(editor).toHaveAttribute("data-vertex-edit-mode", "insert");
    fireEvent.pointerDown(screen.getByTestId("editable-polygon"), {
      clientX: 30,
      clientY: 10,
    });
    expect(polygonInsertHandler).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId("delete-polygon-node"));
    expect(editor).toHaveAttribute("data-vertex-edit-mode", "delete");
    fireEvent.pointerDown(screen.getByTestId("mask-vertex-mask-1-0"));
    expect(vertexPointerHandler).toHaveBeenCalledTimes(1);
    expect(vertexPointerHandler.mock.calls[0][0].altKey).toBe(true);
  });

  it("keeps whole-polygon removal explicit", () => {
    renderEditor();
    fireEvent.click(screen.getByTestId("open-polygon-tool"));

    fireEvent.keyDown(screen.getByTestId("polygon-mask-layer"), {
      key: "Delete",
    });
    fireEvent.keyDown(screen.getByTestId("polygon-mask-layer"), {
      key: "Backspace",
    });

    expect(polygonKeyHandler).not.toHaveBeenCalled();
  });
});
