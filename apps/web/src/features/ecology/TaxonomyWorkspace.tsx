import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import {
  labRequest,
  type LabRole,
  type LabSession,
} from "../reviewer-lab/reviewerLabApi";
import { saveWorkflowGraph } from "../workflow-graphs/workflowGraphApi";
import type { Identity } from "./ecologyApi";
import {
  formValue,
  MoreTaxonomyRows,
  outcomes,
  ranks,
  SourceEvidence,
  submitFields,
  TaxonomyErrors,
  useTaxonomyPage,
} from "./TaxonomyFields";
import { SamplingVisits, TaxonProposals } from "./TaxonomyRecords";
import {
  detectabilityExportUrl,
  recordTaxonomy,
  type DetectabilityAssessment,
} from "./taxonomyApi";

const exclusionLabels: Record<string, string> = {
  unobserved: "Visit unobserved",
  unknown: "Observation outcome unknown",
  insufficient_observation_effort: "Observed effort below the protocol minimum",
  taxonomy_not_confirmed: "Taxonomy not confirmed",
  organism_revision_changed: "Organism revision changed",
  independent_unit_not_declared: "Independent unit not declared",
  independent_unit_type_mismatch: "Different unit type",
  shared_parent_across_units: "Parent organism shared across units",
  independent_presence_not_confirmed: "Independent presence not confirmed",
  source_unavailable: "Original source unavailable or changed",
  reused_source_bytes: "Original bytes reused across visits",
  overlapping_visits_in_unit: "Visit overlaps another in the same unit",
  insufficient_repeated_visits_in_unit: "Unit lacks a second eligible visit",
};

function RoleAccess({
  projectId,
  session,
  setSession,
  onOpenReviewerLab,
}: {
  projectId: string;
  session: LabSession | null;
  setSession: (session: LabSession | null) => void;
  onOpenReviewerLab?: () => void;
}) {
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  async function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const key = formValue(new FormData(form), "key");
    form.reset();
    setConnecting(true);
    setError(null);
    try {
      const actor = await labRequest<LabRole>(projectId, "/session", { key });
      setSession({ key, actor });
    } catch {
      setError(new Error("Enter an active Reviewer Lab key for this project."));
    } finally {
      setConnecting(false);
    }
  }

  return (
    <section aria-label="Taxonomy local role">
      {session ? (
        <div className="annotation-editor-inline-actions">
          <p role="status">
            Local role: {session.actor.name} · {session.actor.role} · revision{" "}
            {session.actor.revision}
          </p>
          <button
            type="button"
            className="secondary"
            onClick={() => setSession(null)}
          >
            Change local role
          </button>
        </div>
      ) : (
        <form
          aria-label="Connect a taxonomy role"
          onSubmit={(event) => void connect(event)}
        >
          <label>
            Reviewer Lab key
            <input
              type="password"
              name="key"
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
              required
            />
          </label>
          <div className="annotation-editor-inline-actions">
            <button type="submit" disabled={connecting}>
              Connect local role
            </button>
            {onOpenReviewerLab && (
              <button
                type="button"
                className="secondary"
                onClick={onOpenReviewerLab}
              >
                Open Reviewer lab
              </button>
            )}
          </div>
        </form>
      )}
      <TaxonomyErrors errors={[error]} />
    </section>
  );
}

