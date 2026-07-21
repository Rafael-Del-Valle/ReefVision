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
  AnnotationEditor: ({
    initialImageId,
    onMaskPredictionAccepted,
  }: {
    initialImageId: string;
    onMaskPredictionAccepted?: (kind: "polygon" | "raster_mask") => void;
  }) => (
    <div data-testid="box-workspace">
      {initialImageId}
      <button
        type="button"
        onClick={() => onMaskPredictionAccepted?.("polygon")}
      >
        Accept polygon prediction fixture
      </button>
      <button
        type="button"
        onClick={() => onMaskPredictionAccepted?.("raster_mask")}
      >
        Accept raster prediction fixture
      </button>
    </div>
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
      {imageId}
      <img alt="Accepted raster mask fixture" />
    </div>
  ),
}));

vi.mock("./PromptPointAssistOverlay", () => ({
  PromptPointAssistOverlay: ({
    activeWorkspace,
    onAccepted,
  }: {
    activeWorkspace: "boxes" | "masks" | "raster";
    onAccepted: (kind: "raster_mask" | "polygon") => void;
  }) => (
    <div data-testid="prompt-point-assist">
      <span>{activeWorkspace}</span>
      <button type="button" onClick={() => onAccepted("polygon")}>
        Accept polygon fixture
      </button>
    </div>
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

  it("uses annotation type as the exclusive workspace and overlay filter", async () => {
    const { queryClient, project } = renderEditor();
    const editor = screen.getByTestId("enhanced-annotation-editor");

    expect(screen.getByTestId("box-workspace")).toHaveTextContent("image-1");
    expect(
      screen.queryByRole("button", { name: "Polygon tool" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("group", { name: "Visible annotation types" }),
    ).not.toBeInTheDocument();

    const annotationType = screen.getByLabelText("Annotation type");
    expect(annotationType).toHaveValue("boxes");
    expect(editor).toHaveAttribute("data-active-annotation-type", "boxes");
    expect(editor).toHaveAttribute("data-boxes-visible", "true");
    expect(editor).toHaveAttribute("data-polygons-visible", "false");
    expect(editor).toHaveAttribute("data-raster-visible", "false");

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
    expect(editor).toHaveAttribute("data-active-annotation-type", "masks");
    expect(editor).toHaveAttribute("data-boxes-visible", "false");
    expect(editor).toHaveAttribute("data-polygons-visible", "true");
    expect(editor).toHaveAttribute("data-raster-visible", "false");

    fireEvent.change(screen.getByLabelText("Annotation type"), {
      target: { value: "raster" },
    });
    expect(screen.getByTestId("raster-workspace")).toHaveTextContent("image-2");
    expect(editor).toHaveAttribute("data-active-annotation-type", "raster");
    expect(editor).toHaveAttribute("data-boxes-visible", "false");
    expect(editor).toHaveAttribute("data-polygons-visible", "false");
    expect(editor).toHaveAttribute("data-raster-visible", "true");
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

  it("locks polygon node tools while point assist owns canvas input", () => {
    renderEditor();
    fireEvent.change(screen.getByLabelText("Annotation type"), {
      target: { value: "masks" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Insert node" }));
    fireEvent.pointerDown(screen.getByTestId("editable-polygon"), {
      clientX: 30,
      clientY: 10,
    });
    expect(polygonInsertHandler).toHaveBeenCalledTimes(1);
    polygonInsertHandler.mockClear();

    fireEvent.click(screen.getByTestId("toggle-point-assist"));
    expect(screen.getByRole("button", { name: "Move nodes" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Insert node" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Delete node" })).toBeDisabled();

    fireEvent.pointerDown(screen.getByTestId("editable-polygon"), {
      clientX: 30,
      clientY: 10,
    });
    expect(polygonInsertHandler).not.toHaveBeenCalled();
  });

  it("closes point assist and switches workspace after accepting output", () => {
    renderEditor();
    const editor = screen.getByTestId("enhanced-annotation-editor");
    fireEvent.click(screen.getByTestId("toggle-point-assist"));
    expect(screen.getByTestId("prompt-point-assist")).toHaveTextContent(
      "boxes",
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Accept polygon fixture" }),
    );

    expect(screen.queryByTestId("prompt-point-assist")).not.toBeInTheDocument();
    expect(screen.getByTestId("mask-workspace")).toBeInTheDocument();
    expect(editor).toHaveAttribute("data-active-annotation-type", "masks");
    expect(editor).toHaveAttribute("data-point-assist-enabled", "false");
  });

  it("opens the editable polygon workspace after accepting a polygon prediction", () => {
    renderEditor();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Accept polygon prediction fixture",
      }),
    );

    expect(screen.getByTestId("mask-workspace")).toBeInTheDocument();
    expect(screen.getByTestId("editable-polygon")).toBeInTheDocument();
    expect(screen.getByTestId("enhanced-annotation-editor")).toHaveAttribute(
      "data-active-annotation-type",
      "masks",
    );
  });

  it("opens the editable raster workspace after accepting a raster prediction", () => {
    renderEditor();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Accept raster prediction fixture",
      }),
    );

    expect(screen.getByTestId("raster-workspace")).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "Accepted raster mask fixture" }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("enhanced-annotation-editor")).toHaveAttribute(
      "data-active-annotation-type",
      "raster",
    );
  });

  it("keeps whole-polygon removal explicit", () => {
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
