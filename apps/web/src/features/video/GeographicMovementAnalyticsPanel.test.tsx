import { fireEvent, render, screen, within } from "@testing-library/react";

import { describe, expect, it, vi } from "vitest";

import type { GeographicTrackAnalytics } from "./videoGeographicMovementAnalyticsApi";

import type { GeographicMovementAnalyticsState } from "./videoGeographicMovementAnalyticsState";

import { GeographicMovementAnalyticsPanel } from "./GeographicMovementAnalyticsPanel";

const coordinate = {
  latitude_deg: 32.75,
  longitude_deg: -79.93,
  crs: "EPSG:4326",
};

function analytics(observationCount = 0): GeographicTrackAnalytics {
  return {
    track_id: "track-1",
    video_asset_id: "video-1",
    observation_count: observationCount,
    segment_count: 0,
    first_frame_index: null,
    last_frame_index: null,
    first_frame_time_s: null,
    last_frame_time_s: null,
    elapsed_time_s: null,
    total_distance_m: 0,
    net_displacement_m: 0,
    mean_speed_m_s: null,
    max_segment_speed_m_s: null,
    start_location: null,
    end_location: null,
    segments: [],
  };
}

function successState(
  data: GeographicTrackAnalytics,
): GeographicMovementAnalyticsState {
  return {
    status: "success",
    trackId: data.track_id,
    data,
    error: null,
    errorStatus: null,
  };
}

describe("GeographicMovementAnalyticsPanel", () => {
  it("shows the idle selection prompt", () => {
    render(
      <GeographicMovementAnalyticsPanel
        state={{
          status: "idle",
          trackId: null,
          data: null,
          error: null,
          errorStatus: null,
        }}
        onReload={vi.fn()}
      />,
    );

    expect(
      screen.getByText(
        /Select an existing track to view geographic movement analytics/,
      ),
    ).toBeInTheDocument();

    expect(
      screen.getByRole("button", {
        name: "Refresh analytics",
      }),
    ).toBeDisabled();
  });

  it("shows loading without stale metrics", () => {
    render(
      <GeographicMovementAnalyticsPanel
        state={{
          status: "loading",
          trackId: "track-1",
          data: null,
          error: null,
          errorStatus: null,
        }}
        onReload={vi.fn()}
      />,
    );

    expect(
      screen.getByText("Loading geographic movement analytics..."),
    ).toBeInTheDocument();

    expect(screen.queryByText("Total distance")).not.toBeInTheDocument();
  });

  it("treats zero observations as an empty success state", () => {
    render(
      <GeographicMovementAnalyticsPanel
        state={successState(analytics())}
        onReload={vi.fn()}
      />,
    );

    expect(
      screen.getByTestId("geographic-analytics-empty"),
    ).toBeInTheDocument();

    expect(
      screen.getByText("No fresh geographic observations for this track."),
    ).toBeInTheDocument();

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows the backend error and allows retry", () => {
    const onReload = vi.fn();

    render(
      <GeographicMovementAnalyticsPanel
        state={{
          status: "error",
          trackId: "track-1",
          data: null,
          error: "Unsupported CRS.",
          errorStatus: 400,
        }}
        onReload={onReload}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Unsupported CRS.");

    fireEvent.click(
      screen.getByRole("button", {
        name: "Retry geographic analytics",
      }),
    );

    expect(onReload).toHaveBeenCalledTimes(1);
  });

  it("displays backend summary metrics without recalculation", () => {
    const data = {
      ...analytics(2),
      segment_count: 1,
      total_distance_m: 12.345,
      net_displacement_m: 10.5,
      elapsed_time_s: 2,
      mean_speed_m_s: 6.1725,
      max_segment_speed_m_s: 6.1725,
      start_location: coordinate,
      end_location: coordinate,
    };

    render(
      <GeographicMovementAnalyticsPanel
        state={successState(data)}
        onReload={vi.fn()}
      />,
    );

    expect(screen.getByText("12.35 m")).toBeInTheDocument();
    expect(screen.getByText("10.50 m")).toBeInTheDocument();
    expect(screen.getByText("2.00 s")).toBeInTheDocument();

    expect(screen.getAllByText("6.17 m/s")).toHaveLength(2);

    expect(
      screen.getByText("2 observations; 1 trajectory segments"),
    ).toBeInTheDocument();
  });

  it("does not invent speed when elapsed time is invalid", () => {
    const data: GeographicTrackAnalytics = {
      ...analytics(2),
      segment_count: 1,
      first_frame_index: 10,
      last_frame_index: 20,
      first_frame_time_s: 1,
      last_frame_time_s: 1,
      elapsed_time_s: 0,
      total_distance_m: 5,
      net_displacement_m: 5,
      start_location: coordinate,
      end_location: coordinate,
      segments: [
        {
          track_id: "track-1",
          video_asset_id: "video-1",
          start_observation_id: "observation-1",
          end_observation_id: "observation-2",
          start_frame_index: 10,
          end_frame_index: 20,
          start_frame_time_s: 1,
          end_frame_time_s: 1,
          elapsed_time_s: 0,
          start_location: coordinate,
          end_location: coordinate,
          distance_m: 5,
          speed_m_s: null,
          initial_bearing_deg: null,
          cumulative_distance_m: 5,
          speed_valid: false,
          invalid_reason: "non_positive_elapsed_time",
        },
      ],
    };

    render(
      <GeographicMovementAnalyticsPanel
        state={successState(data)}
        onReload={vi.fn()}
      />,
    );

    const table = screen.getByRole("table", {
      name: "Geographic trajectory segments",
    });

    expect(
      within(table).getByText("Non-positive elapsed time"),
    ).toBeInTheDocument();

    expect(within(table).getAllByRole("cell")[4]).toHaveTextContent(
      "Unavailable",
    );

    expect(screen.queryByText("Infinity")).not.toBeInTheDocument();
    expect(screen.queryByText("NaN")).not.toBeInTheDocument();
  });

  it("allows an explicit successful-result refresh", () => {
    const onReload = vi.fn();

    render(
      <GeographicMovementAnalyticsPanel
        state={successState(analytics(1))}
        onReload={onReload}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "Refresh analytics",
      }),
    );

    expect(onReload).toHaveBeenCalledTimes(1);
  });
});

