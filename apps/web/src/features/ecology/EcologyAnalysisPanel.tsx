import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import type { Metric, Registry } from "./ecologyApi";
import {
  ecologyAnalysisDownload,
  listEcologyAnalyses,
  saveEcologyAnalysis,
  type AnalysisCreate,
  type AnalysisSelection,
  type EcologyAnalysis,
  type SurveySource,
} from "./ecologyAnalysisApi";

interface ImageOption {
  id: string;
  original_filename: string;
  annotation_status: string;
}

const metrics: Record<Metric, string> = {
  mask_projected_area: "Projected mask area",
  box_width: "Box width",
  box_height: "Box height",
};

interface SurveyDraft {
  key: number;
  image_id: string;
  sample_id: string;
  experimental_unit_type: string;
  experimental_unit_id: string;
  observed_at: string;
  surveyed_area_m2: string;
  exclusion_reason: string;
}

function emptySurvey(key: number): SurveyDraft {
  return {
    key,
    image_id: "",
    sample_id: "",
    experimental_unit_type: "site",
    experimental_unit_id: "",
    observed_at: "",
    surveyed_area_m2: "",
    exclusion_reason: "",
  };
}

function surveyPayload(source: SurveyDraft): SurveySource {
  return {
    image_id: source.image_id || undefined,
    sample_id: source.sample_id,
    experimental_unit_type: source.experimental_unit_type,
    experimental_unit_id: source.experimental_unit_id,
    observed_at: source.observed_at,
    surveyed_area_m2: source.surveyed_area_m2
      ? Number(source.surveyed_area_m2)
      : undefined,
    exclusion_reason: source.exclusion_reason || undefined,
  };
}

function SurveyFields({
  source,
  images,
  onChange,
}: {
  source: SurveyDraft;
  images: readonly ImageOption[];
  onChange: (value: SurveyDraft) => void;
}) {
  function field(name: keyof Omit<SurveyDraft, "key">, value: string) {
    onChange({ ...source, [name]: value });
  }
  return (
    <>
      <label>
        Reviewed image
        <select
          value={source.image_id}
          onChange={(event) => field("image_id", event.target.value)}
        >
          <option value="">Missing image</option>
          {images.map((image) => (
            <option key={image.id} value={image.id}>
              {image.original_filename}
            </option>
          ))}
          {source.image_id &&
            !images.some((image) => image.id === source.image_id) && (
              <option value={source.image_id}>{source.image_id}</option>
            )}
        </select>
      </label>
      <label>
        Sample ID
        <input
          required
          value={source.sample_id}
          onChange={(event) => field("sample_id", event.target.value)}
        />
      </label>
      <label>
        Sampling level
        <select
          value={source.experimental_unit_type}
          onChange={(event) =>
            field("experimental_unit_type", event.target.value)
          }
        >
          {["organism", "colony", "tank", "site"].map((type) => (
            <option key={type}>{type}</option>
          ))}
        </select>
      </label>
      <label>
        Experimental unit ID
        <input
          required
          value={source.experimental_unit_id}
          onChange={(event) =>
            field("experimental_unit_id", event.target.value)
          }
        />
      </label>
      <label>
        Survey time with offset
        <input
          required
          placeholder="2026-11-14T12:00:00Z"
          value={source.observed_at}
          onChange={(event) => field("observed_at", event.target.value)}
        />
      </label>
      <label>
        Surveyed area (m²)
        <input
          type="number"
          min="0"
          step="any"
          value={source.surveyed_area_m2}
          onChange={(event) => field("surveyed_area_m2", event.target.value)}
        />
      </label>
      <label>
        Exclusion reason
        <input
          required={!source.image_id}
          value={source.exclusion_reason}
          onChange={(event) => field("exclusion_reason", event.target.value)}
        />
      </label>
    </>
  );
}

