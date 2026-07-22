import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { AppProviders } from "./app/providers";
import { CatalogInferenceLauncher } from "./features/annotation-editor/CatalogInferenceLauncher";
import { SegmentationInferenceLauncher } from "./features/annotation-editor/SegmentationInferenceLauncher";
import { SegmentationExportLauncher } from "./features/dataset-versions/SegmentationExportLauncher";
import { initializeRuntime } from "./runtime";
import { renderStartupError } from "./startup";

const rootElement = (() => {
  const element = document.getElementById("root");
  if (!(element instanceof HTMLElement)) {
    throw new Error("ReefVision root element was not found");
  }
  return element;
})();

async function bootstrap() {
  await initializeRuntime();
  createRoot(rootElement).render(
    <StrictMode>
      <AppProviders>
        <App />
        <SegmentationExportLauncher />
        <SegmentationInferenceLauncher />
        <CatalogInferenceLauncher />
      </AppProviders>
    </StrictMode>,
  );
}

void bootstrap().catch((error: unknown) => {
  const message =
    error instanceof Error
      ? error.message
      : "The desktop runtime did not finish initializing.";
  renderStartupError(rootElement, message, bootstrap);
});