function AssessmentResult({
  assessment,
  onOpenWorkflow,
}: {
  assessment: DetectabilityAssessment;
  onOpenWorkflow?: () => void;
}) {
  const queries = useQueryClient();
  const { result } = assessment;
  const save = useMutation({
    mutationFn: () =>
      saveWorkflowGraph(assessment.project_id, {
        graph_id: `detectability-${assessment.id}`,
        name: `Detectability · ${result.request.scientific_name} · ${result.request.window_start}`,
        nodes: [
          { node_id: "project", node_type: "project_source" },
          {
            node_id: "detectability",
            node_type: "detectability_assessment",
            parameters: {
              assessment_id: assessment.id,
              assessment_sha256: assessment.result_sha256,
            },
          },
        ],
        edges: [
          {
            edge_id: "project-detectability",
            source_node_id: "project",
            source_port_id: "project",
            target_node_id: "detectability",
            target_port_id: "project",
          },
        ],
      }),
    onSuccess: async () => {
      await queries.invalidateQueries({
        queryKey: ["workflow-graphs", assessment.project_id],
      });
      onOpenWorkflow?.();
    },
  });
  return (
    <section className="panel" aria-label="Saved detectability assessment">
      <h4>Known-presence detectability</h4>
      <p>
        {result.request.scientific_name} · {result.request.rank} ·{" "}
        {result.request.protocol}
      </p>
      <p>
        {result.request.window_start} through {result.request.window_end} (end
        excluded)
      </p>
      {result.estimate === null ? (
        <p role="status">Estimate withheld. {result.withhold_reason}</p>
      ) : (
        <p role="status">
          Estimated detection:{" "}
          <strong>{(100 * result.estimate).toFixed(1)}%</strong>
        </p>
      )}
      {result.confidence_interval && (
        <p>
          95% independent-unit interval:{" "}
          {(100 * result.confidence_interval.lower).toFixed(1)}% to{" "}
          {(100 * result.confidence_interval.upper).toFixed(1)}%
        </p>
      )}
      <dl>
        <dt>Independent units ({result.request.unit_type})</dt>
        <dd>{result.independent_groups}</dd>
        <dt>Eligible visits</dt>
        <dd>
          {result.eligible_visits} of {result.total_recorded_visits}
        </dd>
        <dt>Observed detections</dt>
        <dd>{result.observed_detections}</dd>
        <dt>Observed non-detections</dt>
        <dd>{result.observed_nondetections}</dd>
        <dt>Included observation effort</dt>
        <dd>{result.included_effort_seconds} seconds</dd>
        <dt>Minimum effort per visit</dt>
        <dd>{result.request.minimum_effort_seconds} seconds</dd>
        <dt>Result SHA-256</dt>
        <dd>
          <code>{assessment.result_sha256}</code>
        </dd>
        <dt>Evidence SHA-256</dt>
        <dd>
          <code>{result.evidence_sha256}</code>
        </dd>
      </dl>
      <div className="annotation-editor-inline-actions">
        <a
          className="button"
          href={detectabilityExportUrl(assessment.project_id, assessment.id)}
          download
        >
          Export detectability JSON
        </a>
        <button
          type="button"
          className="secondary"
          disabled={save.isPending}
          onClick={() => save.mutate()}
        >
          Save detectability workflow
        </button>
      </div>
      <TaxonomyErrors errors={[save.error]} />
      <details>
        <summary>Method and assumptions</summary>
        <p>
          Each independent unit contributes its detection fraction with equal
          weight. The interval uses Hoeffding’s bound over those unit-level
          fractions.
        </p>
        <ul>
          {result.assumptions.map((assumption) => (
            <li key={assumption}>{assumption}</li>
          ))}
        </ul>
      </details>
      <details>
        <summary>Independent unit results</summary>
        <ul>
          {result.groups.map((group) => (
            <li key={group.unit_id}>
              {group.unit_id} · {group.detections}/{group.eligible_visits}{" "}
              detections · {group.effort_seconds} seconds
            </li>
          ))}
        </ul>
      </details>
      <details>
        <summary>Survey evidence and exclusions</summary>
        <ol>
          {result.visits.map((row) => (
            <li key={row.id}>
              <strong>
                {row.visit.identity.organism_key} · {row.visit.started_at}
              </strong>
              <p>
                {outcomes[row.visit.outcome]} · {row.visit.effort_seconds}{" "}
                seconds ·{" "}
                {row.exclusion
                  ? (exclusionLabels[row.exclusion] ?? row.exclusion)
                  : "Included"}
              </p>
              <p>
                Recorded by {row.visit.observer.name}. Taxonomy review:{" "}
                {row.taxonomy_review?.review.reviewer.name ?? "Pending"}.
                Presence review:{" "}
                {row.presence_review?.review.reviewer.name ?? "Pending"}.
              </p>
              <SourceEvidence
                projectId={assessment.project_id}
                label="Observation source"
                source={row.visit.source}
              />
              <SourceEvidence
                projectId={assessment.project_id}
                label="Known-presence reference"
                source={row.presence_review?.review.source}
              />
            </li>
          ))}
        </ol>
      </details>
    </section>
  );
}

