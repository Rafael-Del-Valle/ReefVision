import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Project } from "../../api/client";

vi.mock("./AnnotationEditor", () => ({
  AnnotationEditor: ({ initialImageId }: { initialImageId: string }) => (
    <div data-testid="box-workspace">{initialImageId}</div>
  ),
}));

vi.mock("./MaskAnnotationWorkspace", () => ({
  MaskAnnotationWorkspace: ({ imageId }: { imageId: string }) => (
    <div data-testid="mask-workspace">{imageId}</div>
  ),
}));

vi.mock("./RasterMaskWorkspace", () => ({
  RasterMaskWorkspace: ({ imageId }: { imageId: string }) => (
    <div data-testid="raster-workspace">{imageId}</div>
  ),
}));

import { EnhancedAnnotationEditor } from "./EnhancedAnnotationEditor";

describe("EnhancedAnnotationEditor", () => {
  it("toggles annotation types on the most recently loaded image", async () => {
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
    expect(screen.getByTestId("mask-workspace")).toHaveTextContent("image-2");

    fireEvent.change(screen.getByLabelText("Annotation type"), {
      target: { value: "raster" },
    });
    expect(screen.getByTestId("raster-workspace")).toHaveTextContent("image-2");
  });
});
