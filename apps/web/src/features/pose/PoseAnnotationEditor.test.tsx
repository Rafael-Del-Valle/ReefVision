import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PoseAnnotationEditor } from "./PoseAnnotationEditor";
import type {
  PoseInstance,
  PoseLandmarkSchema,
  PoseSaveRequest,
} from "./types";

const schema: PoseLandmarkSchema = {
  id: "jellyfish-schema",
  revision: 3,
  groups: [
    { name: "bell_center", count: 1 },
    { name: "tentacle", count: 8 },
  ],
  edges: [{ from: "bell_center", to: "tentacle" }],
};

const poseA: PoseInstance = {
  id: "pose-a",
  revision: 4,
  schema_id: schema.id,
  schema_revision: schema.revision,
  observations: [
    {
      id: "bell-a",
      semantic_label: "bell_center",
      occurrence_index: 0,
      x: 450,
      y: 300,
      confidence: null,
      source: "manual",
    },
  ],
};

const poseB: PoseInstance = {
  id: "pose-b",
  revision: 7,
  schema_id: schema.id,
  schema_revision: schema.revision,
  observations: [
    {
      id: "bell-b",
      semantic_label: "bell_center",
      occurrence_index: 0,
      x: 300,
      y: 250,
      confidence: null,
      source: "manual",
    },
  ],
};

function installStageBounds(): SVGSVGElement {
  const stage = screen.getByTestId("pose-stage") as unknown as SVGSVGElement;
  Object.defineProperty(stage, "getBoundingClientRect", {
    configurable: true,
    value: () => ({
      x: 0,
      y: 0,
      left: 0,
      top: 0,
      right: 900,
      bottom: 600,
      width: 900,
      height: 600,
      toJSON: () => ({}),
    }),
  });
  return stage;
}

function savedPose(
  request: PoseSaveRequest,
  revision = request.base_revision + 1,
): PoseInstance {
  return {
    id: request.pose_id,
    revision,
    schema_id: request.schema_id,
    schema_revision: request.schema_revision,
    observations: request.observations,
  };
}

describe("PoseAnnotationEditor", () => {
  it("stores eight repeated tentacles under one semantic label", async () => {
    const onSave = vi.fn(async (request: PoseSaveRequest) =>
      savedPose(request),
    );
    render(
      <PoseAnnotationEditor
        imageUrl="data:image/png;base64,"
        imageWidth={900}
        imageHeight={600}
        schema={schema}
        poses={[poseA]}
        onSave={onSave}
      />,
    );
    const stage = installStageBounds();

    fireEvent.click(
      screen.getByRole("button", { name: "Place tentacle" }),
    );
    for (let index = 0; index < 8; index += 1) {
      fireEvent.pointerDown(stage, {
        button: 0,
        clientX: 200 + index * 20,
        clientY: 220 + index * 10,
      });
    }

    expect(screen.getByText("tentacle 8 / 8")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Place tentacle" }),
    ).toBeDisabled();
    expect(screen.getAllByTestId(/pose-skeleton-/)).toHaveLength(8);

    fireEvent.click(screen.getByRole("button", { name: "Save pose" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    const request = onSave.mock.calls[0][0];
    const tentacles = request.observations.filter(
      (observation) => observation.semantic_label === "tentacle",
    );
    expect(tentacles).toHaveLength(8);
    expect(tentacles.map((item) => item.occurrence_index)).toEqual([
      0, 1, 2, 3, 4, 5, 6, 7,
    ]);
  });

  it("keeps unsaved edits isolated between pose instances", () => {
    const onSave = vi.fn(async (request: PoseSaveRequest) =>
      savedPose(request),
    );
    render(
      <PoseAnnotationEditor
        imageUrl="data:image/png;base64,"
        imageWidth={900}
        imageHeight={600}
        schema={schema}
        poses={[poseA, poseB]}
        onSave={onSave}
      />,
    );
    const stage = installStageBounds();

    fireEvent.click(
      screen.getByRole("button", { name: "Place tentacle" }),
    );
    fireEvent.pointerDown(stage, {
      button: 0,
      clientX: 450,
      clientY: 300,
    });
    expect(screen.getByText("tentacle 1 / 8")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Pose"), {
      target: { value: "pose-b" },
    });
    expect(screen.getByText("tentacle 0 / 8")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Pose"), {
      target: { value: "pose-a" },
    });
    expect(screen.getByText("tentacle 1 / 8")).toBeInTheDocument();
  });

  it("preserves image coordinates while zooming around the cursor", async () => {
    const onSave = vi.fn(async (request: PoseSaveRequest) =>
      savedPose(request),
    );
    render(
      <PoseAnnotationEditor
        imageUrl="data:image/png;base64,"
        imageWidth={900}
        imageHeight={600}
        schema={schema}
        poses={[poseA]}
        onSave={onSave}
      />,
    );
    const stage = installStageBounds();

    fireEvent.click(
      screen.getByRole("button", { name: "Place tentacle" }),
    );
    fireEvent.pointerDown(stage, {
      button: 0,
      clientX: 450,
      clientY: 300,
    });
    fireEvent.wheel(stage, {
      clientX: 450,
      clientY: 300,
      deltaY: -120,
    });
    fireEvent.pointerDown(stage, {
      button: 0,
      clientX: 450,
      clientY: 300,
    });

    fireEvent.click(screen.getByRole("button", { name: "Save pose" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));

    const request = onSave.mock.calls[0][0];
    const tentacles = request.observations.filter(
      (observation) => observation.semantic_label === "tentacle",
    );
    expect(tentacles).toHaveLength(2);
    expect(tentacles[0].x).toBeCloseTo(tentacles[1].x, 5);
    expect(tentacles[0].y).toBeCloseTo(tentacles[1].y, 5);
  });

  it("does not advance the base revision after a failed save", async () => {
    const onSave = vi
      .fn<(request: PoseSaveRequest) => Promise<PoseInstance>>()
      .mockImplementationOnce(async () => {
        throw new Error("network unavailable");
      })
      .mockImplementationOnce(async (request) => savedPose(request, 5));

    render(
      <PoseAnnotationEditor
        imageUrl="data:image/png;base64,"
        imageWidth={900}
        imageHeight={600}
        schema={schema}
        poses={[poseA]}
        onSave={onSave}
      />,
    );
    const stage = installStageBounds();

    fireEvent.click(
      screen.getByRole("button", { name: "Place tentacle" }),
    );
    fireEvent.pointerDown(stage, {
      button: 0,
      clientX: 450,
      clientY: 300,
    });

    fireEvent.click(screen.getByRole("button", { name: "Save pose" }));
    await screen.findByText("Save failed: network unavailable");

    expect(onSave.mock.calls[0][0].base_revision).toBe(4);
    expect(screen.getByText("tentacle 1 / 8")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save pose" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(2));

    expect(onSave.mock.calls[1][0].base_revision).toBe(4);
    await screen.findByText("Saved revision 5");
    expect(screen.getByTestId("pose-revision")).toHaveTextContent(
      "Revision 5",
    );
  });
});
