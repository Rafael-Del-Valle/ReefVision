import { version as packageVersion } from "../package.json";

// Development identity is deliberately separate from the public package/API
// version. ReefVision 1.1 is not yet a published or release-validated build.
// Vite only exposes this local label in development mode when explicitly set
// by the launch script. Production MSI builds retain their true package version.
const requestedLine: string | undefined = import.meta.env.VITE_REEFVISION_DEV_LINE;

export const developmentLine =
  import.meta.env.DEV &&
  typeof requestedLine === "string" &&
  /^1\.1\.0-dev(?:\.[a-z0-9]+)*$/.test(requestedLine.trim())
    ? requestedLine.trim()
    : null;

export function displayVersion(coreVersion?: string | null): string {
  return developmentLine ?? coreVersion ?? packageVersion;
}
