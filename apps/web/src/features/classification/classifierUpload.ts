import { getApiBaseUrl } from "../../runtime";
import type { ModelRecord } from "../phase456/api";

export async function uploadClassifier(
  projectId: string,
  file: File,
  classificationMode: "multiclass" | "binary_state",
  displayName?: string,
): Promise<ModelRecord> {
  const form = new FormData();
  form.append("model_file", file);
  form.append("classification_mode", classificationMode);
  if (displayName?.trim()) form.append("display_name", displayName.trim());
  const response = await fetch(
    `${getApiBaseUrl()}/projects/${projectId}/classifiers`,
    {
      method: "POST",
      body: form,
    },
  );
  if (!response.ok) {
    let message = `Classifier import failed with HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (typeof payload.detail === "string") message = payload.detail;
    } catch {
      // Keep the HTTP fallback.
    }
    throw new Error(message);
  }
  return (await response.json()) as ModelRecord;
}
