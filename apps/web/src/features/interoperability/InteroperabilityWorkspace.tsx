import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

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
  const [includeGeneratedArtifacts, setIncludeGeneratedArtifacts] = useState(true);
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
        throw new Error("Inspect a compatible exchange package before importing it");
      }
      return importProjectExchange(inspectionFile, importProjectName || undefined);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["projects"] });
      await queryClient.invalidateQueries({ queryKey: ["project-summaries"] });
    },
  });

  useEffect(() => {
    setImportProjectName(inspectMutation.data?.project_name ?? "");
  }, [inspectMutation.data]);

  return (
    <section className="feature-workspace">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Phase 9</p>
          <h3>Project interoperability</h3>
          <p>
            Export, inspect, and import versioned ReefVision project packages. Imports
            always create a new project with remapped record IDs; they never overwrite
            the currently open project.
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
              checked={includeGeneratedArtifacts}
              onChange={(event) => setIncludeGeneratedArtifacts(event.target.checked)}
            />
            Include raster masks and generated training artifacts
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={includeModelWeights}
              onChange={(event) => setIncludeModelWeights(event.target.checked)}
            />
            Include registered model weights
          </label>
          <p>
            Media and raster masks are recommended for a reopenable round trip. Model
            weights remain optional because they can be large and may have separate
            redistribution licenses.
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
          <h4>Inspect and import package</h4>
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
                <strong>{inspectMutation.data.compatible ? "Yes" : "No"}</strong>
              </p>
              <p>Project: {inspectMutation.data.project_name ?? "Unknown"}</p>
              <p>Format: {inspectMutation.data.format_version ?? "Unknown"}</p>
              <p>Media/artifact files: {inspectMutation.data.included_media_count}</p>
              <p>
                Records:{" "}
                {Object.entries(inspectMutation.data.section_counts)
                  .map(([name, count]) => `${name} ${count}`)
                  .join(" · ")}
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
              {inspectMutation.data.compatible && (
                <>
                  <label>
                    New project name
                    <input
                      value={importProjectName}
                      onChange={(event) => setImportProjectName(event.target.value)}
                      placeholder={inspectMutation.data.project_name ?? "Imported project"}
                    />
                  </label>
                  <button
                    type="button"
                    onClick={() => importMutation.mutate()}
                    disabled={importMutation.isPending}
                  >
                    {importMutation.isPending ? "Importing..." : "Import as new project"}
                  </button>
                </>
              )}
            </>
          )}
          {inspectMutation.error && (
            <p className="form-error">{inspectMutation.error.message}</p>
          )}
          {importMutation.error && (
            <p className="form-error">{importMutation.error.message}</p>
          )}
          {importMutation.data && (
            <div>
              <p>
                Imported <strong>{importMutation.data.project_name}</strong> as a new
                project.
              </p>
              <p>
                Remapped {importMutation.data.remapped_id_count} record IDs and restored{" "}
                {importMutation.data.restored_file_count} managed files.
              </p>
              <p>
                New project ID: <code>{importMutation.data.project_id}</code>
              </p>
              {importMutation.data.warnings.length > 0 && (
                <ul>
                  {importMutation.data.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>

        <div className="panel-card">
          <h4>Exchange history</h4>
          {packagesQuery.data?.length ? (
            <ul className="record-list">
              {packagesQuery.data.map((item) => (
                <li key={item.id}>
                  <strong>{item.status}</strong> · {item.direction} · format {item.format_version}
                  <br />
                  <code>{item.manifest_sha256.slice(0, 12) || "pending"}</code>
                  {item.status === "complete" && item.direction === "export" && (
                    <>
                      {" · "}
                      <a href={projectExchangeDownloadUrl(item.id)}>Download ZIP</a>
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
