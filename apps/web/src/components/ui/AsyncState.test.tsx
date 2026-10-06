import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EmptyState, ErrorState, LoadingState } from "./AsyncState";

afterEach(() => {
  cleanup();
});

describe("scientist-facing asynchronous states", () => {
  it("announces loading without stealing focus", () => {
    render(
      <LoadingState
        title="Opening project"
        description="Loading project records."
      />,
    );

    const state = screen.getByRole("status");

    expect(state).toHaveAttribute("aria-live", "polite");

    expect(screen.getByText("Opening project")).toBeInTheDocument();
  });

  it("announces empty scientific workspaces politely", () => {
    render(
      <EmptyState
        title="No reviewed images"
        description="Review an image before exporting."
      />,
    );

    const state = screen.getByRole("status");

    expect(state).toHaveAttribute("aria-live", "polite");

    expect(screen.getByText("No reviewed images")).toBeInTheDocument();
  });

  it("exposes errors as alerts with non-submit recovery buttons", () => {
    render(
      <ErrorState
        title="Project unavailable"
        message="The project could not be loaded."
        error={new Error("offline")}
        onRetry={vi.fn()}
        onBack={vi.fn()}
      />,
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();

    expect(
      screen.getByRole("button", {
        name: "Retry",
      }),
    ).toHaveAttribute("type", "button");

    expect(
      screen.getByRole("button", {
        name: "Go back",
      }),
    ).toHaveAttribute("type", "button");
  });
});
