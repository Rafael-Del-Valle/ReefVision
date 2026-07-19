import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import type { JobRecord, Project } from "../../api/client";
import {
  getLifecycleJob,
  queueProjectArchive,
  queueProjectArchiveImport,
  queueProjectDuplicate,
  queueProjectStorageMigration,
  restoreArchivedProject,
  updateProjectLifecycle,
  verifyProjectArchive,
} from "./projectLifecycleApi";

function jobIsActive(job: JobRecord | undefined): boolean {
  return Boolean(
    job &&
    [
      "queued",
      "blocked",
      "running",
      "pause_requested",
      "paused",
      "cancel_requested",
    ].includes(job.status),
  );
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  if (value < 1024 * 1024 * 1024) {
    return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
  }
  return `${(value / (1024 * 1024 * 1024)).toFixed(2)} GiB`;
}

function JobStatusCard({ job }: { job: JobRecord }) {
  const result = job.result_json ?? {};
  const progress =
    job.progress_total > 0
      ? Math.min(
          100,
          Math.round((job.progress_current / job.progress_total) * 100),
        )
      : 0;
  return (
    <article className="dashboard-card">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Lifecycle job</p>
          <h4>{job.job_type.replaceAll("_", " ")}</h4>
        </div>
        <span>{job.status}</span>
      </div>
      <progress value={job.progress_current} max={job.progress_total || 1} />
      <p>{progress}% complete</p>
      {job.error_message && <p className="form-error">{job.error_message}</p>}
      {typeof result.archive_path === "string" && (
        <p>
          Archive: <code>{result.archive_path}</code>
        </p>
      )}
      {typeof result.new_storage_root === "string" && (
        <p>
          New storage root: <code>{result.new_storage_root}</code>
        </p>
      )}
      {typeof result.project_name === "string" && (
        <p>
          Created project: <strong>{result.project_name}</strong>
        </p>
      )}
    </article>
  );
}

