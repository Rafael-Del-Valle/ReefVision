import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  importProjectExchange,
  inspectProjectExchange,
} from "../../features/interoperability/projectExchangeApi";

export function ProjectImportDialog({
  onClose,
  onImported,
}: {
  onClose: () => void;
  onImported: (projectId: string) => void;
}) {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [projectName, setProjectName] = useState("");

  const inspect = useMutation({
    mutationFn: () => {
      if (!file) throw new Error("Choose a ReefVision project package first.");
      return inspectProjectExchange(file);
    },
  });

  const importPackage = useMutation({
    mutationFn: () => {
      if (!file) throw new Error("Choose a ReefVision project package first.");
      if (!inspect.data?.compatible) {
        throw new Error(
          "Inspect a compatible project package before importing.",
        );
      }
      return importProjectExchange(file, projectName.trim() || undefined);
    },
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ["project_summaries"] });
      queryClient.removeQueries({ queryKey: ["project", result.project_id] });
      onImported(result.project_id);
    },
  });

  return (
    <div className="modal-backdrop" role="presentation">
      <section
        className="modal rv-project-import-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="project-import-title"
      >
        <div className="section-heading">
          <div>
            <p className="eyebrow">Portable project</p>
            <h2 id="project-import-title">Import ReefVision project</h2>
          </div>
          <button
            type="button"
            className="icon-button"
            aria-label="Close project import"
            onClick={onClose}
          >
            Close
          </button>
        </div>

        <p>
          Import a versioned ReefVision Exchange package from another computer
          or collaborator. Import always creates a new managed project and never
          overwrites an existing project.
        </p>

        <label>
          ReefVision project package
          <input
            type="file"
            accept=".zip,.reefvision.zip,application/zip"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              inspect.reset();
              importPackage.reset();
              setProjectName("");
            }}
          />
        </label>

        <button
          type="button"
          className="secondary"
          disabled={!file || inspect.isPending}
          onClick={() => inspect.mutate()}
        >
          {inspect.isPending ? "Inspecting…" : "Inspect package safely"}
        </button>

        {inspect.data && (
          <div className="rv-project-import-summary">
            <div>
              <span>Compatible</span>
              <strong>{inspect.data.compatible ? "Yes" : "No"}</strong>
            </div>
            <div>
              <span>Project</span>
              <strong>{inspect.data.project_name ?? "Unknown"}</strong>
            </div>
            <div>
              <span>Format</span>
              <strong>{inspect.data.format_version ?? "Unknown"}</strong>
            </div>
            <div>
              <span>Packaged files</span>
              <strong>{inspect.data.included_media_count}</strong>
            </div>
          </div>
        )}

        {inspect.data?.warnings.map((warning) => (
          <p key={warning} className="annotation-helper">
            {warning}
          </p>
        ))}

        {inspect.data?.errors.map((error) => (
          <p key={error} className="form-error">
            {error}
          </p>
        ))}

        {inspect.data?.compatible && (
          <label>
            Imported project name (optional)
            <input
              value={projectName}
              onChange={(event) => setProjectName(event.target.value)}
              placeholder={
                inspect.data.project_name ?? "Use package project name"
              }
            />
          </label>
        )}

        {(inspect.error || importPackage.error) && (
          <p className="form-error">
            {(inspect.error ?? importPackage.error)?.message}
          </p>
        )}

        <div className="modal-actions">
          <button type="button" className="secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            disabled={
              !file || !inspect.data?.compatible || importPackage.isPending
            }
            onClick={() => importPackage.mutate()}
          >
            {importPackage.isPending
              ? "Importing project…"
              : "Import as new project"}
          </button>
        </div>
      </section>
    </div>
  );
}
