import { request } from "../../api/client";
import { getApiBaseUrl } from "../../runtime";

export interface AdjustmentParameters {
  red_gain_percent: number;
  green_gain_percent: number;
  blue_gain_percent: number;
  brightness_offset: number;
  contrast_percent: number;
}

export interface ImageAdjustmentPin {
  recipe_id: string;
  content_sha256: string;
  original_sha256: string;
  rendition_sha256: string;
}

export interface ImageAdjustmentRecord {
  id: string;
  image_id: string;
  project_id: string;
  content_sha256: string;
  created_at: string;
  receipt: {
    project_id: string;
    image_id: string;
    original_sha256: string;
    rendition_sha256: string;
    rgb_sha256: string;
    width_px: number;
    height_px: number;
    pixel_axes: "raw_source";
    parameters: AdjustmentParameters;
  };
}

export interface AdjustmentView {
  imageId: string;
  url: string;
  visible: boolean;
  recipe?: ImageAdjustmentRecord;
}

export const originalPhotoParameters: AdjustmentParameters = {
  red_gain_percent: 100,
  green_gain_percent: 100,
  blue_gain_percent: 100,
  brightness_offset: 0,
  contrast_percent: 100,
};

const path = (image: string) =>
  `/images/${encodeURIComponent(image)}/adjustments`;

export function adjustmentPin(
  recipe: ImageAdjustmentRecord,
): ImageAdjustmentPin {
  return {
    recipe_id: recipe.id,
    content_sha256: recipe.content_sha256,
    original_sha256: recipe.receipt.original_sha256,
    rendition_sha256: recipe.receipt.rendition_sha256,
  };
}

export function adjustmentFileUrl(
  image: string,
  recipe: string,
  resource: "rendition" | "download" | "export",
) {
  return `${getApiBaseUrl()}${path(image)}/${encodeURIComponent(recipe)}/${resource}`;
}

export function listAdjustments(
  image: string,
  page: number,
  signal?: AbortSignal,
  pageSize = 24,
) {
  return request<{
    items: ImageAdjustmentRecord[];
    total: number;
    page_size: number;
  }>(`${path(image)}?page=${page}&page_size=${pageSize}`, { signal });
}

export function saveAdjustment(
  image: string,
  original: string,
  parameters: AdjustmentParameters,
) {
  return request<ImageAdjustmentRecord>(path(image), {
    method: "POST",
    body: JSON.stringify({ original_sha256: original, parameters }),
  });
}

export async function previewAdjustment(
  image: string,
  original: string,
  parameters: AdjustmentParameters,
): Promise<Blob> {
  return fetchRendition(`${getApiBaseUrl()}${path(image)}/preview`, {
    method: "POST",
    body: JSON.stringify({ original_sha256: original, parameters }),
    headers: { "Content-Type": "application/json" },
  });
}

export function reopenAdjustment(recipe: ImageAdjustmentRecord): Promise<Blob> {
  return fetchRendition(
    adjustmentFileUrl(recipe.image_id, recipe.id, "rendition"),
  );
}

async function fetchRendition(
  url: string,
  options?: RequestInit,
): Promise<Blob> {
  const response = await fetch(url, {
    ...options,
    signal: AbortSignal.timeout(30_000),
  });
  if (!response.ok) {
    const payload: { detail?: unknown } = await response
      .json()
      .catch(() => ({}));
    throw new Error(
      typeof payload.detail === "string"
        ? payload.detail
        : `Adjusted image could not be loaded (${response.status})`,
    );
  }
  return response.blob();
}
