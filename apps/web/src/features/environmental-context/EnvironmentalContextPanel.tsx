import {
  CopernicusImportForm,
  OceanCurrentWorkspace,
} from "./OceanCurrentWorkspace";
import { LunarContextPanel } from "./LunarContextPanel";
import {
  EnvironmentalAnalysisWorkspace,
  TidalImportForm,
} from "./EnvironmentalAnalysisWorkspace";
import {
  useMutationState,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useId, useRef, useState, type KeyboardEvent } from "react";
import "./environmental-workspace.css";

import type { Project } from "../../api/client";
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "../../components/ui/AsyncState";
import {
  ScientificRecordCard,
  SOURCE_LABELS,
  utcTime,
  scientificVariableLabel,
} from "./ScientificRecordCard";
import { SensorAndNoaaForms } from "./SensorAndNoaaForms";
import { EnvironmentalSubjectInspector } from "./EnvironmentalSubjectInspector";
import {
  getScientificRecords,
  type ScientificRecord,
  type ScientificSourceKind,
} from "./environmentalContextApi";

const PAGE_SIZE = 100;
const VIEWS = [
  ["overview", "Overview"],
  ["sources", "Data sources"],
  ["analyses", "Analyses"],
] as const;
type View = (typeof VIEWS)[number][0];
type Source = "local" | "noaa" | "tides" | "copernicus";
type AnalysisTask = "saved" | "currents" | "lunar";

export function EnvironmentalContextPanel({ project }: { project: Project }) {
  return <EnvironmentalWorkspace key={project.id} projectId={project.id} />;
}

