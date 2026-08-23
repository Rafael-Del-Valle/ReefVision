import { invoke } from "@tauri-apps/api/core";

export interface DesktopContext {
  apiBaseUrl: string;
  dataDir: string;
  desktopMode: boolean;
}

declare global {
  interface Window {
    __TAURI_INTERNALS__?: object;
  }
}

const runtimeState: DesktopContext & { initialized: boolean } = {
  apiBaseUrl: "",
  dataDir: "",
  desktopMode: false,
  initialized: false,
};

let initialization: Promise<void> | null = null;

function isTauriEnvironment(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

function browserRuntimeError(): Error {
  return new Error(
    "ReefVision is a desktop application and cannot run as a standalone browser app. " +
      "Launch ReefVision with the installed Windows application or use the desktop development command.",
  );
}

function desktopStartupError(apiBaseUrl: string): Error {
  return new Error(
    `ReefVision could not reach its local desktop API at ${apiBaseUrl} during startup. ` +
      `The sidecar may still be starting, may have stopped, or may be blocked by another process.`,
  );
}

async function waitForApiHealth(apiBaseUrl: string, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError: Error | null = null;

  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${apiBaseUrl}/health`);
      if (response.ok) {
        return;
      }
      lastError = new Error(
        `ReefVision desktop API health check returned HTTP ${response.status} during startup.`,
      );
    } catch (error) {
      lastError = desktopStartupError(apiBaseUrl);
    }
    await new Promise((resolve) => window.setTimeout(resolve, 250));
  }

  throw lastError ?? desktopStartupError(apiBaseUrl);
}

export async function initializeRuntime(): Promise<void> {
  if (runtimeState.initialized) {
    return;
  }
  if (initialization) {
    return initialization;
  }

  initialization = (async () => {
    if (!isTauriEnvironment()) {
      throw browserRuntimeError();
    }

    const context = await invoke<DesktopContext>("desktop_context");
    await waitForApiHealth(context.apiBaseUrl);
    runtimeState.apiBaseUrl = context.apiBaseUrl;
    runtimeState.dataDir = context.dataDir;
    runtimeState.desktopMode = context.desktopMode;
    runtimeState.initialized = true;
  })();

  try {
    await initialization;
  } catch (error) {
    initialization = null;
    throw error;
  }
}

export function getApiBaseUrl(): string {
  return runtimeState.apiBaseUrl;
}

export function getRuntimeContext(): DesktopContext {
  return {
    apiBaseUrl: runtimeState.apiBaseUrl,
    dataDir: runtimeState.dataDir,
    desktopMode: runtimeState.desktopMode,
  };
}

export function resetRuntimeForTests(): void {
  runtimeState.apiBaseUrl = "";
  runtimeState.dataDir = "";
  runtimeState.desktopMode = false;
  runtimeState.initialized = false;
  initialization = null;
}
