import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";

import {
  MonitoringAssessmentPanel,
  monitoringRuleKey,
} from "./MonitoringAssessmentPanel";
import { MonitoringProjectSummaries } from "./MonitoringProjectSummaries";
import { MonitoringRuleForm } from "./MonitoringRuleForm";
import {
  createMonitoringAssessment,
  createMonitoringRule,
  getMonitoringAssessment,
  getMonitoringRule,
  listMonitoringRules,
  type MonitoringAssessmentCreate,
  type MonitoringRuleCreate,
} from "./monitoringApi";
import {
  assessmentLabel,
  MonitoringFields,
  monitoringLabel,
  useMonitoringAssessments,
} from "./monitoringPresentation";
import "./monitoring.css";

interface MonitoringProps {
  projectId: string;
  onOpenWorkflow?: () => void;
}

function MonitoringAssessments({ projectId, onOpenWorkflow }: MonitoringProps) {
  const cache = useQueryClient();
  const [newRule, setNewRule] = useState(false);
  const [ruleId, setRuleId] = useState("");
  const [assessmentId, setAssessmentId] = useState("");
  const [invalidWindow, setInvalidWindow] = useState("");
  const rulesKey = ["monitoring-rules", projectId];
  const rules = useInfiniteQuery({
    queryKey: rulesKey,
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      listMonitoringRules(projectId, pageParam, signal),
    getNextPageParam: (last) =>
      last.offset + last.items.length < last.total && last.items.length > 0
        ? last.offset + last.items.length
        : undefined,
  });
  const chosenRule = useQuery({
    queryKey: monitoringRuleKey(projectId, ruleId),
    queryFn: ({ signal }) => getMonitoringRule(projectId, ruleId, signal),
    enabled: Boolean(ruleId),
  });
  const assessments = useMonitoringAssessments(projectId);
  const detailsKey = (id: string) => ["monitoring-assessment", projectId, id];
  const details = useQuery({
    queryKey: detailsKey(assessmentId),
    queryFn: ({ signal }) =>
      getMonitoringAssessment(projectId, assessmentId, signal),
    enabled: Boolean(assessmentId),
  });
  const createRule = useMutation({
    mutationFn: (data: MonitoringRuleCreate) =>
      createMonitoringRule(projectId, data),
    onSuccess: (saved) => {
      cache.setQueryData(monitoringRuleKey(projectId, saved.id), saved);
      setRuleId(saved.id);
      setNewRule(false);
      void cache.invalidateQueries({ queryKey: rulesKey });
    },
  });
  const assess = useMutation({
    mutationFn: (data: MonitoringAssessmentCreate) =>
      createMonitoringAssessment(projectId, data),
    onSuccess: (record) => {
      cache.setQueryData(detailsKey(record.id), record);
      setAssessmentId(record.id);
      void cache.invalidateQueries({
        queryKey: ["monitoring-assessments", projectId],
      });
    },
  });

  function assessWindow(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const rule = chosenRule.data;
    if (!rule) return;
    const form = new FormData(event.currentTarget);
    const start = new Date(`${form.get("start")}Z`);
    const end = new Date(`${form.get("end")}Z`);
    const length = end.getTime() - start.getTime();
    if (!(length > 0 && length <= 31 * 24 * 60 * 60 * 1_000)) {
      setInvalidWindow("Choose an increasing UTC window of at most 31 days.");
      return;
    }
    setInvalidWindow("");
    assess.mutate({
      rule_id: rule.id,
      rule_sha256: rule.rule_sha256,
      window_start: start.toISOString().replace(/\.000Z$/, "Z"),
      window_end: end.toISOString().replace(/\.000Z$/, "Z"),
    });
  }

  const ruleOptions = rules.data?.pages.flatMap((page) => page.items) ?? [];
  const assessmentOptions =
    assessments.data?.pages.flatMap((page) => page.items) ?? [];
  const rule = chosenRule.data;
  const selectedAssessment = details.data;
  const readError =
    rules.error ?? chosenRule.error ?? assessments.error ?? details.error;
  return (
    <>
      <div className="dashboard-actions">
        {!newRule && (
          <button type="button" onClick={() => setNewRule(true)}>
            New monitoring rule
          </button>
        )}
      </div>
      {newRule && (
        <MonitoringRuleForm
          projectId={projectId}
          pending={createRule.isPending}
          onCreate={(data) => createRule.mutate(data)}
          onCancel={() => {
            createRule.reset();
            setNewRule(false);
          }}
        />
      )}
      {(readError || createRule.error) && (
        <p role="alert" className="form-error">
          {(readError ?? createRule.error)?.message}
        </p>
      )}
      <form className="panel" onSubmit={assessWindow}>
        <h3>Assess a monitoring window</h3>
        <div className="dashboard-grid">
          <label>
            Monitoring rule
            <select
              value={ruleId}
              required
              onChange={(event) => setRuleId(event.currentTarget.value)}
            >
              <option value="">Choose a saved rule</option>
              {rule && !ruleOptions.some((option) => option.id === rule.id) && (
                <option value={rule.id}>{rule.label}</option>
              )}
              {ruleOptions.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Window start (UTC)
            <input name="start" type="datetime-local" step={1} required />
          </label>
          <label>
            Window end (UTC)
            <input name="end" type="datetime-local" step={1} required />
          </label>
        </div>
        {rules.hasNextPage && (
          <button
            className="secondary"
            type="button"
            disabled={rules.isFetchingNextPage}
            onClick={() => void rules.fetchNextPage()}
          >
            Load more rules
          </button>
        )}
        {rule && (
          <details>
            <summary>Rule settings</summary>
            <MonitoringFields
              fields={{
                source: rule.kind,
                protocol: rule.protocol,
                metric: monitoringLabel(rule.metric),
                unit: rule.unit,
                rule_sha256: rule.rule_sha256,
                ...rule.parameters,
              }}
            />
          </details>
        )}
        <p className="muted">
          The end time is excluded from the assessment window.
        </p>
        {(invalidWindow || assess.error) && (
          <p className="form-error" role="alert">
            {invalidWindow || assess.error?.message}
          </p>
        )}
        <button type="submit" disabled={!rule || assess.isPending}>
          Assess monitoring window
        </button>
      </form>
      <section className="panel" aria-label="Saved assessments">
        <h3>Saved assessments</h3>
        <label>
          Saved assessment
          <select
            value={assessmentId}
            onChange={(event) => setAssessmentId(event.currentTarget.value)}
          >
            <option value="">Choose a saved assessment</option>
            {selectedAssessment &&
              !assessmentOptions.some(
                (option) => option.id === selectedAssessment.id,
              ) && (
                <option value={selectedAssessment.id}>
                  {assessmentLabel(selectedAssessment)}
                </option>
              )}
            {assessmentOptions.map((option) => (
              <option key={option.id} value={option.id}>
                {assessmentLabel(option)}
              </option>
            ))}
          </select>
        </label>
        {assessments.hasNextPage && (
          <button
            className="secondary"
            type="button"
            disabled={assessments.isFetchingNextPage}
            onClick={() => void assessments.fetchNextPage()}
          >
            Load more assessments
          </button>
        )}
      </section>
      {selectedAssessment && (
        <MonitoringAssessmentPanel
          key={selectedAssessment.id}
          assessment={selectedAssessment}
          onOpenWorkflow={onOpenWorkflow}
        />
      )}
    </>
  );
}

const tabs = ["Assessments", "Project summaries"] as const;

function Monitoring({ projectId, onOpenWorkflow }: MonitoringProps) {
  const id = useId();
  const [active, setActive] = useState<(typeof tabs)[number]>("Assessments");
  return (
    <section
      className="dashboard-page monitoring-workspace"
      aria-label="Monitoring workspace"
    >
      <h2>Monitoring</h2>
      <div
        className="dashboard-actions"
        role="tablist"
        aria-label="Monitoring views"
      >
        {tabs.map((tab, index) => (
          <button
            key={tab}
            id={`${id}-tab-${index}`}
            type="button"
            role="tab"
            className={active === tab ? undefined : "secondary"}
            aria-selected={active === tab}
            aria-controls={`${id}-panel-${index}`}
            onClick={() => setActive(tab)}
          >
            {tab}
          </button>
        ))}
      </div>
      <div
        role="tabpanel"
        id={`${id}-panel-0`}
        aria-labelledby={`${id}-tab-0`}
        hidden={active !== tabs[0]}
      >
        <MonitoringAssessments
          projectId={projectId}
          onOpenWorkflow={onOpenWorkflow}
        />
      </div>
      {active === tabs[1] && (
        <div
          role="tabpanel"
          id={`${id}-panel-1`}
          aria-labelledby={`${id}-tab-1`}
        >
          <MonitoringProjectSummaries
            projectId={projectId}
            onOpenWorkflow={onOpenWorkflow}
          />
        </div>
      )}
    </section>
  );
}

export function MonitoringWorkspace(props: MonitoringProps) {
  return <Monitoring key={props.projectId} {...props} />;
}