function EnvironmentalWorkspace({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const tabId = useId();
  const sourcePicker = useRef<HTMLSelectElement>(null);
  const addButton = useRef<HTMLButtonElement>(null);
  const selectedTrigger = useRef<HTMLButtonElement>(null);
  const inspectorHeading = useRef<HTMLHeadingElement>(null);
  const addDataRequested = useRef(false);
  const [view, setView] = useState<View>("overview");
  const [source, setSource] = useState<Source>("local");
  const [showImport, setShowImport] = useState(false);
  const [visitedSources, setVisitedSources] = useState<Source[]>([]);
  const [task, setTask] = useState<AnalysisTask>("saved");
  const [visitedTasks, setVisitedTasks] = useState<AnalysisTask[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const pending = useMutationState({
    filters: {
      mutationKey: ["environment-workspace", projectId],
      status: "pending",
    },
    select: (mutation) => mutation.options.mutationKey?.[2],
  });

  function chooseSource(next: Source) {
    setSource(next);
    setVisitedSources((current) =>
      current.includes(next) ? current : [...current, next],
    );
  }

  function openImport(provider?: Source) {
    if (provider) chooseSource(provider);
    addDataRequested.current = true;
    setView("sources");
    setShowImport(true);
    setVisitedSources((previous) => (previous.length ? previous : ["local"]));
    if (view === "sources" && showImport) {
      sourcePicker.current?.focus();
      addDataRequested.current = false;
    }
  }

  function selectView(next: View) {
    setView(next);
    if (next === "analyses")
      setVisitedTasks((previous) => (previous.length ? previous : ["saved"]));
  }

  function focusView(next: View) {
    selectView(next);
    document.getElementById(`${tabId}-tab-${next}`)?.focus();
  }

  function handleTabs(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const last = VIEWS.length - 1;
    const next = {
      ArrowLeft: (index + last) % VIEWS.length,
      ArrowRight: (index + 1) % VIEWS.length,
      Home: 0,
      End: last,
    }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    focusView(VIEWS[next][0]);
  }
  const [offset, setOffset] = useState(0);
  const [variableInput, setVariableInput] = useState("");
  const [sourceInput, setSourceInput] = useState<ScientificSourceKind | "">("");
  const [filters, setFilters] = useState<{
    variable: string;
    sourceKind: ScientificSourceKind | "";
  }>({ variable: "", sourceKind: "" });
  const recordsQuery = useQuery({
    queryKey: [
      "scientific-records",
      projectId,
      { limit: PAGE_SIZE, offset, ...filters },
    ],
    queryFn: ({ signal }) =>
      getScientificRecords(
        projectId,
        { limit: PAGE_SIZE, offset, ...filters },
        signal,
      ),
  });
  const refreshRecords = async () => {
    setOffset(0);
    await queryClient.invalidateQueries({
      queryKey: ["scientific-records", projectId],
    });
  };
  const activeFilter = Boolean(filters.variable || filters.sourceKind);
  const overview = useQuery({
    queryKey: [
      "scientific-records",
      projectId,
      { limit: PAGE_SIZE, offset: 0, variable: "", sourceKind: "" },
    ],
    queryFn: ({ signal }) =>
      getScientificRecords(projectId, { limit: PAGE_SIZE, offset: 0 }, signal),
    enabled: view === "overview" && (offset !== 0 || activeFilter),
  });
  const overviewQuery = offset === 0 && !activeFilter ? recordsQuery : overview;
  const records = recordsQuery.data;
  const selected = records?.items.find((record) => record.id === selectedId);
  return (
    <section
      className="feature-workspace environmental-workspace"
      aria-label="Environmental Context workspace"
    >
      <header className="environment-heading">
        <div>
          <h2>Environmental Context</h2>
          <p>
            Bring site measurements and environmental conditions into your
            project.
          </p>
        </div>
        <button ref={addButton} type="button" onClick={() => openImport()}>
          Add environmental data
        </button>
      </header>
      <div
        className="environment-tabs"
        role="tablist"
        aria-label="Environmental Context views"
      >
        {VIEWS.map(([id, label], index) => (
          <button
            type="button"
            role="tab"
            id={`${tabId}-tab-${id}`}
            key={id}
            aria-controls={`${tabId}-panel-${id}`}
            aria-selected={view === id}
            tabIndex={view === id ? 0 : -1}
            onClick={() => selectView(id)}
            onKeyDown={(event) => handleTabs(event, index)}
          >
            {label}
          </button>
        ))}
      </div>
      {pending.length > 0 && (
        <p className="environment-feedback" role="status">
          In progress: {pending.join(", ")}
        </p>
      )}
      <section
        role="tabpanel"
        id={`${tabId}-panel-overview`}
        aria-labelledby={`${tabId}-tab-overview`}
        hidden={view !== "overview"}
        tabIndex={0}
      >
        {view === "overview" &&
          (overviewQuery.isPending ? (
            <LoadingState
              title="Loading scientific records"
              description="Reading this project's saved records."
            />
          ) : overviewQuery.error ? (
            <ErrorState
              title="Scientific records could not be loaded"
              message={overviewQuery.error.message}
              onRetry={() => {
                void overviewQuery.refetch();
              }}
            />
          ) : overviewQuery.data && overviewQuery.data.total ? (
            <EnvironmentOverview
              records={overviewQuery.data.items}
              total={overviewQuery.data.total}
              onBrowse={() => focusView("sources")}
              onAnalyze={() => focusView("analyses")}
            />
          ) : (
            <EmptyState
              title="No scientific records yet"
              description="Add measurements from a sensor file, a NOAA station, or Copernicus Marine. You can also calculate lunar context from a UTC timestamp."
              action={
                <button
                  type="button"
                  className="secondary"
                  onClick={() => focusView("analyses")}
                >
                  Choose an analysis
                </button>
              }
            />
          ))}
      </section>
      <section
        role="tabpanel"
        id={`${tabId}-panel-sources`}
        aria-labelledby={`${tabId}-tab-sources`}
        hidden={view !== "sources"}
        tabIndex={0}
      >
        {(showImport || visitedSources.length > 0) && (
          <section
            hidden={!showImport}
            className="environment-acquisition panel-card"
            aria-label="Add environmental data"
          >
            <div className="environment-section-heading">
              <h3>Add environmental data</h3>
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  setShowImport(false);
                  addButton.current?.focus();
                }}
              >
                Hide import form
              </button>
            </div>
            <label>
              <span id={`${tabId}-source-label`}>Data source</span>
              <select
                aria-labelledby={`${tabId}-source-label`}
                value={source}
                ref={(element) => {
                  sourcePicker.current = element;
                  if (
                    element &&
                    view === "sources" &&
                    addDataRequested.current
                  ) {
                    addDataRequested.current = false;
                    element.focus();
                  }
                }}
                onChange={(event) => chooseSource(event.target.value as Source)}
              >
                <option value="local">Local sensor JSON</option>
                <option value="noaa">NOAA station temperature</option>
                <option value="tides">NOAA tides</option>
                <option value="copernicus">Copernicus Marine</option>
              </select>
            </label>

            <SensorAndNoaaForms
              projectId={projectId}
              source={source === "local" || source === "noaa" ? source : null}
              onImported={refreshRecords}
            />
            {visitedSources.includes("tides") && (
              <div hidden={source !== "tides"}>
                <TidalImportForm projectId={projectId} />
              </div>
            )}
            {visitedSources.includes("copernicus") && (
              <div hidden={source !== "copernicus"}>
                <CopernicusImportForm projectId={projectId} />
              </div>
            )}
          </section>
        )}
        <section
          className="environment-records"
          aria-label="Scientific records"
        >
          <h3>Saved scientific records</h3>
          <form
            className="training-form-grid"
            onSubmit={(event) => {
              event.preventDefault();
              setOffset(0);
              setSelectedId(null);
              setFilters({
                variable: variableInput.trim(),
                sourceKind: sourceInput,
              });
            }}
          >
            <label>
              Variable filter
              <input
                value={variableInput}
                placeholder="All variables"
                onChange={(event) => setVariableInput(event.target.value)}
              />
            </label>
            <label>
              Source kind filter
              <select
                value={sourceInput}
                onChange={(event) =>
                  setSourceInput(
                    event.target.value as ScientificSourceKind | "",
                  )
                }
              >
                <option value="">All source kinds</option>
                {Object.entries(SOURCE_LABELS).map(([kind, label]) => (
                  <option key={kind} value={kind}>
                    {label} sources
                  </option>
                ))}
              </select>
            </label>
            <button type="submit" className="secondary">
              Apply filters
            </button>
          </form>

          {view === "sources" &&
            (recordsQuery.isPending ? (
              <LoadingState
                title="Loading scientific records"
                description="Reading this project's saved records."
              />
            ) : recordsQuery.error ? (
              <ErrorState
                title="Scientific records could not be loaded"
                message={recordsQuery.error.message}
                onRetry={() => {
                  void recordsQuery.refetch();
                }}
              />
            ) : records && records.items.length === 0 ? (
              <EmptyState
                title={
                  activeFilter
                    ? "No records match these filters"
                    : "No scientific records yet"
                }
                description={
                  activeFilter
                    ? "Clear the filters to browse the full record list."
                    : "Add environmental data to start this record list."
                }
                action={
                  activeFilter ? (
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => {
                        setVariableInput("");
                        setSourceInput("");
                        setOffset(0);
                        setSelectedId(null);
                        setFilters({ variable: "", sourceKind: "" });
                      }}
                    >
                      Clear filters
                    </button>
                  ) : undefined
                }
              />
            ) : (
              records && (
                <>
                  {selected && (
                    <section
                      className="environment-record-inspector"
                      aria-label="Selected record"
                    >
                      <div className="environment-section-heading">
                        <h4 ref={inspectorHeading} tabIndex={-1}>
                          Selected record
                        </h4>
                        <button
                          type="button"
                          className="secondary"
                          onClick={() => {
                            setSelectedId(null);
                            selectedTrigger.current?.focus();
                          }}
                        >
                          Close record
                        </button>
                      </div>
                      <ScientificRecordCard
                        key={selected.id}
                        record={selected}
                      />
                      {selected.variable === "geographic_position" &&
                        selected.subject && (
                          <EnvironmentalSubjectInspector
                            key={selected.id}
                            projectId={projectId}
                            subject={selected.subject}
                          />
                        )}
                    </section>
                  )}
                  <div
                    className="environment-table-scroll"
                    tabIndex={0}
                    role="region"
                    aria-label="Scrollable scientific records"
                  >
                    <table aria-label="Saved scientific records">
                      <thead>
                        <tr>
                          <th scope="col">Measurement</th>
                          <th scope="col">Observed (UTC)</th>
                          <th scope="col">Source</th>
                          <th scope="col">Quality</th>
                        </tr>
                      </thead>
                      <tbody>
                        {records.items.map((record) => (
                          <tr
                            key={record.id}
                            className={
                              record.id === selectedId ? "selected" : ""
                            }
                          >
                            <th scope="row">
                              <button
                                type="button"
                                className="environment-record-button"
                                aria-pressed={record.id === selectedId}
                                onClick={(event) => {
                                  selectedTrigger.current = event.currentTarget;
                                  setSelectedId(record.id);
                                  const keyboard = event.detail === 0;
                                  requestAnimationFrame(() => {
                                    const heading = inspectorHeading.current;
                                    heading?.scrollIntoView?.({
                                      block: "nearest",
                                    });
                                    if (keyboard)
                                      heading?.focus({ preventScroll: true });
                                  });
                                }}
                              >
                                <span>
                                  {scientificVariableLabel(record.variable)}
                                </span>
                                <small>
                                  {record.value} {record.unit}
                                </small>
                              </button>
                            </th>
                            <td>
                              <time dateTime={record.observed_at}>
                                {utcTime(record.observed_at).replace(
                                  / UTC$/,
                                  "",
                                )}
                              </time>
                            </td>
                            <td>{record.provenance.source}</td>
                            <td>
                              <span
                                className={
                                  record.qc === "suspect" ||
                                  record.qc === "rejected"
                                    ? "environment-warning"
                                    : ""
                                }
                              >
                                {record.qc ?? "unassessed"}
                              </span>
                              {record.environmental_snapshot_current ===
                                false && (
                                <small className="environment-warning">
                                  Historical snapshot
                                </small>
                              )}
                              {record.calibration_current === false && (
                                <small className="environment-warning">
                                  Stale calibration
                                </small>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <nav
                    className="pagination"
                    aria-label="Scientific record pages"
                  >
                    <button
                      type="button"
                      disabled={offset === 0 || recordsQuery.isFetching}
                      onClick={() => {
                        setSelectedId(null);
                        setOffset((current) =>
                          Math.max(0, current - PAGE_SIZE),
                        );
                      }}
                    >
                      Previous page
                    </button>
                    <span role="status">
                      Records {records.items.length ? offset + 1 : 0}–
                      {offset + records.items.length} of {records.total}
                    </span>
                    <button
                      type="button"
                      disabled={
                        offset + PAGE_SIZE >= records.total ||
                        recordsQuery.isFetching
                      }
                      onClick={() => {
                        setSelectedId(null);
                        setOffset((current) => current + PAGE_SIZE);
                      }}
                    >
                      Next page
                    </button>
                  </nav>
                </>
              )
            ))}
        </section>
      </section>
      <section
        role="tabpanel"
        id={`${tabId}-panel-analyses`}
        aria-labelledby={`${tabId}-tab-analyses`}
        hidden={view !== "analyses"}
        tabIndex={0}
      >
        <label className="environment-task">
          <span id={`${tabId}-analysis-label`}>Analysis task</span>
          <select
            aria-labelledby={`${tabId}-analysis-label`}
            value={task}
            onChange={(event) => {
              const next = event.target.value as AnalysisTask;
              setTask(next);
              setVisitedTasks((previous) =>
                previous.includes(next) ? previous : [...previous, next],
              );
            }}
          >
            <option value="saved">Saved environmental analyses</option>
            <option value="currents">Ocean current map</option>
            <option value="lunar">Quick lunar context (offline)</option>
          </select>
        </label>
        {visitedTasks.includes("saved") && (
          <div hidden={task !== "saved"}>
            <EnvironmentalAnalysisWorkspace
              projectId={projectId}
              onAddTides={() => openImport("tides")}
            />
          </div>
        )}
        {visitedTasks.includes("currents") && (
          <div hidden={task !== "currents"}>
            <OceanCurrentWorkspace
              projectId={projectId}
              onAddData={() => openImport("copernicus")}
            />
          </div>
        )}
        {visitedTasks.includes("lunar") && (
          <div hidden={task !== "lunar"}>
            <LunarContextPanel projectId={projectId} />
          </div>
        )}
      </section>
    </section>
  );
}

function EnvironmentOverview({
  records,
  total,
  onBrowse,
  onAnalyze,
}: {
  records: ScientificRecord[];
  total: number;
  onBrowse: () => void;
  onAnalyze: () => void;
}) {
  const times = records
    .map((record) => record.observed_at)
    .filter((time) => Number.isFinite(Date.parse(time)))
    .sort((a, b) => Date.parse(a) - Date.parse(b));
  const firstTime = times[0];
  const lastTime = times.at(-1);
  const sources = [
    ...new Set(records.map((record) => record.provenance.source)),
  ];
  const flagged = records.filter(
    (record) =>
      record.qc === "suspect" ||
      record.qc === "rejected" ||
      record.qc_flags?.length,
  ).length;
  const historical = records.filter(
    (record) =>
      record.environmental_snapshot_current === false ||
      record.calibration_current === false,
  ).length;
  const withoutLocation = records.filter((record) => !record.location).length;
  return (
    <div className="environment-overview">
      <h3>Project evidence</h3>
      <dl className="environment-summary">
        <div>
          <dt>Saved records</dt>
          <dd>{total.toLocaleString()}</dd>
        </div>
        <div>
          <dt>Sources in view</dt>
          <dd>{sources.length.toLocaleString()}</dd>
        </div>
        <div>
          <dt>Flagged for quality</dt>
          <dd>{flagged.toLocaleString()}</dd>
        </div>
        <div>
          <dt>Historical or stale</dt>
          <dd>{historical.toLocaleString()}</dd>
        </div>
      </dl>
      <section className="panel-card environment-coverage">
        <h4>Observation coverage</h4>
        <p className="secondary-text">
          {records.length === total
            ? "All saved records"
            : `Showing ${records.length} of ${total} saved records`}{" "}
          · Observation times shown in UTC
        </p>
        {firstTime && lastTime && (
          <p>
            {utcTime(firstTime)}
            {firstTime !== lastTime && <> to {utcTime(lastTime)}</>}
          </p>
        )}
        {sources.length > 0 && (
          <p>
            Sources: {sources.slice(0, 4).join(", ")}
            {sources.length > 4 && ` and ${sources.length - 4} more`}
          </p>
        )}
        {withoutLocation > 0 && (
          <p className="environment-warning">
            {withoutLocation} without coordinates. Geographic matching requires
            a recorded location.
          </p>
        )}
      </section>
      <div className="environment-overview-actions">
        <button type="button" className="secondary" onClick={onBrowse}>
          Browse records
        </button>
        <button type="button" className="secondary" onClick={onAnalyze}>
          Choose an analysis
        </button>
      </div>
    </div>
  );
}