function AnalysisResults({
  analysis,
  projectId,
}: {
  analysis: EcologyAnalysis;
  projectId: string;
}) {
  const { result } = analysis.snapshot;
  return (
    <>
      {analysis.stale && <p role="alert">{analysis.stale_reason}</p>}
      <p>Reviewed by {analysis.snapshot.reviewed_by}</p>
      {result.kind === "growth" ? (
        <>
          <table>
            <caption>Calibrated image-plane growth</caption>
            <thead>
              <tr>
                <th>Organism</th>
                <th>First</th>
                <th>Last</th>
                <th>Change</th>
                <th>Change per day</th>
              </tr>
            </thead>
            <tbody>
              {result.changes.map((row) => (
                <tr key={row.organism_id}>
                  <th scope="row">{row.organism_id}</th>
                  <td>
                    {row.initial_value} {row.unit}
                  </td>
                  <td>
                    {row.final_value} {row.unit}
                  </td>
                  <td>
                    {row.absolute_change.toPrecision(4)} {row.unit}
                  </td>
                  <td>
                    {row.change_per_day.toPrecision(4)} {row.unit}/day
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {result.changes.length > 0 && (
            <details>
              <summary>Plot first and last observations</summary>
              {result.changes.map((row) => {
                const maximum = Math.max(row.initial_value, row.final_value);
                return (
                  <div key={row.organism_id}>
                    <p>
                      {row.organism_id} · {row.unit}
                    </p>
                    <meter
                      aria-label={`${row.organism_id} first observation`}
                      min={0}
                      max={maximum}
                      value={row.initial_value}
                    />
                    {" → "}
                    <meter
                      aria-label={`${row.organism_id} last observation`}
                      min={0}
                      max={maximum}
                      value={row.final_value}
                    />
                  </div>
                );
              })}
            </details>
          )}
          {result.population_summaries.length > 0 && (
            <details>
              <summary>Descriptive experimental-unit summaries</summary>
              {result.population_summaries.map((row) => (
                <p key={`${row.baseline_date}-${row.final_date}-${row.unit}`}>
                  {row.baseline_date} through {row.final_date} ·{" "}
                  {row.independent_unit_count} declared units · mean change{" "}
                  {row.mean_unit_absolute_change.toPrecision(4)} {row.unit}
                </p>
              ))}
            </details>
          )}
        </>
      ) : (
        <>
          <table>
            <caption>{result.class_name} survey detections</caption>
            <thead>
              <tr>
                <th>Sample</th>
                <th>Visit (UTC)</th>
                <th>Unit</th>
                <th>Count</th>
                <th>Surveyed m²</th>
                <th>Count / m²</th>
              </tr>
            </thead>
            <tbody>
              {result.visits.map((row) => (
                <tr key={`${row.sample_id}-${row.observed_at}`}>
                  <th scope="row">{row.sample_id}</th>
                  <td>{row.observed_at}</td>
                  <td>{row.experimental_unit_id}</td>
                  <td>{row.count}</td>
                  <td>{row.surveyed_area_m2 ?? "—"}</td>
                  <td>{row.density_per_m2?.toPrecision(4) ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {result.visits.length > 0 && (
            <details>
              <summary>Plot sample counts</summary>
              {result.visits.map((row) => (
                <div key={`${row.sample_id}-${row.observed_at}`}>
                  <span>
                    {row.sample_id} · {row.observed_at.slice(0, 10)}
                  </span>{" "}
                  <meter
                    aria-label={`${row.sample_id} detections on ${row.observed_at.slice(0, 10)}`}
                    min={0}
                    max={Math.max(
                      1,
                      ...result.visits.map((visit) => visit.count),
                    )}
                    value={row.count}
                  />
                </div>
              ))}
            </details>
          )}
          {result.unit_summaries.length > 0 && (
            <details>
              <summary>Experimental-unit totals by UTC date</summary>
              {result.unit_summaries.map((row) => (
                <p key={`${row.experimental_unit_id}-${row.observed_on}`}>
                  {row.observed_on} · {row.experimental_unit_id} ·{" "}
                  {row.sample_count} samples · {row.total_count} detections
                  {row.excluded_sample_count > 0 &&
                    ` · ${row.excluded_sample_count} excluded samples`}
                  {row.density_per_m2 != null &&
                    ` · ${row.density_per_m2.toPrecision(4)} / m²`}
                </p>
              ))}
            </details>
          )}
        </>
      )}
      {result.exclusions.length > 0 && (
        <details open>
          <summary>Excluded and incomplete observations</summary>
          <ul>
            {result.exclusions.map((row, index) => (
              <li key={index}>
                {row.source} · {row.reason.replaceAll("_", " ")}
              </li>
            ))}
          </ul>
        </details>
      )}
      <details>
        <summary>Method and provenance</summary>
        <p>{analysis.snapshot.review_note}</p>
        {analysis.snapshot.limitations.map((text) => (
          <p key={text}>{text}</p>
        ))}
        <code>{analysis.content_sha256}</code>
      </details>
      <p>
        <a href={ecologyAnalysisDownload(projectId, analysis.id, "csv")}>
          Download CSV
        </a>
        {" · "}
        <a href={ecologyAnalysisDownload(projectId, analysis.id, "json")}>
          Download JSON
        </a>
      </p>
    </>
  );
}

export function EcologyAnalysisPanel({
  projectId,
  registry,
  images,
  classes,
}: {
  projectId: string;
  registry: Registry | undefined;
  images: readonly ImageOption[];
  classes: readonly { id: string; name: string }[];
}) {
  const client = useQueryClient();
  const [kind, setKind] = useState<AnalysisSelection["kind"]>("growth");
  const [metric, setMetric] = useState<Metric>("mask_projected_area");
  const [growth, setGrowth] = useState<Record<string, string>>({});
  const [surveys, setSurveys] = useState<SurveyDraft[]>([emptySurvey(0)]);
  const [classId, setClassId] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [supersedes, setSupersedes] = useState<string>();
  const [activeId, setActiveId] = useState<string>();
  const [page, setPage] = useState(1);
  const historyKey = ["ecology-verified-analyses", projectId];
  const history = useQuery({
    queryKey: [...historyKey, page],
    queryFn: ({ signal }) => listEcologyAnalyses(projectId, page, signal),
  });
  const run = useMutation({
    mutationFn: (payload: AnalysisCreate) =>
      saveEcologyAnalysis(projectId, payload),
    onSuccess: async (saved) => {
      setActiveId(saved.id);
      setPage(1);
      setSupersedes(undefined);
      setConfirmed(false);
      await client.invalidateQueries({ queryKey: historyKey });
    },
  });
  const active = history.data?.items.find((item) => item.id === activeId);
  const reviewedImages = images.filter(
    (item) => item.annotation_status === "reviewed",
  );
  const observationRows = (registry?.calibration_evidence_links ?? []).map(
    (row, index) => {
      const annotation = registry?.annotation_evidence_links.find(
        (link) => link.id === row.annotation_evidence_id,
      );
      const source = registry?.image_evidence_links.find(
        (link) => link.id === annotation?.image_evidence_id,
      );
      const image = images.find((item) => item.id === source?.image_id);
      return {
        id: row.id,
        label: `Visit ${index + 1}${source ? ` · ${source.organism_key}` : ""}${image ? ` · ${image.original_filename}` : ""}`,
      };
    },
  );

  function recalculate(record: EcologyAnalysis) {
    const selection = record.snapshot.selection;
    const mapped = (id: string) => record.source_id_map[id] ?? id;
    setKind(selection.kind);
    setSupersedes(record.id);
    setNote("");
    setConfirmed(false);
    if (selection.kind === "growth") {
      setMetric(selection.metric);
      setGrowth(
        Object.fromEntries(
          selection.sources.map((row) => [
            mapped(row.calibration_evidence_id),
            row.exclusion_reason ?? "",
          ]),
        ),
      );
    } else {
      setClassId(mapped(selection.class_id));
      setSurveys(
        selection.sources.map((row, key) => ({
          ...row,
          key,
          image_id: row.image_id ? mapped(row.image_id) : "",
          exclusion_reason: row.exclusion_reason ?? "",
          surveyed_area_m2: row.surveyed_area_m2?.toString() ?? "",
        })),
      );
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!confirmed) return;
    const selection: AnalysisSelection =
      kind === "growth"
        ? {
            kind,
            metric,
            sources: Object.entries(growth).map(
              ([calibration_evidence_id, exclusion_reason]) => ({
                calibration_evidence_id,
                ...(exclusion_reason.trim()
                  ? { exclusion_reason: exclusion_reason.trim() }
                  : {}),
              }),
            ),
          }
        : { kind, class_id: classId, sources: surveys.map(surveyPayload) };
    run.mutate({
      selection,
      reviewed_by: reviewer,
      review_note: note,
      confirm_reviewed_selection: true,
      supersedes_id: supersedes,
    });
  }

  return (
    <section
      className="management-card"
      aria-label="Reviewed ecological analyses"
    >
      <h3>Reviewed ecological analyses</h3>
      <form onSubmit={submit}>
        <label>
          Analysis
          <select
            value={kind}
            onChange={(event) => {
              setKind(
                event.target.value === "abundance" ? "abundance" : "growth",
              );
              setSupersedes(undefined);
              setConfirmed(false);
            }}
          >
            <option value="growth">Growth</option>
            <option value="abundance">Abundance</option>
          </select>
        </label>
        {kind === "growth" ? (
          <>
            <label>
              Measurement
              <select
                value={metric}
                onChange={(event) => setMetric(event.target.value as Metric)}
              >
                {Object.entries(metrics).map(([value, title]) => (
                  <option key={value} value={value}>
                    {title}
                  </option>
                ))}
              </select>
            </label>
            <fieldset>
              <legend>Calibrated visits</legend>
              {observationRows.length === 0 && (
                <p>
                  Link reviewed annotations and their saved image calibration to
                  an organism first.
                </p>
              )}
              {observationRows.map((row) => (
                <div key={row.id}>
                  <label>
                    <input
                      type="checkbox"
                      checked={row.id in growth}
                      onChange={(event) => {
                        const next = { ...growth };
                        if (event.target.checked) next[row.id] = "";
                        else delete next[row.id];
                        setGrowth(next);
                        setConfirmed(false);
                      }}
                    />
                    {row.label}
                  </label>
                  {row.id in growth && (
                    <label>
                      Exclusion reason
                      <input
                        aria-label={`Exclude ${row.id}`}
                        value={growth[row.id]}
                        onChange={(event) => {
                          setGrowth({
                            ...growth,
                            [row.id]: event.target.value,
                          });
                          setConfirmed(false);
                        }}
                      />
                    </label>
                  )}
                </div>
              ))}
            </fieldset>
          </>
        ) : (
          <>
            <p>
              Use one reviewed image per nonoverlapping sample and UTC date. Add
              surveyed area only when it was measured.
            </p>
            <label>
              Counted class
              <select
                value={classId}
                onChange={(event) => {
                  setClassId(event.target.value);
                  setConfirmed(false);
                }}
                required
              >
                <option value="">Select class</option>
                {classes.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.name}
                  </option>
                ))}
              </select>
            </label>
            {surveys.map((source, index) => (
              <fieldset key={source.key}>
                <legend>Sample visit {index + 1}</legend>
                <SurveyFields
                  source={source}
                  images={reviewedImages}
                  onChange={(changed) => {
                    setConfirmed(false);
                    setSurveys(
                      surveys.map((row) =>
                        row.key === changed.key ? changed : row,
                      ),
                    );
                  }}
                />
                {surveys.length > 1 && (
                  <button
                    type="button"
                    onClick={() => {
                      setConfirmed(false);
                      setSurveys(
                        surveys.filter((item) => item.key !== source.key),
                      );
                    }}
                  >
                    Remove sample visit
                  </button>
                )}
              </fieldset>
            ))}
            <button
              type="button"
              onClick={() => {
                setConfirmed(false);
                setSurveys([
                  ...surveys,
                  emptySurvey((surveys.at(-1)?.key ?? -1) + 1),
                ]);
              }}
            >
              Add sample visit
            </button>
          </>
        )}
        <label>
          Reviewed by
          <input
            required
            value={reviewer}
            onChange={(event) => setReviewer(event.target.value)}
          />
        </label>
        <label>
          Review notes
          <textarea
            required
            minLength={3}
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
        </label>
        <label>
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
          />
          Confirm the selected observations, comparable measurements, and
          declared sampling design
        </label>
        <button
          type="submit"
          disabled={
            !confirmed ||
            !reviewer.trim() ||
            note.trim().length < 3 ||
            run.isPending ||
            (kind === "growth" ? Object.keys(growth).length < 2 : !classId)
          }
        >
          {run.isPending
            ? "Saving…"
            : supersedes
              ? "Review and save recalculation"
              : "Review and save analysis"}
        </button>
        {run.error && <p role="alert">{run.error.message}</p>}
      </form>
      <h4>Saved analyses</h4>
      {history.isPending && <p>Loading saved analyses…</p>}
      {history.error && <p role="alert">{history.error.message}</p>}
      {history.data?.items.length === 0 && <p>No reviewed analysis saved.</p>}
      <ul>
        {history.data?.items.map((saved) => (
          <li key={saved.id}>
            <button
              type="button"
              onClick={() => setActiveId(saved.id)}
              aria-pressed={activeId === saved.id}
            >
              {saved.snapshot.result.kind === "growth" ? "Growth" : "Abundance"}{" "}
              · {saved.created_at} {saved.stale ? " · Stale evidence" : ""}
            </button>
          </li>
        ))}
      </ul>
      {history.data && history.data.total > 20 && (
        <div>
          <button
            type="button"
            disabled={page === 1}
            onClick={() => setPage(page - 1)}
          >
            Previous analyses
          </button>
          <button
            type="button"
            disabled={history.data.total <= page * 20}
            onClick={() => setPage(page + 1)}
          >
            Next analyses
          </button>
        </div>
      )}
      {active && (
        <div aria-label="Saved ecological result">
          <AnalysisResults analysis={active} projectId={projectId} />
          <button type="button" onClick={() => recalculate(active)}>
            Prepare recalculation
          </button>
        </div>
      )}
    </section>
  );
}
