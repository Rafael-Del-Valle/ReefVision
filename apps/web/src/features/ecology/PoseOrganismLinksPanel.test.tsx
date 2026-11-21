import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { PoseOrganismLinksPanel } from "./PoseOrganismLinksPanel";

afterEach(() => vi.restoreAllMocks());

it("requires explicit review, keeps interrupted scope visible, and opens exact evidence", async () => {
  const sent: unknown[] = [];
  const link = {
    id: "revision-1",
    link_id: "link",
    revision: 1,
    action: "link",
    status: "current",
    stale_reason: null,
    association_run_id: "run",
    animal_identity_id: "fish-b",
    frame_start: 2,
    frame_end: 4,
    created_at: "2026-11-14T12:00:00Z",
    source: {
      video_id: "video",
      observations: [
        { id: "obs-2", frame_index: 2, source_video_track_id: "track" },
      ],
      measurements: [
        { id: "series", run_id: "measure", name: "Gape distance" },
      ],
      events: [
        {
          id: "event",
          run_id: "event-run",
          measurement_series_id: "series",
          start_frame: 2,
          end_frame: 4,
        },
      ],
    },
  };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = new URL(String(input));
    if (url.pathname.endsWith("/ecology/pose-links")) {
      if (init?.method === "POST") {
        sent.push(JSON.parse(String(init.body)));
        return Response.json(link, { status: 201 });
      }
      return Response.json({
        items: sent.length ? [link] : [],
        total: sent.length,
        limit: 50,
      });
    }
    if (url.pathname.endsWith("/videos")) {
      return Response.json([
        { id: "video", original_filename: "recording.mp4" },
      ]);
    }
    if (url.pathname.endsWith("/pose-identity-runs")) {
      return Response.json([
        {
          id: "run",
          video_id: "video",
          revision: 2,
          status: "completed",
          pose_schema_content_hash: "a".repeat(64),
        },
      ]);
    }
    if (url.pathname.endsWith("/identities")) {
      return Response.json([
        {
          id: "fish-a",
          stable_identity_key: "First fish",
          lifecycle_state: "active",
          first_frame: 0,
          last_frame: 1,
        },
        {
          id: "fish-b",
          stable_identity_key: "Second fish",
          lifecycle_state: "active",
          first_frame: 2,
          last_frame: 4,
        },
      ]);
    }
    if (url.pathname.endsWith("/observations")) {
      return Response.json([
        {
          id: "obs-2",
          animal_identity_id: "fish-b",
          frame_index: 2,
          verification_state: "scientist_confirmed",
        },
        {
          id: "obs-4",
          animal_identity_id: "fish-b",
          frame_index: 4,
          verification_state: "scientist_confirmed",
        },
      ]);
    }
    return Response.json([]);
  });
  const onOpenPoseEvidence = vi.fn();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <PoseOrganismLinksPanel
        projectId="project"
        organismKey="organism-b"
        organismRevisionId="organism-rev"
        onOpenPoseEvidence={onOpenPoseEvidence}
      />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Link reviewed pose" }));
  const runOption = await screen.findByRole("option", {
    name: /recording.mp4/,
  });
  const form = within(screen.getByRole("form", { name: "Link reviewed pose" }));
  expect(
    form.getByRole("button", { name: "Confirm pose link" }),
  ).toBeDisabled();
  fireEvent.change(form.getByLabelText(/Reviewed identity run/), {
    target: { value: runOption.getAttribute("value") },
  });
  await screen.findByRole("option", { name: "Second fish" });
  fireEvent.change(form.getByLabelText(/Animal identity/), {
    target: { value: "fish-b" },
  });
  expect(
    await screen.findByText(/Frames without reviewed observations remain gaps/),
  ).toBeVisible();
  fireEvent.change(form.getByLabelText("Reviewer"), {
    target: { value: "Field scientist" },
  });
  fireEvent.change(form.getByLabelText("Reason"), {
    target: { value: "Recognized the marked fish" },
  });
  fireEvent.submit(
    form.getByRole("button", { name: "Confirm pose link" }).closest("form")!,
  );
  expect(await form.findByRole("alert")).toHaveTextContent(
    /explicitly confirm/,
  );
  expect(sent).toEqual([]);
  fireEvent.click(form.getByRole("checkbox", { name: /I confirm/ }));
  fireEvent.click(form.getByRole("button", { name: "Confirm pose link" }));
  await waitFor(() =>
    expect(sent).toEqual([
      {
        confirm: true,
        reviewer: "Field scientist",
        reason: "Recognized the marked fish",
        organism_revision_id: "organism-rev",
        association_run_id: "run",
        animal_identity_id: "fish-b",
        expected_identity_run_revision: 2,
        expected_pose_schema_sha256: "a".repeat(64),
        frame_start: 2,
        frame_end: 4,
        measurement_series_ids: [],
        event_revision_ids: [],
      },
    ]),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Open event at frame 2" }),
  );
  expect(onOpenPoseEvidence).toHaveBeenCalledWith({
    videoId: "video",
    frameIndex: 2,
    sourceTrackId: "track",
    identityRunId: "run",
    animalIdentityId: "fish-b",
    measurementRunId: "measure",
    measurementSeriesId: "series",
    eventRunId: "event-run",
    eventRevisionId: "event",
  });
  client.clear();
});
