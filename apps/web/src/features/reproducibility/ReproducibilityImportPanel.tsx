import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import {
  importResearchPackage,
  inspectResearchPackage,
  type ResearchManifest,
} from "./reproducibilityApi";

export function ResearchManifestDetails({
  manifest,
  manifestSha,
}: {
  manifest: ResearchManifest;
  manifestSha: string | null;
}) {
  return (
    <>
      <dl>
        <dt>Proof SHA-256</dt>
        <dd>
          <code>{manifest.proof.proof_sha256}</code>
        </dd>
        <dt>Manifest SHA-256</dt>
        <dd>
          <code>{manifestSha}</code>
        </dd>
        <dt>Included source files</dt>
        <dd>{manifest.included_media_count}</dd>
      </dl>
      {manifest.omitted_sources.length > 0 ? (
        <details open>
          <summary>
            Omitted source files ({manifest.omitted_sources.length})
          </summary>
          <ul>
            {manifest.omitted_sources.map((source) => (
              <li key={source.kind + ":" + source.record_id}>
                {source.name} ({source.kind}). Requires relinking for{" "}
                {source.requires_relink_for.join(", ")}.
              </li>
            ))}
          </ul>
        </details>
      ) : (
        <p>All source files are included.</p>
      )}
    </>
  );
}

export function ReproducibilityImportPanel({
  onOpenProject,
}: {
  onOpenProject: (projectId: string) => void;
}) {
  const [file, setFile] = useState<File>();
  const [name, setName] = useState("");
  const inspect = useMutation({
    mutationFn: async (source: File) => ({
      source,
      result: await inspectResearchPackage(source),
    }),
  });
  const restore = useMutation({
    mutationFn: ({ source, title }: { source: File; title: string }) =>
      importResearchPackage(source, title),
  });
  const inspection =
    inspect.data?.source === file ? inspect.data?.result : undefined;
  const working = inspect.isPending || restore.isPending;
  const imported = restore.data;

  return (
    <section className="panel-card" aria-label="Import reproducibility package">
      <h3>Import reproducibility package</h3>
      <label>
        Choose reproducibility package
        <input
          type="file"
          accept=".zip,application/zip"
          disabled={working}
          onChange={(event) => {
            setFile(event.currentTarget.files?.[0]);
            inspect.reset();
            restore.reset();
          }}
        />
      </label>
      <button
        type="button"
        disabled={!file || working}
        onClick={() => file && inspect.mutate(file)}
      >
        {inspect.isPending ? "Verifying package…" : "Verify package"}
      </button>
      {inspection && (
        <>
          <p role="status">
            {inspection.compatible
              ? "Package verified"
              : "Package verification failed"}
          </p>
          {inspection.errors.map((error) => (
            <p key={error}>{error}</p>
          ))}
          {inspection.manifest && (
            <ResearchManifestDetails
              manifest={inspection.manifest}
              manifestSha={inspection.manifest_sha256}
            />
          )}
        </>
      )}
      {inspection?.compatible && (
        <>
          <label>
            New project name
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={inspection.project_name ?? undefined}
              maxLength={150}
            />
          </label>
          <button
            type="button"
            disabled={working}
            onClick={() =>
              file && restore.mutate({ source: file, title: name })
            }
          >
            {restore.isPending ? "Importing package…" : "Import as new project"}
          </button>
        </>
      )}
      {imported && (
        <div>
          <p role="status">Imported {imported.project_name}</p>
          <button
            type="button"
            onClick={() => onOpenProject(imported.project_id)}
          >
            Open imported project
          </button>
        </div>
      )}
      {(inspect.error || restore.error) && (
        <p role="alert">{(restore.error ?? inspect.error)?.message}</p>
      )}
    </section>
  );
}
