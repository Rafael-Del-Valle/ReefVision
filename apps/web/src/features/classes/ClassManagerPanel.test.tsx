import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Project } from "../../api/client";
import { ClassManagerPanel } from "./ClassManagerPanel";

const project: Project = {
  id: "project-1",
  name: "CPT Coral Study",
  slug: "cpt-coral-study",
  description: "Octocoral polyp annotations",
  storage_root: "projects/project-1",
  default_annotation_type: "bbox",
  created_at: "2026-07-08T00:00:00Z",
  updated_at: "2026-07-08T00:00:00Z",
  archived_at: null,
  label_classes: [
    {
      id: "class-1",
      project_id: "project-1",
      class_index: 0,
      display_order: 0,
      name: "Muricea Closed",
      scientific_name: null,
      state_name: null,
      description: null,
      display_color: "#E76F51",
      is_active: true,
      archived_at: null,
      created_at: "2026-07-08T00:00:00Z",
      updated_at: "2026-07-08T00:00:00Z",
    },
    {
      id: "class-2",
      project_id: "project-1",
      class_index: 1,
      display_order: 1,
      name: "Muricea Open",
      scientific_name: null,
      state_name: null,
      description: null,
      display_color: "#2A9D8F",
      is_active: true,
      archived_at: null,
      created_at: "2026-07-08T00:00:00Z",
      updated_at: "2026-07-08T00:00:00Z",
    },
  ],
};

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ClassManagerPanel project={project} />
    </QueryClientProvider>,
  );
}

