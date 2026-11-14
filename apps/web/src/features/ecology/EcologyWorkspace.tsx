import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { getAnnotationSession, getImages } from "../../api/client";
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "../../components/ui/AsyncState";
import type { MaskAnnotationRecord } from "../annotation-editor/types";
import { listMeasurementRuns } from "../video/biologicalMovementApi";
import {
  ecologyCsv,
  getCandidates,
  getRegistry,
  linkEvidence,
  saveOrganism,
  type Identity,
  type OrganismKind,
  type Registry,
} from "./ecologyApi";

function IdentityForm({
  projectId,
  identity,
  colonies,
  onSaved,
}: {
  projectId: string;
  identity?: Identity;
  colonies: Identity[];
  onSaved: () => Promise<void>;
}) {
  const [kind, setKind] = useState<OrganismKind>(identity?.kind ?? "colony");
  const mutation = useMutation({
    mutationFn: (values: FormData) => {
      const value = (name: string) => String(values.get(name) ?? "").trim();
      return saveOrganism(
        projectId,
        identity?.organism_key ?? value("organism"),
        {
          kind,
          reason: value("reason"),
          parent_colony_key:
            kind === "fragment" ? value("parent") || null : null,
          experimental_unit_type: value("unitType") || null,
          experimental_unit_id: value("unitId") || null,
        },
        identity,
      );
    },
    onSuccess: onSaved,
  });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    mutation.mutate(new FormData(event.currentTarget));
  }

  const title = identity ? "Revise organism" : "Register organism";
  return (
    <form className="management-card" aria-label={title} onSubmit={submit}>
      {!identity && (
        <label>
          Organism ID
          <input
            name="organism"
            required
            maxLength={100}
            pattern="[A-Za-z0-9][A-Za-z0-9._\-]*"
          />
        </label>
      )}
      <label>
        Organism type
        <select
          value={kind}
          onChange={(event) => setKind(event.target.value as OrganismKind)}
        >
          <option value="colony">Colony</option>
          <option value="fragment">Fragment</option>
          <option value="individual">Individual</option>
        </select>
      </label>
      {kind === "fragment" && (
        <label>
          Parent colony
          <select
            name="parent"
            defaultValue={identity?.parent_colony_key ?? ""}
          >
            <option value="">Unspecified</option>
            {colonies
              .filter((row) => row.organism_key !== identity?.organism_key)
              .map((row) => (
                <option key={row.id} value={row.organism_key}>
                  {row.organism_key}
                </option>
              ))}
          </select>
        </label>
      )}
      <details>
        <summary>Experimental unit</summary>
        <p className="annotation-helper">
          Record a biological sampling unit such as a tank or colony. Supply
          both fields when recording a unit.
        </p>
        <label>
          Unit type
          <input
            name="unitType"
            maxLength={100}
            defaultValue={identity?.experimental_unit_type ?? ""}
          />
        </label>
        <label>
          Unit ID
          <input
            name="unitId"
            maxLength={150}
            defaultValue={identity?.experimental_unit_id ?? ""}
          />
        </label>
      </details>
      <label>
        {identity ? "Revision reason" : "Registration reason"}
        <input name="reason" required minLength={3} maxLength={500} />
      </label>
      <button type="submit" disabled={mutation.isPending}>
        {mutation.isPending ? "Saving…" : title}
      </button>
      {mutation.isError && (
        <p className="form-error" role="alert">
          {mutation.error.message}
        </p>
      )}
    </form>
  );
}

