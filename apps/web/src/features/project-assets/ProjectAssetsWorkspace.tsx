import { useState } from "react";
import { BioacousticsWorkspace } from "../bioacoustics/BioacousticsWorkspace";
import { MultispectralWorkspace } from "./MultispectralWorkspace";
import "./projectAssets.css";

export function ProjectAssetsWorkspace({
  projectId,
  onOpenWorkflow,
}: {
  projectId: string;
  onOpenWorkflow: () => void;
}) {
  const [view, setView] = useState<"audio" | "spectral">("audio");
  return (
    <section aria-label="Project assets">
      <div
        className="project-asset-tabs"
        role="tablist"
        aria-label="Project asset types"
        onKeyDown={(event) => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key))
            return;
          event.preventDefault();
          const next =
            event.key === "Home"
              ? "audio"
              : event.key === "End"
                ? "spectral"
                : view === "audio"
                  ? "spectral"
                  : "audio";
          setView(next);
          event.currentTarget
            .querySelector<HTMLButtonElement>("#assets-" + next)
            ?.focus();
        }}
      >
        <button
          type="button"
          role="tab"
          id="assets-audio"
          aria-controls="assets-panel"
          aria-selected={view === "audio"}
          tabIndex={view === "audio" ? 0 : -1}
          onClick={() => setView("audio")}
        >
          Audio
        </button>
        <button
          type="button"
          role="tab"
          id="assets-spectral"
          aria-controls="assets-panel"
          aria-selected={view === "spectral"}
          tabIndex={view === "spectral" ? 0 : -1}
          onClick={() => setView("spectral")}
        >
          Multispectral images
        </button>
      </div>
      <div
        id="assets-panel"
        role="tabpanel"
        aria-labelledby={view === "audio" ? "assets-audio" : "assets-spectral"}
      >
        {view === "audio" ? (
          <BioacousticsWorkspace
            projectId={projectId}
            onOpenWorkflow={onOpenWorkflow}
          />
        ) : (
          <MultispectralWorkspace
            projectId={projectId}
            onOpenWorkflow={onOpenWorkflow}
          />
        )}
      </div>
    </section>
  );
}