function sourceClassRow() {
  const sourceHeading = screen.getAllByText("Muricea Closed", {
    selector: "strong",
  })[0];
  const row = sourceHeading.closest("li");
  expect(row).not.toBeNull();
  return row as HTMLLIElement;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ClassManagerPanel", () => {
  it("previews and executes a reassignment with the reviewed checksum", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) => {
        const url = String(input);
        if (
          url.endsWith(
            `/projects/${project.id}/classes/class-1/reassign/preview`,
          ) &&
          init?.method === "POST"
        ) {
          return jsonResponse({
            id: "operation-1",
            project_id: project.id,
            source_class_id: "class-1",
            target_class_id: "class-2",
            operation_type: "reassign",
            status: "previewed",
            preview_checksum: "a".repeat(64),
            requested_by_identity: "local-user:test",
            source_class: {
              id: "class-1",
              name: "Muricea Closed",
              class_index: 0,
              display_order: 0,
              display_color: "#E76F51",
              scientific_name: null,
              state_name: null,
              description: null,
              archived_at: null,
            },
            target_class: {
              id: "class-2",
              name: "Muricea Open",
              class_index: 1,
              display_order: 1,
              display_color: "#2A9D8F",
              scientific_name: null,
              state_name: null,
              description: null,
              archived_at: null,
            },
            plan: {
              mutable_records: [
                {
                  key: "annotations_active",
                  label: "Active annotations",
                  count: 1,
                  record_ids: ["annotation-1"],
                },
              ],
              protected_records: [
                {
                  key: "dataset_versions",
                  label: "Immutable dataset versions",
                  count: 1,
                  record_ids: ["version-1"],
                },
              ],
              blocking_records: [],
              compatibility_impacts: [
                {
                  key: "dataset_versions",
                  label: "Immutable dataset versions",
                  status: "Historical class only",
                  message: "Immutable versions keep the original class map.",
                  record_ids: ["version-1"],
                },
              ],
              warnings: [],
              blockers: [],
            },
            affected_counts: [],
            protected_reference_counts: [],
            warnings: [],
            failures: [],
            rollback_result: {},
            final_state: null,
            notes: null,
            created_at: "2026-07-10T00:00:00Z",
            updated_at: "2026-07-10T00:00:00Z",
            started_at: null,
            completed_at: null,
          });
        }
        if (
          url.endsWith(`/projects/${project.id}/classes/class-1/reassign`) &&
          init?.method === "POST"
        ) {
          return jsonResponse({
            id: "operation-1",
            project_id: project.id,
            source_class_id: "class-1",
            target_class_id: "class-2",
            operation_type: "reassign",
            status: "completed",
            preview_checksum: "a".repeat(64),
            requested_by_identity: "local-user:test",
            source_class: {
              id: "class-1",
              name: "Muricea Closed",
              class_index: 0,
              display_order: 0,
              display_color: "#E76F51",
              scientific_name: null,
              state_name: null,
              description: null,
              archived_at: null,
            },
            target_class: {
              id: "class-2",
              name: "Muricea Open",
              class_index: 1,
              display_order: 1,
              display_color: "#2A9D8F",
              scientific_name: null,
              state_name: null,
              description: null,
              archived_at: null,
            },
            plan: {
              mutable_records: [
                {
                  key: "annotations_active",
                  label: "Active annotations",
                  count: 1,
                  record_ids: ["annotation-1"],
                },
              ],
              protected_records: [],
              blocking_records: [],
              compatibility_impacts: [],
              warnings: [],
              blockers: [],
            },
            affected_counts: [
              {
                key: "annotations_active",
                label: "Active annotations",
                count: 1,
                record_ids: [],
              },
            ],
            protected_reference_counts: [],
            warnings: [],
            failures: [],
            rollback_result: { rolled_back: false },
            final_state: "reassigned",
            notes: null,
            created_at: "2026-07-10T00:00:00Z",
            updated_at: "2026-07-10T00:00:01Z",
            started_at: "2026-07-10T00:00:00Z",
            completed_at: "2026-07-10T00:00:01Z",
          });
        }
        if (
          url.endsWith(`/projects/${project.id}/classes/class-1/usage`) &&
          (!init?.method || init.method === "GET")
        ) {
          return jsonResponse({
            class_id: "class-1",
            project_id: project.id,
            class_name: "Muricea Closed",
            is_active: true,
            archived_at: null,
            total_references: 1,
            mutable_reference_count: 1,
            immutable_reference_count: 0,
            can_delete: false,
            delete_blockers: [],
            compatibility_warnings: [],
            counts: [],
          });
        }
        throw new Error(`Unhandled request: ${init?.method ?? "GET"} ${url}`);
      });

    renderPanel();
    await userEvent.click(
      within(sourceClassRow()).getByRole("button", {
        name: "Preview reassign",
      }),
    );

    expect(await screen.findByText("Reassign preview")).toBeInTheDocument();
    expect(screen.getByText(/Historical class only/)).toBeInTheDocument();

    await userEvent.click(
      within(sourceClassRow()).getByRole("button", { name: "Run reassign" }),
    );

    await waitFor(() =>
      expect(screen.getByText("Latest operation")).toBeInTheDocument(),
    );

    const executeCall = fetchMock.mock.calls.find(
      ([request, requestInit]) =>
        String(request).endsWith(
          `/projects/${project.id}/classes/class-1/reassign`,
        ) && requestInit?.method === "POST",
    );
    expect(executeCall).toBeDefined();
    expect(executeCall?.[1]?.body).toContain("operation-1");
    expect(executeCall?.[1]?.body).toContain("a".repeat(64));
  });

  it("renders blocking records for reassign and delete previews", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (
        url.endsWith(
          `/projects/${project.id}/classes/class-1/reassign-delete/preview`,
        ) &&
        init?.method === "POST"
      ) {
        return jsonResponse({
          id: "operation-2",
          project_id: project.id,
          source_class_id: "class-1",
          target_class_id: "class-2",
          operation_type: "reassign_delete",
          status: "previewed",
          preview_checksum: "b".repeat(64),
          requested_by_identity: "local-user:test",
          source_class: {
            id: "class-1",
            name: "Muricea Closed",
            class_index: 0,
            display_order: 0,
            display_color: "#E76F51",
            scientific_name: null,
            state_name: null,
            description: null,
            archived_at: null,
          },
          target_class: {
            id: "class-2",
            name: "Muricea Open",
            class_index: 1,
            display_order: 1,
            display_color: "#2A9D8F",
            scientific_name: null,
            state_name: null,
            description: null,
            archived_at: null,
          },
          plan: {
            mutable_records: [],
            protected_records: [],
            blocking_records: [
              {
                key: "annotations_deleted",
                label: "Deleted annotations block physical deletion",
                count: 1,
                record_ids: ["annotation-deleted"],
              },
            ],
            compatibility_impacts: [],
            warnings: [],
            blockers: [
              "Deleted annotations still reference this class and would be removed by a hard delete.",
            ],
          },
          affected_counts: [],
          protected_reference_counts: [],
          warnings: [],
          failures: [],
          rollback_result: {},
          final_state: null,
          notes: null,
          created_at: "2026-07-10T00:00:00Z",
          updated_at: "2026-07-10T00:00:00Z",
          started_at: null,
          completed_at: null,
        });
      }
      throw new Error(`Unhandled request: ${init?.method ?? "GET"} ${url}`);
    });

    renderPanel();
    await userEvent.click(
      within(sourceClassRow()).getByRole("button", {
        name: "Preview Reassign and Delete",
      }),
    );

    expect(
      await screen.findByText("Reassign and Delete preview"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Deleted annotations still reference this class and would be removed by a hard delete.",
      ),
    ).toBeInTheDocument();
  });
});
