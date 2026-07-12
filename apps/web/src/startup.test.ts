import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderStartupError } from "./startup";

describe("renderStartupError", () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="root"></div>';
  });

  it("renders a retryable startup error screen", () => {
    const onRetry = vi.fn();
    const root = document.getElementById("root");
    if (!(root instanceof HTMLElement)) {
      throw new Error("Test root element was not created");
    }

    renderStartupError(root, "Desktop API did not become ready.", onRetry);

    expect(
      screen.getByRole("heading", { name: "ReefVision could not start" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Desktop API did not become ready."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry startup" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("restores the retry button after a failed retry", async () => {
    const onRetry = vi.fn().mockRejectedValue(new Error("still failing"));
    const root = document.getElementById("root");
    if (!(root instanceof HTMLElement)) {
      throw new Error("Test root element was not created");
    }

    renderStartupError(root, "Desktop API did not become ready.", onRetry);

    const retryButton = screen.getByRole("button", { name: "Retry startup" });
    fireEvent.click(retryButton);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Retry startup" }),
      ).not.toBeDisabled(),
    );
  });
});
