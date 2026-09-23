import type { GeoReferencedObservationSummary } from "./videoGeoreferencedObservationsApi";

export interface PendingVideoMapSeek {
  sequence: number;
  frameIndex: number;
  frameTimeSeconds: number;
}

export function frameIndexForVideoTime(
  currentTimeSeconds: number,
  fps: number,
  frameCount: number,
): number {
  if (
    !Number.isFinite(currentTimeSeconds) ||
    !Number.isFinite(fps) ||
    fps <= 0 ||
    frameCount <= 0
  ) {
    return 0;
  }

  const rawFrame = Math.round(Math.max(0, currentTimeSeconds) * fps);

  return Math.min(Math.max(0, rawFrame), Math.max(0, frameCount - 1));
}

export function videoTimeMatchesPendingSeek(
  pending: PendingVideoMapSeek | null,
  currentTimeSeconds: number,
  fps: number,
): boolean {
  if (!pending) {
    return true;
  }

  if (
    !Number.isFinite(currentTimeSeconds) ||
    !Number.isFinite(fps) ||
    fps <= 0
  ) {
    return false;
  }

  const halfFrameSeconds = 0.5 / fps;

  const toleranceSeconds = Math.max(0.05, halfFrameSeconds);

  return (
    Math.abs(currentTimeSeconds - pending.frameTimeSeconds) <= toleranceSeconds
  );
}

export function activeObservationForFrame(
  observations: GeoReferencedObservationSummary[],
  frameIndex: number | null | undefined,
): GeoReferencedObservationSummary | null {
  if (
    frameIndex === null ||
    frameIndex === undefined ||
    observations.length === 0
  ) {
    return null;
  }

  let best = observations[0];

  let bestDistance = Math.abs(best.frame_index - frameIndex);

  for (let index = 1; index < observations.length; index += 1) {
    const candidate = observations[index];

    const candidateDistance = Math.abs(candidate.frame_index - frameIndex);

    if (
      candidateDistance < bestDistance ||
      (candidateDistance === bestDistance &&
        candidate.frame_index < best.frame_index)
    ) {
      best = candidate;
      bestDistance = candidateDistance;
    }
  }

  return best;
}
