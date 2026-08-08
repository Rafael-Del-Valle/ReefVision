import { getApiBaseUrl } from "../runtime";

export interface AnnotationImportIssue {
  source_file: string | null;
  image_reference: string | null;
  annotation_id: string | null;
  detail: string;
}

export interface AnnotationImportReport {
  project_id: string;
  format: string;
  files_processed: number;
  annotation_files: number;
  class_mapping_files: number;
  dataset_yaml_files: number;
  classes_matched: number;
  classes_created: number;
  boxes_imported: number;
  masks_imported: number;
  duplicate_annotations: number;
  unmatched_images: number;
  unknown_classes: number;
  skipped_annotations: number;
  issues: AnnotationImportIssue[];
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
  } catch {
    // Fall through to the HTTP status message.
  }
  return `Annotation import failed with HTTP ${response.status}`;
}

export async function importAnnotations(
  projectId: string,
  files: File[],
): Promise<AnnotationImportReport> {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file, file.name));
  const response = await fetch(
    `${getApiBaseUrl()}/projects/${projectId}/imports/annotations`,
    {
      method: "POST",
      body: formData,
    },
  );
  if (!response.ok) {
    throw new Error(await errorMessage(response));
  }
  return (await response.json()) as AnnotationImportReport;
}