function EvidenceForm({
  projectId,
  identity,
  registry,
  refresh,
}: {
  projectId: string;
  identity: Identity;
  registry: Registry;
  refresh: () => Promise<void>;
}) {
  const [mode, setMode] = useState<"image" | "annotation" | "calibration">(
    "image",
  );
  const [filename, setFilename] = useState("");
  const [page, setPage] = useState(1);
  const [imageId, setImageId] = useState("");
  const [imageLinkId, setImageLinkId] = useState("");
  const links = registry.image_evidence_links.filter(
    (row) => row.organism_key === identity.organism_key,
  );
  const currentLinks = links.filter(
    (row) => row.identity_revision === identity.revision,
  );
  const imageLink = currentLinks.find((row) => row.id === imageLinkId);
  const annotationLinks = registry.annotation_evidence_links.filter((row) =>
    currentLinks.some((link) => link.id === row.image_evidence_id),
  );
  const calibrated = new Set(
    registry.calibration_evidence_links.map(
      (row) => row.annotation_evidence_id,
    ),
  );
  const images = useQuery({
    queryKey: ["ecology-image-picker", projectId, filename, page],
    queryFn: ({ signal }) =>
      getImages(projectId, { page, pageSize: 25, filename }, signal),
    enabled: mode === "image",
  });
  const annotations = useQuery({
    queryKey: ["ecology-annotation-picker", projectId, imageLink?.image_id],
    queryFn: ({ signal }) => getAnnotationSession(imageLink!.image_id, signal),
    enabled: mode === "annotation" && Boolean(imageLink),
  });
  const session = annotations.data as typeof annotations.data & {
    mask_annotations?: MaskAnnotationRecord[];
  };
  const className = (id: string | null) =>
    session?.label_classes.find((row) => row.id === id)?.name ?? "Unclassified";
  const options =
    session?.image.annotation_status === "reviewed"
      ? [
          ...session.annotations
            .filter((row) => row.source_type === "human" && !row.deleted_at)
            .map((row) => ({ ...row, kind: "box" as const })),
          ...(session.mask_annotations ?? [])
            .filter(
              (row) =>
                row.source_type === "human" &&
                row.status === "verified" &&
                !row.deleted_at,
            )
            .map((row) => ({ ...row, kind: "mask" as const })),
        ]
      : [];
  const mutation = useMutation({
    mutationFn: (data: FormData) => {
      const reason = String(data.get("reason") ?? "").trim();
      if (mode === "image" && imageId)
        return linkEvidence(projectId, identity.organism_key, {
          action: "image-evidence",
          image_id: imageId,
          expected_identity_revision: identity.revision,
          reason,
        });
      const selected = String(data.get("source") ?? "");
      const annotation = options.find((row) => row.id === selected);
      if (mode === "annotation" && imageLink && annotation)
        return linkEvidence(projectId, identity.organism_key, {
          action: "annotation-evidence",
          image_evidence_id: imageLink.id,
          annotation_kind: annotation.kind,
          annotation_id: annotation.id,
          expected_annotation_revision: annotation.revision,
          reason,
        });
      const link = annotationLinks.find((row) => row.id === selected);
      if (mode === "calibration" && link && data.get("confirm"))
        return linkEvidence(projectId, identity.organism_key, {
          action: "calibration-evidence",
          annotation_evidence_id: link.id,
          expected_annotation_sha256: link.annotation_sha256,
          confirm_source_calibration: true,
          reason,
        });
      throw new Error("Select applicable evidence and confirm its source.");
    },
    onSuccess: refresh,
  });
  const eligibleAnnotations = annotationLinks.filter(
    (row) => !calibrated.has(row.id),
  );
  const available =
    mode === "image"
      ? Boolean(imageId)
      : mode === "annotation"
        ? options.length > 0
        : eligibleAnnotations.length > 0;

  return (
    <form
      className="management-card"
      aria-label="Link observation evidence"
      onSubmit={(event) => {
        event.preventDefault();
        mutation.mutate(new FormData(event.currentTarget));
      }}
    >
      <label>
        Evidence to link
        <select
          value={mode}
          disabled={mutation.isPending}
          onChange={(event) => {
            setMode(event.target.value as typeof mode);
            mutation.reset();
          }}
        >
          <option value="image">Source image</option>
          <option value="annotation">Reviewed annotation</option>
          <option value="calibration">Source calibration</option>
        </select>
      </label>
      {mode === "image" && (
        <>
          <label>
            Filter by filename
            <input
              type="search"
              value={filename}
              onChange={(event) => {
                setFilename(event.target.value);
                setImageId("");
                setPage(1);
              }}
            />
          </label>
          <label>
            Source image
            <select
              value={imageId}
              onChange={(event) => setImageId(event.target.value)}
              required
            >
              <option value="">Choose an image</option>
              {images.data?.items.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.original_filename}
                </option>
              ))}
            </select>
          </label>
          {images.data && images.data.pages > 1 && (
            <div className="annotation-editor-inline-actions">
              <button
                type="button"
                className="secondary"
                disabled={page === 1}
                onClick={() => {
                  setImageId("");
                  setPage(page - 1);
                }}
              >
                Previous images
              </button>
              <span>
                Page {page} of {images.data.pages}
              </span>
              <button
                type="button"
                className="secondary"
                disabled={page >= images.data.pages}
                onClick={() => {
                  setImageId("");
                  setPage(page + 1);
                }}
              >
                Next images
              </button>
            </div>
          )}
        </>
      )}
      {mode === "annotation" && (
        <>
          <label>
            Linked image
            <select
              value={imageLinkId}
              onChange={(event) => setImageLinkId(event.target.value)}
              required
            >
              <option value="">Choose a linked image</option>
              {currentLinks.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.reason} ({row.image_id.slice(0, 8)})
                </option>
              ))}
            </select>
          </label>
          {!imageLink ? (
            <p>Link an image to this identity revision first.</p>
          ) : (
            !annotations.isPending &&
            !options.length && (
              <p>
                No eligible annotations. Save a human annotation and mark the
                source image reviewed.
              </p>
            )
          )}
          <label>
            Reviewed geometry
            <select name="source" key={imageLinkId} required>
              <option value="">Choose a reviewed box or mask</option>
              {options.map((row) => (
                <option key={row.id} value={row.id}>
                  {className(row.label_class_id)} · {row.kind} ·{" "}
                  {row.id.slice(0, 8)} · revision {row.revision}
                </option>
              ))}
            </select>
          </label>
        </>
      )}
      {mode === "calibration" && (
        <>
          <p>
            Save the source image's calibration in the image editor before
            linking its snapshot.
          </p>
          <label>
            Linked annotation
            <select name="source" required>
              <option value="">Choose an annotation</option>
              {eligibleAnnotations.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.annotation_kind} {row.annotation_id.slice(0, 8)} ·
                  revision {row.annotation_revision}
                </option>
              ))}
            </select>
          </label>
          <label className="checkbox-row">
            <input type="checkbox" name="confirm" required /> I reviewed the
            source-image calibration.
          </label>
        </>
      )}
      <label>
        Linking reason
        <input name="reason" required minLength={3} maxLength={500} />
      </label>
      <button type="submit" disabled={mutation.isPending || !available}>
        {mutation.isPending ? "Linking…" : "Link evidence"}
      </button>
      {mutation.isSuccess && (
        <p role="status">Evidence linked to revision {identity.revision}.</p>
      )}
      {(mutation.error ||
        (mode === "image"
          ? images.error
          : mode === "annotation"
            ? annotations.error
            : null)) && (
        <p className="form-error" role="alert">
          {(mutation.error ?? images.error ?? annotations.error)?.message}
        </p>
      )}
    </form>
  );
}

