import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import type { LabSession } from "../reviewer-lab/reviewerLabApi";
import type { Identity } from "./ecologyApi";
import {
  decisions,
  formValue,
  MoreTaxonomyRows,
  outcomes,
  ranks,
  SourceEvidence,
  SourcePicker,
  submitFields,
  TaxonomyErrors,
  useTaxonomyPage,
} from "./TaxonomyFields";
import {
  pinTaxonomySource,
  recordTaxonomy,
  type DetectabilityVisit,
  type TaxonProposal,
  type TaxonReview,
  type VisitOutcome,
} from "./taxonomyApi";

function useRecord<T>(
  projectId: string,
  mutationFn: (data: FormData) => Promise<T>,
  onSaved?: (record: T) => void,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: async (record) => {
      await queryClient.invalidateQueries({
        queryKey: ["taxonomy", projectId],
      });
      onSaved?.(record);
    },
  });
}

function ReviewHistory({
  projectId,
  path,
  expected,
  kind,
  session,
  author,
}: {
  projectId: string;
  path: string;
  expected: number;
  kind: "taxonomy" | "presence";
  session: LabSession | null;
  author: string;
}) {
  const rows = useTaxonomyPage<TaxonReview>(projectId, path);
  const [decision, setDecision] = useState("confirmed");
  const mutation = useRecord(projectId, async (data) => {
    const source =
      kind === "presence"
        ? await pinTaxonomySource(projectId, formValue(data, "source"))
        : undefined;
    return recordTaxonomy<TaxonReview>(
      projectId,
      path,
      {
        expected_revision: expected,
        decision,
        reason: formValue(data, "reason"),
        ...(kind === "presence" ? { source } : {}),
      },
      session?.key,
    );
  });
  const independent =
    session &&
    session.actor.role !== "manager" &&
    session.actor.member_id !== author;
  const title =
    kind === "taxonomy" ? "Taxonomy decision" : "Known presence decision";
  return (
    <section aria-label={`${title} history`}>
      <h4>{title} history</h4>
      {rows.data?.pages[0]?.total === 0 && <p>No decision recorded.</p>}
      <ol>
        {rows.data?.pages
          .flatMap((page) => page.items)
          .map((item) => (
            <li key={item.id}>
              <strong>{decisions[item.review.decision]}</strong> · revision{" "}
              {item.revision}
              <p>
                {item.review.reviewer.name} · {item.review.reviewer.role} ·{" "}
                {new Date(item.review.reviewed_at).toLocaleString()}
              </p>
              <p>{item.review.reason}</p>
              <SourceEvidence
                source={item.review.source}
                label="Separate presence evidence"
              />
            </li>
          ))}
      </ol>
      <MoreTaxonomyRows {...rows} label="decisions" />
      {independent ? (
        <form
          className="management-card"
          aria-label={title}
          onSubmit={submitFields(mutation.mutate)}
        >
          <label>
            Decision
            <select
              value={decision}
              onChange={(event) => setDecision(event.currentTarget.value)}
            >
              {Object.entries(decisions).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          {kind === "presence" && (
            <SourcePicker
              projectId={projectId}
              label="Separate presence source"
              required={decision === "confirmed"}
            />
          )}
          <label>
            Decision reason
            <textarea name="reason" required minLength={3} maxLength={1000} />
          </label>
          <button type="submit" disabled={mutation.isPending}>
            Record {title.toLowerCase()}
          </button>
        </form>
      ) : (
        <p>
          Use a current local reviewer or adjudicator role held by someone other
          than the author.
        </p>
      )}
      <TaxonomyErrors errors={[rows.error, mutation.error]} />
    </section>
  );
}

export function TaxonProposals({
  projectId,
  identities,
  session,
}: {
  projectId: string;
  identities: readonly Identity[];
  session: LabSession | null;
}) {
  const rows = useTaxonomyPage<TaxonProposal>(projectId, "proposals");
  const records = rows.data?.pages.flatMap((page) => page.items) ?? [];
  const [selectedId, setSelectedId] = useState("");
  const selected = records.find((row) => row.id === selectedId);
  const mutation = useRecord(
    projectId,
    async (data) =>
      recordTaxonomy<TaxonProposal>(
        projectId,
        "proposals",
        {
          identity_revision_id: formValue(data, "organism"),
          scientific_name: formValue(data, "scientific-name"),
          rank: formValue(data, "rank"),
          source: await pinTaxonomySource(projectId, formValue(data, "source")),
          reason: formValue(data, "reason"),
        },
        session?.key,
      ),
    (row) => setSelectedId(row.id),
  );
  return (
    <section aria-label="Taxon proposals">
      <h3>Taxon proposals</h3>
      {session && identities.length > 0 && (
        <form
          className="management-card"
          aria-label="Propose a taxon"
          onSubmit={submitFields(mutation.mutate)}
        >
          <label>
            Registered organism
            <select name="organism" required defaultValue="">
              <option value="">Choose a current organism</option>
              {identities.map((identity) => (
                <option key={identity.id} value={identity.id}>
                  {identity.organism_key} · revision {identity.revision}
                </option>
              ))}
            </select>
          </label>
          <label>
            Scientific name
            <input name="scientific-name" maxLength={150} required />
          </label>
          <label>
            Taxonomic rank
            <select name="rank">
              {ranks.map((rank) => (
                <option key={rank}>{rank}</option>
              ))}
            </select>
          </label>
          <SourcePicker projectId={projectId} label="Taxonomy source" />
          <label>
            Proposal reason
            <textarea name="reason" required minLength={3} maxLength={1000} />
          </label>
          <button type="submit" disabled={mutation.isPending}>
            Submit taxon proposal
          </button>
        </form>
      )}
      {!identities.length && (
        <p>
          Register a named organism and its independent unit in the Identity
          registry.
        </p>
      )}
      {rows.data?.pages[0]?.total === 0 && <p>No taxon proposals recorded.</p>}
      <ul>
        {records.map((row) => (
          <li key={row.id}>
            <button
              type="button"
              className="secondary"
              aria-pressed={row.id === selectedId}
              onClick={() => setSelectedId(row.id)}
            >
              {row.proposal.identity.organism_key} ·{" "}
              {row.proposal.scientific_name} ·{" "}
              {row.state === "proposed" ? "Proposed" : decisions[row.state]}
            </button>
          </li>
        ))}
      </ul>
      <MoreTaxonomyRows {...rows} label="taxon proposals" />
      {selected && (
        <section aria-label="Selected taxon proposal">
          <h4>
            {selected.proposal.scientific_name} · {selected.proposal.rank}
          </h4>
          <p>
            {selected.proposal.identity.organism_key}, identity revision{" "}
            {selected.proposal.identity.revision}
          </p>
          <p>
            Proposed by {selected.proposal.author.name} ·{" "}
            {selected.proposal.author.role}
          </p>
          <p>{selected.proposal.reason}</p>
          <SourceEvidence
            source={selected.proposal.source}
            label="Pinned taxonomy evidence"
          />
          <ReviewHistory
            key={`${selected.id}:${selected.review_revision}`}
            projectId={projectId}
            path={`proposals/${selected.id}/reviews`}
            expected={selected.review_revision}
            kind="taxonomy"
            session={session}
            author={selected.proposal.author.member_id}
          />
        </section>
      )}
      <TaxonomyErrors errors={[rows.error, mutation.error]} />
    </section>
  );
}

export function SamplingVisits({
  projectId,
  session,
}: {
  projectId: string;
  session: LabSession | null;
}) {
  const proposals = useTaxonomyPage<TaxonProposal>(projectId, "proposals");
  const rows = useTaxonomyPage<DetectabilityVisit>(projectId, "visits");
  const records = rows.data?.pages.flatMap((page) => page.items) ?? [];
  const [selectedId, setSelectedId] = useState("");
  const [outcome, setOutcome] = useState<VisitOutcome>("detected");
  const selected = records.find((row) => row.id === selectedId);
  const options = proposals.data?.pages.flatMap((page) => page.items) ?? [];
  const mutation = useRecord(
    projectId,
    async (data) =>
      recordTaxonomy<DetectabilityVisit>(
        projectId,
        "visits",
        {
          proposal_id: formValue(data, "proposal"),
          protocol: formValue(data, "protocol"),
          started_at: formValue(data, "started-at"),
          effort_seconds: Number(formValue(data, "effort")),
          outcome,
          source: await pinTaxonomySource(projectId, formValue(data, "source")),
          notes: formValue(data, "notes"),
        },
        session?.key,
      ),
    (row) => setSelectedId(row.id),
  );
  return (
    <section aria-label="Sampling visits">
      <h3>Sampling visits</h3>
      <p>
        Record each intended visit. An observed non-detection needs positive
        effort and original media.
      </p>
      {session && options.length > 0 && (
        <form
          className="management-card"
          aria-label="Record a sampling visit"
          onSubmit={submitFields(mutation.mutate)}
        >
          <label>
            Organism and taxon proposal
            <select name="proposal" required defaultValue="">
              <option value="">Choose a proposal</option>
              {options.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.proposal.identity.organism_key} ·{" "}
                  {option.proposal.scientific_name} · {option.state}
                </option>
              ))}
            </select>
          </label>
          <MoreTaxonomyRows {...proposals} label="available proposals" />
          <label>
            Sampling protocol
            <input name="protocol" required maxLength={200} />
          </label>
          <label>
            Visit start (UTC or offset)
            <input
              name="started-at"
              placeholder="2026-02-02T13:00:00Z"
              required
            />
          </label>
          <label>
            Observation outcome
            <select
              value={outcome}
              onChange={(event) =>
                setOutcome(event.currentTarget.value as VisitOutcome)
              }
            >
              {Object.entries(outcomes).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          {outcome !== "unobserved" && (
            <>
              <label>
                Observed effort (seconds)
                <input
                  name="effort"
                  type="number"
                  step="any"
                  min={0}
                  max={86400}
                  required
                />
              </label>
              <SourcePicker
                projectId={projectId}
                label="Observation source"
                required={outcome !== "unknown"}
              />
            </>
          )}
          <label>
            Visit notes
            <textarea name="notes" minLength={3} maxLength={1000} required />
          </label>
          <button type="submit" disabled={mutation.isPending}>
            Record sampling visit
          </button>
        </form>
      )}
      {proposals.data?.pages[0]?.total === 0 && (
        <p>
          Submit a proposal for the surveyed organism before recording visits.
        </p>
      )}
      {rows.data?.pages[0]?.total === 0 && <p>No sampling visits recorded.</p>}
      <ul>
        {records.map((row) => (
          <li key={row.id}>
            <button
              type="button"
              className="secondary"
              aria-pressed={row.id === selectedId}
              onClick={() => setSelectedId(row.id)}
            >
              {row.visit.identity.organism_key} · {row.visit.started_at} ·{" "}
              {outcomes[row.visit.outcome]}
            </button>
          </li>
        ))}
      </ul>
      <MoreTaxonomyRows {...rows} label="sampling visits" />
      {selected && (
        <section aria-label="Selected sampling visit">
          <h4>
            {selected.visit.identity.organism_key} ·{" "}
            {outcomes[selected.visit.outcome]}
          </h4>
          <p>
            {selected.visit.protocol} · {selected.visit.effort_seconds} seconds
            · {selected.visit.observer.name}
          </p>
          <p>
            {selected.visit.identity.experimental_unit_type ??
              "Unit type undeclared"}{" "}
            ·{" "}
            {selected.visit.identity.experimental_unit_id ??
              "Unit ID undeclared"}
          </p>
          <p>{selected.visit.notes}</p>
          <SourceEvidence
            source={selected.visit.source}
            label="Pinned observation evidence"
          />
          <ReviewHistory
            key={`${selected.id}:${selected.presence_revision}`}
            projectId={projectId}
            path={`visits/${selected.id}/presence-reviews`}
            expected={selected.presence_revision}
            kind="presence"
            session={session}
            author={selected.visit.observer.member_id}
          />
        </section>
      )}
      <TaxonomyErrors errors={[proposals.error, rows.error, mutation.error]} />
    </section>
  );
}