function Assessments({
  projectId,
  onOpenWorkflow,
}: {
  projectId: string;
  onOpenWorkflow?: () => void;
}) {
  const records = useTaxonomyPage<DetectabilityAssessment>(
    projectId,
    "assessments",
  );
  const queries = useQueryClient();
  const [selectedId, setSelectedId] = useState("");
  const assess = useMutation({
    mutationFn: (data: FormData) =>
      recordTaxonomy<DetectabilityAssessment>(projectId, "assessments", {
        scientific_name: formValue(data, "name"),
        rank: formValue(data, "rank"),
        protocol: formValue(data, "protocol"),
        unit_type: formValue(data, "unit-type"),
        minimum_effort_seconds: Number(formValue(data, "effort")),
        window_start: formValue(data, "start"),
        window_end: formValue(data, "end"),
      }),
    onSuccess: async (result) => {
      setSelectedId(result.id);
      await queries.invalidateQueries({
        queryKey: ["taxonomy", projectId, "assessments"],
      });
    },
  });
  const saved = records.data?.pages.flatMap((page) => page.items) ?? [];
  const selected =
    saved.find((item) => item.id === selectedId) ??
    (assess.data?.id === selectedId ? assess.data : undefined);
  return (
    <section aria-label="Detectability assessments">
      <h3>Detectability assessments</h3>
      <p>
        Estimate detection only for visits with reviewed evidence of known
        presence. Use one survey protocol and independent unit type.
      </p>
      <form
        className="management-card"
        aria-label="Estimate detectability"
        onSubmit={submitFields(assess.mutate)}
      >
        <label>
          Target scientific name
          <input name="name" required maxLength={150} />
        </label>
        <label>
          Target taxonomic rank
          <select name="rank">
            {ranks.map((rank) => (
              <option key={rank}>{rank}</option>
            ))}
          </select>
        </label>
        <label>
          Sampling protocol
          <input name="protocol" required maxLength={200} />
        </label>
        <label>
          Independent unit type
          <input name="unit-type" required maxLength={100} />
        </label>
        <label>
          Minimum effort (seconds)
          <input
            name="effort"
            type="number"
            min={0.000001}
            max={86400}
            step="any"
            required
          />
        </label>
        <label>
          Window start (UTC or offset)
          <input name="start" required placeholder="2026-02-02T00:00:00Z" />
        </label>
        <label>
          Window end (UTC or offset)
          <input name="end" required placeholder="2026-02-03T00:00:00Z" />
        </label>
        <button type="submit" disabled={assess.isPending}>
          Save detectability assessment
        </button>
      </form>
      {records.data?.pages[0]?.total === 0 && (
        <p>No saved detectability assessments.</p>
      )}
      <ul>
        {saved.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              className="secondary"
              aria-pressed={item.id === selectedId}
              onClick={() => setSelectedId(item.id)}
            >
              {item.result.request.scientific_name} ·{" "}
              {item.result.request.window_start} · {item.result.status}
            </button>
          </li>
        ))}
      </ul>
      <MoreTaxonomyRows {...records} label="saved assessments" />
      {selected && (
        <AssessmentResult
          key={selected.id}
          assessment={selected}
          onOpenWorkflow={onOpenWorkflow}
        />
      )}
      <TaxonomyErrors errors={[records.error, assess.error]} />
    </section>
  );
}

export function TaxonomyWorkspace({
  projectId,
  identities,
  onOpenWorkflow,
  onOpenReviewerLab,
}: {
  projectId: string;
  identities: readonly Identity[];
  onOpenWorkflow?: () => void;
  onOpenReviewerLab?: () => void;
}) {
  const [session, setSession] = useState<LabSession | null>(null);
  const [view, setView] = useState<"proposals" | "visits" | "assessments">(
    "proposals",
  );
  return (
    <section className="panel" aria-label="Taxonomy and detectability">
      <h3>Taxonomy and detectability</h3>
      <p>
        Taxon proposals and visit decisions use versioned project-local roles.
        Field authority requires separate evidence.
      </p>
      <RoleAccess
        projectId={projectId}
        session={session}
        setSession={setSession}
        onOpenReviewerLab={onOpenReviewerLab}
      />
      <div className="annotation-editor-inline-actions">
        <button
          type="button"
          className="secondary"
          aria-pressed={view === "proposals"}
          onClick={() => setView("proposals")}
        >
          Taxon proposals
        </button>
        <button
          type="button"
          className="secondary"
          aria-pressed={view === "visits"}
          onClick={() => setView("visits")}
        >
          Sampling visits
        </button>
        <button
          type="button"
          className="secondary"
          aria-pressed={view === "assessments"}
          onClick={() => setView("assessments")}
        >
          Detectability assessments
        </button>
      </div>
      {view === "proposals" && (
        <TaxonProposals
          projectId={projectId}
          identities={identities}
          session={session}
        />
      )}
      {view === "visits" && (
        <SamplingVisits projectId={projectId} session={session} />
      )}
      {view === "assessments" && (
        <Assessments projectId={projectId} onOpenWorkflow={onOpenWorkflow} />
      )}
    </section>
  );
}
