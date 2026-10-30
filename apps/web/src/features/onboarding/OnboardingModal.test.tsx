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
          hasProject={true}
          onNavigate={vi.fn()}
          onClose={() => setOpen(false)}
          onDismissPermanently={() => setOpen(false)}
        />
      )}
    </>
  );
}

function ProjectCreationHandoffHarness() {
  const [onboardingOpen, setOnboardingOpen] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  return (
    <>
      <button type="button">Help</button>
      {onboardingOpen && (
        <OnboardingModal
          version="1.6"
          hasProject={false}
          onNavigate={(destination) => {
            if (destination === "create_project") setCreateOpen(true);
          }}
          onClose={() => setOnboardingOpen(false)}
          onDismissPermanently={() => setOnboardingOpen(false)}
        />
      )}
      {createOpen && (
        <section role="dialog" aria-label="Create project">
          <input aria-label="Project name" autoFocus />
        </section>
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
        hasProject={true}
        onNavigate={vi.fn()}
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

  it("opens saved workflows without permanently dismissing onboarding", () => {
    const onNavigate = vi.fn();
    const onClose = vi.fn();
    const onDismissPermanently = vi.fn();
    render(
      <OnboardingModal
        version="1.6"
        hasProject={true}
        onNavigate={onNavigate}
        onClose={onClose}
        onDismissPermanently={onDismissPermanently}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Open Workflow Builder" }),
    );
    expect(onNavigate).toHaveBeenCalledTimes(1);
    expect(onNavigate).toHaveBeenCalledWith("workflows");
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onDismissPermanently).not.toHaveBeenCalled();
  });

  it("disables project-only links until a project is selected", () => {
    const onNavigate = vi.fn();
    const onClose = vi.fn();
    render(
      <OnboardingModal
        version="1.6"
        hasProject={false}
        onNavigate={onNavigate}
        onClose={onClose}
        onDismissPermanently={vi.fn()}
      />,
    );
    for (const name of [
      "Open class manager",
      "Open QC review",
      "Open Workflow Builder",
    ]) {
      const button = screen.getByRole("button", { name });
      expect(button.hasAttribute("disabled")).toBe(true);
      fireEvent.click(button);
    }
    expect(screen.getByText(/Select or create a project to open class/)).toBeTruthy();
    expect(onNavigate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Open System status" }));
    expect(onNavigate).toHaveBeenCalledTimes(1);
    expect(onNavigate).toHaveBeenCalledWith("system");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("offers explicit project creation from first-run help without creating data", () => {
    const onNavigate = vi.fn();
    const onClose = vi.fn();
    const onDismissPermanently = vi.fn();
    render(
      <OnboardingModal
        version="1.6"
        hasProject={false}
        onNavigate={onNavigate}
        onClose={onClose}
        onDismissPermanently={onDismissPermanently}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Create a project" }));
    expect(onNavigate).toHaveBeenCalledTimes(1);
    expect(onNavigate).toHaveBeenCalledWith("create_project");
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onDismissPermanently).not.toHaveBeenCalled();
  });

  it("hands keyboard focus to the project-creation dialog", () => {
    render(<ProjectCreationHandoffHarness />);
    fireEvent.click(screen.getByRole("button", { name: "Create a project" }));
    expect(
      screen.queryByRole("heading", { name: /Welcome to ReefVision/ }),
    ).toBeNull();
    expect(
      screen.getByRole("dialog", { name: "Create project" }),
    ).toBeTruthy();
    expect(document.activeElement).toBe(
      screen.getByRole("textbox", { name: "Project name" }),
    );
  });

  it("opens existing-project selection without requiring a project first", () => {
    const onNavigate = vi.fn();
    const onClose = vi.fn();
    render(
      <OnboardingModal
        version="1.6"
        hasProject={false}
        onNavigate={onNavigate}
        onClose={onClose}
        onDismissPermanently={vi.fn()}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Choose an existing project" }),
    );
    expect(onNavigate).toHaveBeenCalledTimes(1);
    expect(onNavigate).toHaveBeenCalledWith("projects");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not offer project-creation navigation inside an existing project", () => {
    render(
      <OnboardingModal
        version="1.6"
        hasProject={true}
        onNavigate={vi.fn()}
        onClose={vi.fn()}
        onDismissPermanently={vi.fn()}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "Create a project" }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Choose an existing project" }),
    ).toBeNull();
  });

  it("describes reviewed QC and saved workflows", () => {
    render(
      <OnboardingModal
        version="1.6"
        hasProject={true}
        onNavigate={vi.fn()}
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
