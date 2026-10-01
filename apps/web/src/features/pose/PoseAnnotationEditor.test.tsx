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

const oldSchema: PoseLandmarkSchema = {
  id: "jellyfish-schema",
  revision: 2,
  groups: [
    { name: "bell_center", count: 1 },
    { name: "tentacle", count: 4 },
  ],
  edges: [{ from: "bell_center", to: "tentacle" }],
};

const oldPose: PoseInstance = {
  id: "pose-old",
  revision: 2,
  schema_id: oldSchema.id,
  schema_revision: oldSchema.revision,
  observations: [
    {
      id: "old-bell",
      semantic_label: "bell_center",
      occurrence_index: 0,
      x: 450,
      y: 250,
      confidence: null,
      status: "visible",
      source: "manual",
    },
    ...Array.from({ length: 4 }, (_, index) => ({
      id: `old-tentacle-${index}`,
      semantic_label: "tentacle",
      occurrence_index: index,
      x: 300 + index * 50,
      y: 350,
      confidence: null,
      status: "visible" as const,
      source: "manual",
    })),
  ],
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
      status: "visible",
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
      status: "visible",
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

    fireEvent.click(screen.getByRole("button", { name: "Place tentacle" }));
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

    fireEvent.click(screen.getByRole("button", { name: "Place tentacle" }));
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

    fireEvent.click(screen.getByRole("button", { name: "Place tentacle" }));
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

  it("shows model provenance and confidence for the selected landmark", () => {
    const modelPose: PoseInstance = {
      ...poseA,
      id: "pose-model-details",
      observations: [
        {
          ...poseA.observations[0],
          id: "model-bell-details",
          confidence: 0.9472,
          source: "model",
        },
      ],
    };
    const onSave = vi.fn(async (request: PoseSaveRequest) =>
      savedPose(request),
    );

    render(
      <PoseAnnotationEditor
        imageUrl="data:image/png;base64,"
        imageWidth={900}
        imageHeight={600}
        schema={schema}
        poses={[modelPose]}
        onSave={onSave}
      />,
    );

    fireEvent.pointerDown(
      screen.getByTestId("pose-landmark-model-bell-details"),
      {
        button: 0,
        clientX: 450,
        clientY: 300,
      },
    );

    expect(screen.getByTestId("selected-landmark-source")).toHaveTextContent(
      "Source: model",
    );
    expect(
      screen.getByTestId("selected-landmark-confidence"),
    ).toHaveTextContent("Confidence: 0.947");
    expect(screen.getByTestId("selected-landmark-status")).toHaveTextContent(
      "Status: visible",
    );
  });

  it("marks dragged model landmarks as corrected and saves source-image coordinates", async () => {
    const modelPose: PoseInstance = {
      ...poseA,
      id: "pose-model",
      observations: [
        {
          ...poseA.observations[0],
          id: "model-bell",
          confidence: 0.94,
          source: "model",
        },
      ],
    };
    const onSave = vi.fn(async (request: PoseSaveRequest) =>
      savedPose(request),
    );
    render(
      <PoseAnnotationEditor
        imageUrl="data:image/png;base64,"
        imageWidth={900}
        imageHeight={600}
        schema={schema}
        poses={[modelPose]}
        onSave={onSave}
      />,
    );
    const stage = installStageBounds();

    fireEvent.pointerDown(screen.getByTestId("pose-landmark-model-bell"), {
      button: 0,
      clientX: 450,
      clientY: 300,
    });
    fireEvent.pointerMove(stage, {
      buttons: 1,
      clientX: 540,
      clientY: 350,
    });
    fireEvent.pointerUp(stage, {
      button: 0,
      clientX: 540,
      clientY: 350,
    });
    fireEvent.click(screen.getByRole("button", { name: "Save pose" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    const corrected = onSave.mock.calls[0][0].observations[0];
    expect(corrected.source).toBe("corrected");
    expect(corrected.confidence).toBe(0.94);
    expect(corrected.x).toBeGreaterThan(450);
    expect(corrected.y).toBeGreaterThan(300);
    expect(corrected.x).toBeLessThanOrEqual(900);
    expect(corrected.y).toBeLessThanOrEqual(600);
  });

  it("deletes a selected landmark from the saved pose draft", async () => {
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

    fireEvent.pointerDown(screen.getByTestId("pose-landmark-bell-a"), {
      button: 0,
      clientX: 450,
      clientY: 300,
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Delete selected landmark" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save pose" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0].observations).toEqual([]);
  });

  it("changes visibility status without conflating it with confidence", async () => {
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

    fireEvent.pointerDown(screen.getByTestId("pose-landmark-bell-a"), {
      button: 0,
      clientX: 450,
      clientY: 300,
    });
    fireEvent.change(screen.getByLabelText("Landmark status"), {
      target: { value: "occluded" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save pose" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    const bell = onSave.mock.calls[0][0].observations.find(
      (observation) => observation.id === "bell-a",
    );
    expect(bell?.status).toBe("occluded");
    expect(bell?.confidence).toBeNull();
  });

  it("marks model status edits as corrected provenance", async () => {
    const modelPose: PoseInstance = {
      ...poseA,
      id: "pose-model-status",
      observations: [
        {
          ...poseA.observations[0],
          id: "model-status-bell",
          confidence: 0.88,
          source: "model",
        },
      ],
    };
    const onSave = vi.fn(async (request: PoseSaveRequest) =>
      savedPose(request),
    );

    render(
      <PoseAnnotationEditor
        imageUrl="data:image/png;base64,"
        imageWidth={900}
        imageHeight={600}
        schema={schema}
        poses={[modelPose]}
        onSave={onSave}
      />,
    );

    fireEvent.pointerDown(screen.getByTestId("pose-landmark-model-status-bell"), {
      button: 0,
      clientX: 450,
      clientY: 300,
    });
    fireEvent.change(screen.getByLabelText("Landmark status"), {
      target: { value: "occluded" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save pose" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0].observations[0]).toMatchObject({
      status: "occluded",
      source: "corrected",
      confidence: 0.88,
    });
  });

  it("pins existing poses to their exact immutable schema revision", async () => {
    const onSave = vi.fn(async (request: PoseSaveRequest) =>
      savedPose(request),
    );
    render(
      <PoseAnnotationEditor
        imageUrl="data:image/png;base64,"
        imageWidth={900}
        imageHeight={600}
        schema={schema}
        schemaRevisions={[oldSchema]}
        poses={[oldPose, poseA]}
        initialPoseId={oldPose.id}
        onSave={onSave}
      />,
    );

    expect(screen.getByTestId("pose-schema-revision")).toHaveTextContent(
      "Schema revision 2",
    );
    expect(screen.getByText("tentacle 4 / 4")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Place tentacle" }),
    ).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Save pose" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0].schema_revision).toBe(2);
  });

  it("refuses to reinterpret an old pose with the current schema revision", () => {
    const onSave = vi.fn(async (request: PoseSaveRequest) =>
      savedPose(request),
    );
    render(
      <PoseAnnotationEditor
        imageUrl="data:image/png;base64,"
        imageWidth={900}
        imageHeight={600}
        schema={schema}
        poses={[oldPose]}
        onSave={onSave}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "requires schema jellyfish-schema revision 2",
    );
    expect(screen.queryByRole("button", { name: "Save pose" })).toBeNull();
  });

  it("creates new poses on the current schema revision", async () => {
    const onSave = vi.fn(async (request: PoseSaveRequest) =>
      savedPose(request),
    );
    const onCreatePose = vi.fn(async (currentSchema: PoseLandmarkSchema) => ({
      id: "pose-new",
      revision: 0,
      schema_id: currentSchema.id,
      schema_revision: currentSchema.revision,
      observations: [],
    }));

    render(
      <PoseAnnotationEditor
        imageUrl="data:image/png;base64,"
        imageWidth={900}
        imageHeight={600}
        schema={schema}
        schemaRevisions={[oldSchema]}
        poses={[]}
        onSave={onSave}
        onCreatePose={onCreatePose}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Create pose" }));
    await waitFor(() => expect(onCreatePose).toHaveBeenCalledTimes(1));
    expect(onCreatePose.mock.calls[0][0].revision).toBe(3);
    await screen.findByText("Created pose on schema revision 3");
    expect(screen.getByTestId("pose-schema-revision")).toHaveTextContent(
      "Schema revision 3",
    );
    expect(screen.getByText("tentacle 0 / 8")).toBeInTheDocument();
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

    fireEvent.click(screen.getByRole("button", { name: "Place tentacle" }));
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
    expect(screen.getByTestId("pose-revision")).toHaveTextContent("Revision 5");
  });
});