describe("Task 16G panel synchronization", () => {
  const segment = {
    track_id: "track-1",
    video_asset_id: "video-1",
    start_observation_id: "observation-10",
    end_observation_id: "observation-20",
    start_frame_index: 10,
    end_frame_index: 20,
    start_frame_time_s: 1,
    end_frame_time_s: 2,
    elapsed_time_s: 1,
    start_location: coordinate,
    end_location: coordinate,
    distance_m: 5,
    speed_m_s: 5,
    initial_bearing_deg: 90,
    cumulative_distance_m: 5,
    speed_valid: true,
    invalid_reason: null,
  };

  const data: GeographicTrackAnalytics = {
    ...analytics(2),
    segment_count: 1,
    first_frame_index: 10,
    last_frame_index: 20,
    first_frame_time_s: 1,
    last_frame_time_s: 2,
    elapsed_time_s: 1,
    total_distance_m: 5,
    net_displacement_m: 5,
    mean_speed_m_s: 5,
    max_segment_speed_m_s: 5,
    start_location: coordinate,
    end_location: coordinate,
    segments: [segment],
  };

  it("highlights the segment containing the playback frame", () => {
    const { container, rerender } = render(
      <GeographicMovementAnalyticsPanel
        state={successState(data)}
        onReload={vi.fn()}
        activeFrameIndex={15}
      />,
    );

    expect(
      container.querySelector('tr[data-active-segment="true"]'),
    ).not.toBeNull();

    rerender(
      <GeographicMovementAnalyticsPanel
        state={successState(data)}
        onReload={vi.fn()}
        activeFrameIndex={25}
      />,
    );

    expect(
      container.querySelector('tr[data-active-segment="true"]'),
    ).toBeNull();
  });

  it.each([
    [0, "0.00°"],
    [90.1234, "90.12°"],
    [null, "Unavailable"],
  ])(
    "shows backend initial bearing %s with its convention",
    (bearing, expected) => {
      render(
        <GeographicMovementAnalyticsPanel
          state={successState({
            ...data,
            segments: [{ ...segment, initial_bearing_deg: bearing }],
          })}
          onReload={vi.fn()}
        />,
      );

      const table = screen.getByRole("table", {
        name: "Geographic trajectory segments",
      });
      const headings = within(table).getAllByRole("columnheader");
      const bearingColumn = headings.findIndex(
        (heading) => heading.textContent === "Initial bearing",
      );
      expect(bearingColumn).toBeGreaterThanOrEqual(0);
      expect(
        within(table).getAllByRole("cell")[bearingColumn],
      ).toHaveTextContent(String(expected));
      expect(
        screen.getByText(/clockwise from true north/i),
      ).toBeInTheDocument();
      expect(screen.getByText(/organism orientation/i)).toBeInTheDocument();
    },
  );

  it("seeks to the persisted endpoint without reloading analytics", () => {
    const onFrameSelect = vi.fn();
    const onReload = vi.fn();

    render(
      <GeographicMovementAnalyticsPanel
        state={successState(data)}
        onReload={onReload}
        activeFrameIndex={15}
        onFrameSelect={onFrameSelect}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "Seek to frame 20",
      }),
    );

    expect(onFrameSelect).toHaveBeenCalledTimes(1);
    expect(onFrameSelect).toHaveBeenCalledWith(20, 2);
    expect(onReload).not.toHaveBeenCalled();
  });

  it("keeps segment navigation absent for empty analytics", () => {
    render(
      <GeographicMovementAnalyticsPanel
        state={successState(analytics())}
        onReload={vi.fn()}
        activeFrameIndex={15}
        onFrameSelect={vi.fn()}
      />,
    );

    expect(
      screen.queryByRole("button", { name: /Seek to frame/ }),
    ).not.toBeInTheDocument();
  });
});
