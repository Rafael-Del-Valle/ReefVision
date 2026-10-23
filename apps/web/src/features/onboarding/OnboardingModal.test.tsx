import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { OnboardingModal } from "./OnboardingModal";

function OnboardingHarness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open help
      </button>
      {open && (
        <OnboardingModal
          version="1.6"
          onClose={() => setOpen(false)}
          onDismissPermanently={() => setOpen(false)}
        />
      )}
    </>
  );
}

describe("onboarding local usability", () => {
  it("focuses the modal and restores the original control after Escape", () => {
    render(<OnboardingHarness />);
    const opener = screen.getByRole("button", { name: "Open help" });
    opener.focus();
    fireEvent.click(opener);
    const close = screen.getByRole("button", { name: "Close" });
    expect(document.activeElement).toBe(close);
    fireEvent.keyDown(close, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it("recaptures focus sent to a background control and restores it on dismissal", () => {
    render(<OnboardingHarness />);
    const opener = screen.getByRole("button", { name: "Open help" });
    opener.focus();
    fireEvent.click(opener);
    const close = screen.getByRole("button", { name: "Close" });

    // The original Tab-only trap did not handle programmatic/background focus.
    opener.focus();
    expect(document.activeElement).toBe(close);

    fireEvent.click(
      screen.getByRole("button", { name: "Don't show on startup" }),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);

    // A stale document focus listener would steal focus after unmount.
    const background = document.createElement("button");
    document.body.appendChild(background);
    try {
      background.focus();
      expect(document.activeElement).toBe(background);
    } finally {
      background.remove();
    }
  });

  it("keeps keyboard focus inside the first-run dialog", () => {
    render(
      <OnboardingModal
        version="1.6"
        onClose={vi.fn()}
        onDismissPermanently={vi.fn()}
      />,
    );
    const close = screen.getByRole("button", { name: "Close" });
    const last = screen.getByRole("button", { name: "Don't show on startup" });
    expect(document.activeElement).toBe(close);
    fireEvent.keyDown(close, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);
    fireEvent.keyDown(last, { key: "Tab" });
    expect(document.activeElement).toBe(close);
  });

  it("describes reviewed QC and saved workflows", () => {
    render(
      <OnboardingModal
        version="1.6"
        onClose={vi.fn()}
        onDismissPermanently={vi.fn()}
      />,
    );
    expect(screen.getByText("Research review and workflows")).toBeTruthy();
    expect(
      screen.getByText(/Workflow Builder can save and rerun a QC queue/),
    ).toBeTruthy();
    expect(screen.getByText(/never approve model predictions/)).toBeTruthy();
  });
});