function LongitudinalCandidates({ projectId }: { projectId: string }) {
  const result = useQuery({
    queryKey: ["ecology-candidates", projectId],
    queryFn: ({ signal }) => getCandidates(projectId, signal),
  });
  return (
    <section
      aria-label="Longitudinal measurement candidates"
      className="management-card"
    >
      <h3>Projected endpoint changes</h3>
      <p>
        Scientist review required. These comparisons use calibrated 2D geometry
        from source images.
      </p>
      <div className="annotation-editor-inline-actions">
        <a
          href={ecologyCsv(
            projectId,
            "calibrated-measurement-candidates/measurements.csv",
          )}
        >
          Measurements CSV
        </a>
        <a
          href={ecologyCsv(
            projectId,
            "calibrated-measurement-candidates/report-series.csv",
          )}
        >
          Sampling and QC CSV
        </a>
        <a
          href={ecologyCsv(
            projectId,
            "calibrated-measurement-candidates/population.csv",
          )}
        >
          Declared-unit summaries CSV
        </a>
      </div>
      {result.isPending && <LoadingState title="Checking observations" />}
      {result.isError && (
        <ErrorState
          title="Unavailable measurements"
          message={result.error.message}
          onRetry={() => void result.refetch()}
        />
      )}
      {result.data && (
        <>
          {result.data.projected_endpoint_changes.length ? (
            <ul>
              {result.data.projected_endpoint_changes.map((row) => (
                <li key={`${row.organism_key}-${row.metric}`}>
                  <strong>
                    {row.organism_key} · {row.metric.replaceAll("_", " ")}
                  </strong>
                  <p>
                    {row.baseline_capture_timestamp_utc} to{" "}
                    {row.final_capture_timestamp_utc} · {row.baseline_value} to{" "}
                    {row.final_value} {row.unit} · Change {row.absolute_change}{" "}
                    {row.unit} in {row.elapsed_days} days
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="No comparable timepoints"
              description="Link reviewed observations on two UTC dates using the same organism identity revision and compatible calibration."
            />
          )}
          {result.data.exclusions.length > 0 && (
            <ul aria-label="Excluded calibration evidence">
              {result.data.exclusions.map((row) => (
                <li key={row.calibration_evidence_id}>
                  {row.reason.replaceAll("_", " ")} (
                  {row.calibration_evidence_id})
                </li>
              ))}
            </ul>
          )}
          <details>
            <summary>Input provenance</summary>
            <p>
              {result.data.candidate_count} calibrated candidate measurements
            </p>
            <code>{result.data.input_sha256}</code>
          </details>
        </>
      )}
    </section>
  );
}

function ProjectPoseMeasurements({
  projectId,
  onOpenVideo,
}: {
  projectId: string;
  onOpenVideo?: (videoId: string) => void;
}) {
  const runs = useQuery({
    queryKey: ["pose-measurement-runs", projectId],
    queryFn: ({ signal }) => listMeasurementRuns(projectId, signal),
  });
  if (runs.isPending) return <LoadingState title="Finding pose measurements" />;
  if (runs.isError) {
    return (
      <ErrorState
        title="Pose measurements unavailable"
        message={runs.error.message}
        onRetry={() => void runs.refetch()}
      />
    );
  }
  const completed = runs.data.filter((run) => run.status === "completed");
  return (
    <section className="management-card" aria-label="Pose-derived measurements">
      <h3>Pose-derived measurements</h3>
      <p>
        Review movement events in Video &amp; tracking. Each run retains a video
        identity revision and uses a pose-derived method. Longitudinal
        comparisons above use source-image geometry.
      </p>
      {completed.length === 0 && (
        <p>
          No completed pose measurement runs. Create one in the source video's
          Biological movement workspace.
        </p>
      )}
      {completed.map((run) => (
        <article key={run.id} className="panel-card">
          <h4>
            {run.definitions_json
              .map((definition) => definition.name)
              .join(", ") || "Anatomical measurements"}
          </h4>
          <p>
            {run.verification_state === "scientific"
              ? "Scientist-reviewed identity inputs"
              : "Exploratory identity inputs"}{" "}
            · Identity revision {run.source_identity_run_revision}
          </p>
          {onOpenVideo && (
            <button
              type="button"
              className="secondary"
              onClick={() => onOpenVideo(run.video_id)}
            >
              Open source video
            </button>
          )}
          <details>
            <summary>Run provenance</summary>
            <p>
              Run <code>{run.id}</code>
            </p>
            <p>
              Identity run <code>{run.source_identity_run_id}</code>
            </p>
            {run.result_sha256 && (
              <p>
                Result SHA-256 <code>{run.result_sha256}</code>
              </p>
            )}
          </details>
        </article>
      ))}
    </section>
  );
}

export function EcologyWorkspace({
  projectId,
  onOpenVideo,
}: {
  projectId: string;
  onOpenVideo?: (videoId: string) => void;
}) {
  const client = useQueryClient();
  const [view, setView] = useState<"registry" | "longitudinal" | "pose">(
    "registry",
  );
  const [selected, setSelected] = useState("");
  const query = useQuery({
    queryKey: ["ecology-registry", projectId],
    queryFn: ({ signal }) => getRegistry(projectId, signal),
  });
  async function refresh() {
    await Promise.all([
      client.invalidateQueries({ queryKey: ["ecology-registry", projectId] }),
      client.invalidateQueries({ queryKey: ["ecology-candidates", projectId] }),
    ]);
  }
  const current =
    query.data?.identities.find((row) => row.organism_key === selected) ??
    query.data?.identities[0];
  return (
    <section className="feature-workspace" aria-label="Ecology workspace">
      <div className="section-heading">
        <h2>Organisms and longitudinal observations</h2>
      </div>
      <div className="annotation-editor-inline-actions">
        <button
          type="button"
          className="secondary"
          aria-pressed={view === "registry"}
          onClick={() => setView("registry")}
        >
          Identity registry
        </button>
        <button
          type="button"
          className="secondary"
          aria-pressed={view === "longitudinal"}
          onClick={() => setView("longitudinal")}
        >
          Longitudinal candidates
        </button>
        <button
          type="button"
          className="secondary"
          aria-pressed={view === "pose"}
          onClick={() => setView("pose")}
        >
          Pose measurements
        </button>
      </div>
      {view === "longitudinal" ? (
        <LongitudinalCandidates projectId={projectId} />
      ) : view === "pose" ? (
        <ProjectPoseMeasurements
          projectId={projectId}
          onOpenVideo={onOpenVideo}
        />
      ) : (
        <>
          {query.isPending && (
            <LoadingState title="Loading identity registry" />
          )}
          {query.isError && (
            <ErrorState
              title="Identity registry unavailable"
              message={query.error.message}
              onRetry={() => void query.refetch()}
            />
          )}
          {query.data && (
            <>
              <p>
                Register a stable study ID and link observations that you have
                inspected. Linked evidence remains provisional until scientific
                review.
              </p>
              <details open={!current} className="management-card">
                <summary>Register an organism</summary>
                <IdentityForm
                  projectId={projectId}
                  colonies={query.data.identities.filter(
                    (row) => row.kind === "colony",
                  )}
                  onSaved={refresh}
                />
              </details>
              {!current ? (
                <EmptyState
                  title="No registered organisms"
                  description="Start with the study ID from your field notes."
                />
              ) : (
                <>
                  <label>
                    Organism
                    <select
                      value={current.organism_key}
                      onChange={(event) => setSelected(event.target.value)}
                    >
                      {query.data.identities.map((row) => (
                        <option value={row.organism_key} key={row.id}>
                          {row.organism_key}
                        </option>
                      ))}
                    </select>
                  </label>
                  <section className="management-card">
                    <h3>{current.organism_key}</h3>
                    <p>
                      Revision {current.revision} · {current.kind}.{" "}
                      {current.reason}
                    </p>
                    <details>
                      <summary>Identity history and revisions</summary>
                      <ul>
                        {query.data.identity_history
                          .filter(
                            (row) => row.organism_key === current.organism_key,
                          )
                          .map((row) => (
                            <li key={row.id}>
                              Revision {row.revision} · {row.created_at} ·{" "}
                              {row.reason}
                            </li>
                          ))}
                      </ul>
                      <IdentityForm
                        key={current.id}
                        identity={current}
                        projectId={projectId}
                        colonies={query.data.identities.filter(
                          (row) => row.kind === "colony",
                        )}
                        onSaved={refresh}
                      />
                    </details>
                    <EvidenceForm
                      key={current.id}
                      projectId={projectId}
                      identity={current}
                      registry={query.data}
                      refresh={refresh}
                    />
                    <details>
                      <summary>Source references</summary>
                      <ul>
                        {query.data.image_evidence_links
                          .filter(
                            (row) => row.organism_key === current.organism_key,
                          )
                          .map((row) => (
                            <li key={row.id}>
                              Image {row.image_id} · identity revision{" "}
                              {row.identity_revision} · {row.reason}
                              <div>
                                SHA-256 <code>{row.image_sha256}</code>
                              </div>
                              <ul>
                                {query.data.annotation_evidence_links
                                  .filter(
                                    (annotation) =>
                                      annotation.image_evidence_id === row.id,
                                  )
                                  .map((annotation) => (
                                    <li key={annotation.id}>
                                      {annotation.annotation_kind}{" "}
                                      {annotation.annotation_id} · revision{" "}
                                      {annotation.annotation_revision}
                                      {query.data.calibration_evidence_links
                                        .filter(
                                          (calibration) =>
                                            calibration.annotation_evidence_id ===
                                            annotation.id,
                                        )
                                        .map((calibration) => (
                                          <div key={calibration.id}>
                                            Calibration SHA-256{" "}
                                            <code>
                                              {calibration.calibration_sha256}
                                            </code>
                                          </div>
                                        ))}
                                    </li>
                                  ))}
                              </ul>
                            </li>
                          ))}
                      </ul>
                    </details>
                  </section>
                </>
              )}
              <a href={ecologyCsv(projectId, "identity-registry/history.csv")}>
                Identity history CSV
              </a>
            </>
          )}
        </>
      )}
    </section>
  );
}
