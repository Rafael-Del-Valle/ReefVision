import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import type { Project } from "../../api/client";
import {
  createProjectExchange,
  getProjectExchangePackages,
  importProjectExchange,
  inspectProjectExchange,
  projectExchangeDownloadUrl,
} from "./projectExchangeApi";

interface InteroperabilityWorkspaceProps {
  project: Project;
}

export function InteroperabilityWorkspace({
  project,
}: InteroperabilityWorkspaceProps) {
  const queryClient = useQueryClient();
  const [includeMedia, setIncludeMedia] = useState(true);
  const [includeModelWeights, setIncludeModelWeights] = useState(false);
  const [includeGeneratedArtifacts, setIncludeGeneratedArtifacts] =
    useState(false);
  const [inspectionFile, setInspectionFile] = useState<File | null>(null);
  const [importProjectName, setImportProjectName] = useState("");

  const packagesQuery = useQuery({
    queryKey: ["project-exchange-packages", project.id],
    queryFn: ({ signal }) => getProjectExchangePackages(project.id, signal),
    refetchInterval: 3000,
  });
  const exportMutation = useMutation({
    mutationFn: () =>
      createProjectExchange(project.id, {
        include_media: includeMedia,
        include_model_weights: includeModelWeights,
        include_generated_artifacts: includeGeneratedArtifacts,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["project-exchange-packages", project.id],
      });
    },
  });
  const inspectMutation = useMutation({
    mutationFn: () => {
      if (!inspectionFile) throw new Error("Choose an exchange ZIP first");
      return inspectProjectExchange(inspectionFile);
    },
  });
  const importMutation = useMutation({
    mutationFn: () => {
      if (!inspectionFile) throw new Error("Choose an exchange ZIP first");
      if (!inspectMutation.data?.compatible) {
        throw new Error(
          "Inspect a compatible exchange package before importing",
        );
      }
      return importProjectExchange(
        inspectionFile,
        importProjectName.trim() || undefined,
      );
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  return (
    <section className="feature-workspace">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Project exchange</p>
          <h3>Project interoperability</h3>
          <p>
            Export a versioned, checksummed ReefVision package, inspect it
            without executing package content, or import it as a new project
            with record-ID remapping. Existing projects are never overwritten.
          </p>
        </div>
      </div>

      <div className="feature-grid">
        <div className="panel-card">
          <h4>Create exchange package</h4>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={includeMedia}
              onChange={(event) => setIncludeMedia(event.target.checked)}
            />
            Include original images and videos
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={includeModelWeights}
              onChange={(event) => setIncludeModelWeights(event.target.checked)}
            />
            Include registered model weights
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={includeGeneratedArtifacts}
              onChange={(event) =>
                setIncludeGeneratedArtifacts(event.target.checked)
              }
            />
            Include generated datasets, depth maps, previews, frames, and
            training artifacts
          </label>
          <p>
            Original media, model weights, and generated artifacts are
            independent opt-ins because complete scientific projects can be much
            larger than their metadata alone. Model weights may also have
            separate redistribution licenses.
          </p>
          <button
            type="button"
            onClick={() => exportMutation.mutate()}
            disabled={exportMutation.isPending}
          >
            {exportMutation.isPending ? "Queueing..." : "Create exchange ZIP"}
          </button>
          {exportMutation.error && (
            <p className="form-error">{exportMutation.error.message}</p>
          )}
        </div>

        <div className="panel-card">
          <h4>Inspect or import exchange package</h4>
          <input
            type="file"
            accept=".zip,.reefvision.zip,application/zip"
            onChange={(event) => {
              setInspectionFile(event.target.files?.[0] ?? null);
              inspectMutation.reset();
              importMutation.reset();
            }}
          />
          <button
            type="button"
            onClick={() => inspectMutation.mutate()}
            disabled={!inspectionFile || inspectMutation.isPending}
          >
            {inspectMutation.isPending ? "Inspecting..." : "Inspect safely"}
          </button>
          {inspectMutation.data && (
            <>
              <p>
                Compatible:{" "}
                <strong>
                  {inspectMutation.data.compatible ? "Yes" : "No"}
                </strong>
              </p>
              <p>Project: {inspectMutation.data.project_name ?? "Unknown"}</p>
              <p>Format: {inspectMutation.data.format_version ?? "Unknown"}</p>
              <p>
                Original/model files:{" "}
                {inspectMutation.data.included_media_count}
              </p>
              <p>
                Generated artifacts:{" "}
                {inspectMutation.data.included_generated_artifact_count}
              </p>
              {inspectMutation.data.warnings.length > 0 && (
                <ul>
                  {inspectMutation.data.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              )}
              {inspectMutation.data.errors.length > 0 && (
                <ul className="form-error">
                  {inspectMutation.data.errors.map((error) => (
                    <li key={error}>{error}</li>
                  ))}
                </ul>
              )}
              <label>
                Imported project name (optional)
                <input
                  value={importProjectName}
                  onChange={(event) => setImportProjectName(event.target.value)}
                  placeholder={
                    inspectMutation.data.project_name ??
                    "Use package project name"
                  }
                />
              </label>
              <p className="annotation-helper">
                Import always creates a new managed project. Source UUIDs are
                remapped, exact ID references inside workflow/provenance JSON
                are remapped, packaged media is copied into the new project
                storage tree, and included generated artifacts are restored to
                their managed project-relative paths.
              </p>
              <button
                type="button"
                onClick={() => importMutation.mutate()}
                disabled={
                  !inspectionFile ||
                  !inspectMutation.data.compatible ||
                  importMutation.isPending
                }
              >
                {importMutation.isPending
                  ? "Importing..."
                  : "Import as new project"}
              </button>
            </>
          )}
          {inspectMutation.error && (
            <p className="form-error">{inspectMutation.error.message}</p>
          )}
          {importMutation.error && (
            <p className="form-error">{importMutation.error.message}</p>
          )}
          {importMutation.data && (
            <div className="annotation-selection-list">
              <div className="annotation-selection-row">
                <strong>Imported project</strong>
                <span>{importMutation.data.project_name}</span>
              </div>
              <div className="annotation-selection-row">
                <strong>Slug</strong>
                <code>{importMutation.data.project_slug}</code>
              </div>
              <div className="annotation-selection-row">
                <strong>Copied original/model files</strong>
                <span>{importMutation.data.copied_media_count}</span>
              </div>
              <div className="annotation-selection-row">
                <strong>Restored generated artifacts</strong>
                <span>
                  {importMutation.data.copied_generated_artifact_count}
                </span>
              </div>
              <div className="annotation-selection-row">
                <strong>Source manifest</strong>
                <code>
                  {importMutation.data.source_manifest_sha256.slice(0, 12)}
                </code>
              </div>
              {importMutation.data.warnings.map((warning) => (
                <p key={warning} className="annotation-helper">
                  {warning}
                </p>
              ))}
            </div>
          )}
        </div>

        <div className="panel-card">
          <h4>Exchange history</h4>
          {packagesQuery.data?.length ? (
            <ul className="record-list">
              {packagesQuery.data.map((item) => (
                <li key={item.id}>
                  <strong>{item.status}</strong> · format {item.format_version}
                  <br />
                  <code>{item.manifest_sha256.slice(0, 12) || "pending"}</code>
                  {item.status === "complete" && (
                    <>
                      {" · "}
                      <a href={projectExchangeDownloadUrl(item.id)}>
                        Download ZIP
                      </a>
                    </>
                  )}
                  {item.error_message && (
                    <p className="form-error">{item.error_message}</p>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p>No exchange packages have been created.</p>
          )}
        </div>
      </div>
    </section>
  );
}
