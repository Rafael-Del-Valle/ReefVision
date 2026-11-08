import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AnatomySkeletonDesigner } from "./AnatomySkeletonDesigner";

function renderDesigner() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <AnatomySkeletonDesigner projectId="project-1" />
    </QueryClientProvider>,
  );
}

describe("AnatomySkeletonDesigner", () => {
  it("creates arbitrary repeated anatomy with symmetry and skeleton edges", async () => {
    const requests: Array<{ url: string; body?: Record<string, unknown> }> = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      const body = init?.body
        ? (JSON.parse(String(init.body)) as Record<string, unknown>)
        : undefined;
      requests.push({ url, body });
      if (init?.method === "POST") {
        return new Response(
          JSON.stringify({
            id: "schema-1",
            name: "Moon jelly anatomy",
            revision: 1,
            schema_version: "pose-anatomy-0002",
            landmarks: body?.landmarks,
            edges: body?.edges,
            groups: [
              { name: "Bell center", count: 1 },
              { name: "Tentacle", count: 2 },
            ],
            expanded_labels: ["Bell center", "Tentacle", "Tentacle"],
            keypoint_count: 3,
            allows_repeated_labels: true,
            content_hash: "a".repeat(64),
            legacy_projection: false,
            created_at: "2026-11-08T12:00:00Z",
          }),
          { status: 201, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url.includes("/pose-schemas/schema-1")) {
        return new Response(
          JSON.stringify({
            id: "schema-1",
            project_id: "project-1",
            name: "Moon jelly anatomy",
            revisions: [],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response(JSON.stringify([]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    renderDesigner();
    await screen.findByText("No saved anatomy templates yet.");
    fireEvent.change(screen.getByLabelText("Template name"), {
      target: { value: "Moon jelly anatomy" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Add landmark" }));
    fireEvent.click(screen.getByRole("button", { name: "Add landmark" }));
    fireEvent.click(screen.getByRole("button", { name: "Add landmark" }));
    const ids = screen.getAllByLabelText("Stable landmark ID");
    const names = screen.getAllByLabelText("Anatomical name");
    fireEvent.change(ids[0], { target: { value: "bell_center" } });
    fireEvent.change(names[0], { target: { value: "Bell center" } });
    fireEvent.change(ids[1], { target: { value: "tentacle_1" } });
    fireEvent.change(names[1], { target: { value: "Tentacle" } });
    fireEvent.change(ids[2], { target: { value: "tentacle_2" } });
    fireEvent.change(names[2], { target: { value: "Tentacle" } });

    const repeatGroups = screen.getAllByLabelText("Repeated structure");
    const repeatIndices = screen.getAllByLabelText("Repeat index");
    fireEvent.change(repeatGroups[1], { target: { value: "tentacle" } });
    fireEvent.change(repeatIndices[1], { target: { value: "0" } });
    fireEvent.change(repeatGroups[2], { target: { value: "tentacle" } });
    fireEvent.change(repeatIndices[2], { target: { value: "1" } });
    const symmetry = screen.getAllByLabelText("Symmetric partner");
    fireEvent.change(symmetry[1], { target: { value: "tentacle_2" } });
    fireEvent.change(symmetry[2], { target: { value: "tentacle_1" } });

    fireEvent.change(screen.getByLabelText("Connection start"), {
      target: { value: "bell_center" },
    });
    fireEvent.change(screen.getByLabelText("Connection end"), {
      target: { value: "tentacle_1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add connection" }));
    expect(
      screen.getByTestId("anatomy-edge-bell_center-tentacle_1"),
    ).toBeInTheDocument();
    expect(screen.getAllByTestId(/anatomy-preview-landmark-/)).toHaveLength(3);

    fireEvent.click(screen.getByRole("button", { name: "Save template" }));
    await screen.findByText("Saved revision 1");

    const create = requests.find(
      (item) => item.body?.name === "Moon jelly anatomy",
    );
    expect(create?.body).toMatchObject({
      name: "Moon jelly anatomy",
      edges: [{ from_id: "bell_center", to_id: "tentacle_1" }],
    });
    expect(create?.body?.landmarks).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: "tentacle_1",
          repeat_group: "tentacle",
          repeat_index: 0,
          symmetric_with: "tentacle_2",
        }),
      ]),
    );
  });

  it("loads a saved template and saves reorder and rename as a new revision", async () => {
    const posts: Array<{ url: string; body: Record<string, unknown> }> = [];
    const revision = {
      id: "schema-1",
      name: "Fish anatomy",
      revision: 2,
      schema_version: "pose-anatomy-0002",
      landmarks: [
        { id: "snout", name: "Snout", required: true },
        { id: "tail", name: "Tail base", required: true },
      ],
      edges: [{ from_id: "snout", to_id: "tail" }],
      groups: [
        { name: "Snout", count: 1 },
        { name: "Tail base", count: 1 },
      ],
      expanded_labels: ["Snout", "Tail base"],
      keypoint_count: 2,
      allows_repeated_labels: false,
      content_hash: "b".repeat(64),
      legacy_projection: false,
      created_at: "2026-11-08T12:00:00Z",
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        posts.push({ url, body });
        return new Response(
          JSON.stringify({ ...revision, revision: 3, ...body }),
          {
            status: 201,
            headers: { "Content-Type": "application/json" },
          },
        );
      }
      return new Response(
        JSON.stringify(
          url.includes("/pose-schemas/schema-1")
            ? {
                id: "schema-1",
                project_id: "project-1",
                name: "Fish anatomy",
                revisions: [
                  { ...revision, revision: 1, content_hash: "a".repeat(64) },
                  revision,
                ],
              }
            : [revision],
        ),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      );
    });

    renderDesigner();
    await screen.findByRole("option", { name: "Fish anatomy · revision 2" });
    fireEvent.change(screen.getByLabelText("Saved template"), {
      target: { value: "schema-1" },
    });
    expect(
      await screen.findByText(/Revision 1 · 2 landmarks/),
    ).toBeInTheDocument();
    const names = screen.getAllByLabelText("Anatomical name");
    fireEvent.change(names[0], { target: { value: "Rostrum" } });
    fireEvent.click(
      screen.getAllByRole("button", { name: "Move landmark down" })[0],
    );
    fireEvent.click(screen.getByRole("button", { name: "Save new revision" }));

    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0].url).toContain("/pose-schemas/schema-1/revisions");
    expect(posts[0].body).not.toHaveProperty("name");
    expect(posts[0].body.landmarks).toEqual([
      expect.objectContaining({ id: "tail" }),
      expect.objectContaining({ id: "snout", name: "Rostrum" }),
    ]);
  });
});
