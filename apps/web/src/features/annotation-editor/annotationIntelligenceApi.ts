import { getApiBaseUrl } from "../../runtime";
import type { JobRecord } from "../../api/client";
import type { RasterMaskEditResponse } from "./rasterMaskApi";

export async function intelligenceRequest<T>(
  path: string,
  body?: unknown,
  method = "POST",
): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (!response.ok) {
    let message = `Annotation assistance failed (HTTP ${response.status})`;
    try {
      const error = await response.json();
      if (typeof error.detail === "string") message = error.detail;
      else if (typeof error.error?.message === "string")
        message = error.error.message;
    } catch {
      /* Keep the HTTP error when the server cannot return JSON. */
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export function createSamImageProposals(
  projectId: string,
  imageId: string,
  variant: string,
  device: string,
): Promise<JobRecord> {
  return intelligenceRequest(
    `/projects/${encodeURIComponent(projectId)}/sam-image-proposals`,
    {
      image_id: imageId,
      variant,
      device,
    },
  );
}

export interface MaskRefinement {
  candidate_id: string;
  mask_annotation_id: string;
  image_id: string;
  expected_revision: number;
  status: string;
  mask_url: string;
  old_area_pixels: number;
  proposed_area_pixels: number;
  iou: number;
  edge_change_percent: number;
  warnings: string[];
  requires_confirmation: boolean;
}

export function refinementMaskUrl(candidateId: string): string {
  return `${getApiBaseUrl()}/mask-refinements/${encodeURIComponent(candidateId)}/content`;
}

export function createMaskRefinement(
  maskId: string,
  revision: number,
  variant: string,
  device: string,
): Promise<MaskRefinement> {
  return intelligenceRequest(
    `/mask-annotations/${encodeURIComponent(maskId)}/refinements`,
    {
      expected_revision: revision,
      variant,
      device,
    },
  );
}

export function reviewMaskRefinement(
  candidate: MaskRefinement,
  action: "accept" | "undo" | "redo",
  revision: number,
  confirm = false,
): Promise<RasterMaskEditResponse> {
  return intelligenceRequest(
    `/mask-refinements/${encodeURIComponent(candidate.candidate_id)}/${action}`,
    {
      expected_revision: revision,
      confirm_large_change: confirm,
    },
  );
}
