import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  importAnnotations,
  type AnnotationImportReport,
} from "../../api/annotationImports";

function ImportReport({ report }: { report: AnnotationImportReport }) {
  return (
    <div className="import-summary" role="status">
      <strong>
        {report.files_processed} annotation-support files processed
      </strong>
      <span>{report.boxes_imported} boxes imported</span>
      <span>{report.masks_imported} editable masks imported</span>
      <span>{report.duplicate_annotations} duplicates skipped</span>
      <span>{report.classes_created} classes created</span>
      <span>{report.unmatched_images} unmatched image references</span>
      <span>{report.skipped_annotations} annotations skipped</span>
      {report.issues.slice(0, 10).map((issue, index) => (
        <small
          key={`${issue.source_file ?? "file"}-${issue.annotation_id ?? index}`}
        >
          {issue.source_file ? `${issue.source_file}: ` : ""}
          {issue.detail}
        </small>
      ))}
      {report.issues.length > 10 && (
        <small>
          {report.issues.length - 10} additional issues were reported.
        </small>
      )}
    </div>
  );
}

export function AnnotationImportControls({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [report, setReport] = useState<AnnotationImportReport | null>(null);
  const importer = useMutation({
    mutationFn: (files: File[]) => importAnnotations(projectId, files),
    onSuccess: async (result) => {
      setReport(result);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["images", projectId] }),
        queryClient.invalidateQueries({ queryKey: ["project", projectId] }),
      ]);
    },
  });

  function importFiles(fileList: FileList | null) {
    const files = Array.from(fileList ?? []);
    if (files.length) {
      importer.mutate(files);
    }
  }

  return (
    <section className="annotation-sidebar-section">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Annotation interoperability</p>
          <h3>Import CoralNet-Toolbox annotations</h3>
        </div>
      </div>
      <p>
        Select one or more annotation JSON files. You can select
        class_mapping.json and data.yaml in the same import so ReefVision can
        preserve the original labels, colors, and class metadata.
      </p>
      <label className="button-label">
        Import annotations
        <input
          className="visually-hidden"
          type="file"
          accept=".json,.yaml,.yml,application/json,application/yaml,text/yaml"
          multiple
          onChange={(event) => importFiles(event.target.files)}
        />
      </label>
      {importer.isPending && <p>Validating and converting annotations...</p>}
      {importer.error && <p className="form-error">{importer.error.message}</p>}
      {report && <ImportReport report={report} />}
    </section>
  );
}