export function ProjectLifecyclePanel({ project }: { project: Project }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(project.name);
  const [slug, setSlug] = useState(project.slug);
  const [description, setDescription] = useState(project.description ?? "");
  const [duplicateName, setDuplicateName] = useState(`${project.name} Copy`);
  const [duplicateSlug, setDuplicateSlug] = useState("");
  const [archiveNotes, setArchiveNotes] = useState("");
  const [migrationPath, setMigrationPath] = useState(
    `${project.storage_root}-migrated`,
  );
  const [migrationMode, setMigrationMode] = useState<"move" | "copy">("move");
  const [archivePath, setArchivePath] = useState("");
  const [importName, setImportName] = useState("");
  const [importSlug, setImportSlug] = useState("");
  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  useEffect(() => {
    setName(project.name);
    setSlug(project.slug);
    setDescription(project.description ?? "");
    setDuplicateName(`${project.name} Copy`);
    setMigrationPath(`${project.storage_root}-migrated`);
  }, [project]);

  const job = useQuery({
    queryKey: ["project-lifecycle-job", activeJobId],
    queryFn: () => getLifecycleJob(activeJobId as string),
    enabled: Boolean(activeJobId),
    refetchInterval: (query) => (jobIsActive(query.state.data) ? 1000 : false),
  });

  useEffect(() => {
    if (!job.data || jobIsActive(job.data)) return;
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: ["project", project.id] }),
      queryClient.invalidateQueries({ queryKey: ["project_summaries"] }),
      queryClient.invalidateQueries({
        queryKey: ["project-images", project.id],
      }),
    ]);
  }, [job.data, project.id, queryClient]);

  const update = useMutation({
    mutationFn: () =>
      updateProjectLifecycle(project.id, {
        name,
        slug,
        description: description || null,
      }),
    onSuccess: async (saved) => {
      queryClient.setQueryData(["project", project.id], saved);
      await queryClient.invalidateQueries({ queryKey: ["project_summaries"] });
    },
  });
  const archive = useMutation({
    mutationFn: () => queueProjectArchive(project.id, archiveNotes),
    onSuccess: (result) => setActiveJobId(result.job.id),
  });
  const duplicate = useMutation({
    mutationFn: () =>
      queueProjectDuplicate(project.id, {
        name: duplicateName,
        slug: duplicateSlug || undefined,
      }),
    onSuccess: (result) => setActiveJobId(result.job.id),
  });
  const migrate = useMutation({
    mutationFn: () =>
      queueProjectStorageMigration(project.id, {
        destination_relative_path: migrationPath,
        mode: migrationMode,
      }),
    onSuccess: (result) => setActiveJobId(result.job.id),
  });
  const verify = useMutation({
    mutationFn: () => verifyProjectArchive(archivePath),
  });
  const importArchive = useMutation({
    mutationFn: () =>
      queueProjectArchiveImport({
        archive_path: archivePath,
        name: importName || undefined,
        slug: importSlug || undefined,
        restore_as_active: true,
      }),
    onSuccess: (result) => setActiveJobId(result.job.id),
  });
  const restore = useMutation({
    mutationFn: () => restoreArchivedProject(project.id),
    onSuccess: async (result) => {
      queryClient.setQueryData(["project", project.id], result.project);
      await queryClient.invalidateQueries({ queryKey: ["project_summaries"] });
    },
  });

  const actionError = useMemo(
    () =>
      update.error ??
      archive.error ??
      duplicate.error ??
      migrate.error ??
      verify.error ??
      importArchive.error ??
      restore.error,
    [
      archive.error,
      duplicate.error,
      importArchive.error,
      migrate.error,
      restore.error,
      update.error,
      verify.error,
    ],
  );

  return (
    <section className="dashboard-panel" data-testid="project-lifecycle-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Project lifecycle</p>
          <h3>Identity, duplication, archives, and storage</h3>
          <span>
            Safely rename, duplicate, archive, import, restore, or move a
            complete ReefVision project with schema and checksum verification.
          </span>
        </div>
        <span>{project.archived_at ? "Archived" : "Active"}</span>
      </div>

      {actionError && <p className="form-error">{actionError.message}</p>}
      {project.archived_at && (
        <div className="editor-message error">
          <p>
            This project is archived and hidden from the normal project list.
          </p>
          <button
            type="button"
            disabled={restore.isPending}
            onClick={() => restore.mutate()}
          >
            {restore.isPending ? "Restoring..." : "Restore project"}
          </button>
        </div>
      )}

      <div className="dashboard-grid">
        <article className="dashboard-card">
          <h4>Rename and describe</h4>
          <label>
            Name
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label>
            Slug
            <input
              value={slug}
              onChange={(event) => setSlug(event.target.value)}
            />
          </label>
          <label>
            Description
            <textarea
              rows={5}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </label>
          <button
            type="button"
            disabled={!name.trim() || !slug.trim() || update.isPending}
            onClick={() => update.mutate()}
          >
            {update.isPending ? "Saving..." : "Save project identity"}
          </button>
          {update.isSuccess && <p className="form-success">Project updated.</p>}
        </article>

        <article className="dashboard-card">
          <h4>Duplicate complete project</h4>
          <p>
            Creates a portable archive, remaps every project-owned identifier
            and managed path, repairs immutable checksums, then imports it as a
            new project.
          </p>
          <label>
            Duplicate name
            <input
              value={duplicateName}
              onChange={(event) => setDuplicateName(event.target.value)}
            />
          </label>
          <label>
            Optional slug
            <input
              value={duplicateSlug}
              placeholder="Generated when blank"
              onChange={(event) => setDuplicateSlug(event.target.value)}
            />
          </label>
          <button
            type="button"
            disabled={!duplicateName.trim() || duplicate.isPending}
            onClick={() => duplicate.mutate()}
          >
            {duplicate.isPending ? "Queuing..." : "Duplicate project"}
          </button>
        </article>

        <article className="dashboard-card">
          <h4>Portable full-project archive</h4>
          <p>
            Includes the reachable database graph, schema signature, Alembic
            revision, immutable snapshots, and all managed files with SHA-256
            checksums.
          </p>
          <label>
            Archive notes
            <textarea
              rows={4}
              value={archiveNotes}
              onChange={(event) => setArchiveNotes(event.target.value)}
            />
          </label>
          <button
            type="button"
            disabled={archive.isPending}
            onClick={() => archive.mutate()}
          >
            {archive.isPending ? "Queuing..." : "Create project archive"}
          </button>
        </article>

        <article className="dashboard-card">
          <h4>Storage migration</h4>
          <p>
            Copies every managed file, rewrites project-owned database paths,
            commits atomically, then optionally removes the old project
            directory.
          </p>
          <label>
            New relative storage root
            <input
              value={migrationPath}
              onChange={(event) => setMigrationPath(event.target.value)}
            />
          </label>
          <label>
            Migration mode
            <select
              value={migrationMode}
              onChange={(event) =>
                setMigrationMode(event.target.value as "move" | "copy")
              }
            >
              <option value="move">Move and remove old directory</option>
              <option value="copy">Copy and retain old directory</option>
            </select>
          </label>
          <button
            type="button"
            disabled={!migrationPath.trim() || migrate.isPending}
            onClick={() => migrate.mutate()}
          >
            {migrate.isPending ? "Queuing..." : "Migrate storage"}
          </button>
        </article>
      </div>

      <article className="dashboard-card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Archive import</p>
            <h4>Verify and restore another project archive</h4>
          </div>
        </div>
        <div className="dashboard-grid compact-grid">
          <label>
            Archive path
            <input
              value={archivePath}
              placeholder="archives/projects/...reefvision-project.zip"
              onChange={(event) => {
                setArchivePath(event.target.value);
                verify.reset();
              }}
            />
          </label>
          <label>
            Imported project name
            <input
              value={importName}
              placeholder="Uses archive name when blank"
              onChange={(event) => setImportName(event.target.value)}
            />
          </label>
          <label>
            Optional imported slug
            <input
              value={importSlug}
              onChange={(event) => setImportSlug(event.target.value)}
            />
          </label>
        </div>
        <div className="annotation-editor-inline-actions">
          <button
            type="button"
            className="secondary"
            disabled={!archivePath.trim() || verify.isPending}
            onClick={() => verify.mutate()}
          >
            {verify.isPending ? "Verifying..." : "Verify archive"}
          </button>
          <button
            type="button"
            disabled={
              !verify.data?.valid ||
              importArchive.isPending ||
              !archivePath.trim()
            }
            onClick={() => importArchive.mutate()}
          >
            {importArchive.isPending ? "Queuing..." : "Import verified archive"}
          </button>
        </div>
        {verify.data && (
          <div>
            <div className="version-preview-metrics">
              <span>{verify.data.valid ? "Valid" : "Invalid"}</span>
              <span>{verify.data.record_count} records</span>
              <span>{verify.data.file_count} files</span>
              <span>{formatBytes(verify.data.total_file_bytes)}</span>
            </div>
            <p>
              Source project: {verify.data.source_project_name ?? "Unknown"} ·
              schema {verify.data.source_schema_revision ?? "Unknown"}
            </p>
            {verify.data.blockers.map((blocker) => (
              <p key={blocker} className="form-error">
                {blocker}
              </p>
            ))}
            {verify.data.warnings.map((warning) => (
              <p key={warning} className="form-warning">
                {warning}
              </p>
            ))}
          </div>
        )}
      </article>

      {job.data && <JobStatusCard job={job.data} />}
    </section>
  );
}
