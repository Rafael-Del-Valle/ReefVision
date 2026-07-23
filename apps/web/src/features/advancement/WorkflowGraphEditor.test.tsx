import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import {
  type EditableWorkflow,
  WorkflowGraphEditor,
} from "./WorkflowGraphEditor";
import type { WorkflowNodeDefinition } from "./api";

const definitions: WorkflowNodeDefinition[] = [
  {
    node_type: "image_input",
    display_name: "Image input",
    inputs: [],
    outputs: [{ name: "images", data_type: "images", required: true }],
    requires_model: false,
    supported_model_tasks: [],
  },
  {
    node_type: "export",
    display_name: "Export",
    inputs: [{ name: "artifact", data_type: "artifact", required: true }],
    outputs: [
      { name: "archive", data_type: "export_archive", required: true },
    ],
    requires_model: false,
    supported_model_tasks: [],
  },
];

const initial: EditableWorkflow = {
  name: "Graph test",
  nodes: [
    {
      id: "images",
      node_type: "image_input",
      label: "Image input",
      configuration: { __ui_position: { x: 400, y: 300 } },
    },
  ],
  edges: [],
};

function Harness() {
  const [workflow, setWorkflow] = useState(initial);
  return (
    <>
      <output data-testid="node-count">{workflow.nodes.length}</output>
      <output data-testid="edge-count">{workflow.edges.length}</output>
      <WorkflowGraphEditor
        workflow={workflow}
        definitions={definitions}
        onChange={setWorkflow}
      />
    </>
  );
}

describe("WorkflowGraphEditor advanced editing", () => {
  it("duplicates nodes and supports undo and redo", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(
      within(screen.getByTestId("workflow-node-images")).getByRole("button", {
        name: /image input images/i,
      }),
    );
    await user.click(screen.getByRole("button", { name: /^duplicate$/i }));
    expect(screen.getByTestId("node-count")).toHaveTextContent("2");
    expect(screen.getByTestId("workflow-node-image_input")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^undo$/i }));
    expect(screen.getByTestId("node-count")).toHaveTextContent("1");

    await user.click(screen.getByRole("button", { name: /^redo$/i }));
    expect(screen.getByTestId("node-count")).toHaveTextContent("2");
  });

  it("auto-layouts the graph and allows typed output into a generic artifact port", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getAllByRole("button", { name: /^add$/i })[1]);
    const imageNode = screen.getByTestId("workflow-node-images");
    const exportNode = screen.getByTestId("workflow-node-export");
    await user.click(within(imageNode).getByRole("button", { name: "images" }));
    await user.click(within(exportNode).getByRole("button", { name: "artifact" }));
    expect(screen.getByTestId("edge-count")).toHaveTextContent("1");

    const before = imageNode.getAttribute("style");
    await user.click(screen.getByRole("button", { name: /auto-layout/i }));
    expect(screen.getByTestId("workflow-node-images").getAttribute("style")).not.toBe(
      before,
    );
  });
});
